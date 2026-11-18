"""Detecção de coleta e interação pela tela, por OCR em regiões fixas da interface.

Cobre todos os objetos interativos importantes do Genshin Impact (PT-BR e Inglês)
usando exclusivamente captura de tela passiva (zero leitura de memória / zero injeção):
- Baús (Comum, Sofisticado, Precioso, Luxuoso, Estranho/Diagrama) e Santuários das Profundezas,
  incluindo identificação de raridade (`subtype`) e contexto de origem (`buried_chest`,
  `time_trial`, `warrior_challenge`, `seelie`, `electro_seelie`, `monetoo`, `puzzle_chest`);
- Todos os 8 Oculi (Anemo, Geo, Electro, Dendro, Hydro, Pyro, Cryo, Lunoculus);
- Oferendas e coletáveis regionais (Calcedônia Carmesim, Espato Lúmen, Lanterna Lúmen,
  Carpa Espiritual, Pluma da Luz Purificadora, Selo Sagrado, Padrão de Chave, Pérola da Lua
  Antiga, Kuuhenki, Orvalho Kuuvahki, Cristal Kresnik, Gotas de Asas Sombrias, Conjunto Mnemônico);
- Pontos de Teleporte / Teletransporte / Estações de Alta Velocidade / Ancoragem, Estátuas
  dos Sete, Domínios e Observatórios (via prompt de interação e/ou banner central de desbloqueio);
- Guias, Desafios Contra o Tempo, Desafios do Guerreiro, Baús Enterrados ("Escavar") e Enigmas;
- Caixas de Mora, Pilhas de Pedra/Areia e Selos Elementais de exploração (`mora_chest`);
- Colecionáveis permanentes (Cristal Rodopiante Radiante, Receitas, Livros/Tabuletas/Inscrições,
  Lendas Locais, Hilichurl Estranho, Aranara);
- Opcionalmente (`include_respawnables=True`): todas as 64+ Especialidades Locais, 9 Minérios
  e Pontos de Pesca.

Para economizar CPU, o OCR só roda numa região quando a imagem dela mudou e respeita
`min_interval` por região.
"""

from __future__ import annotations

import difflib
import logging
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from gmt.data.catalog import (
    CATALOG,
    MINERAL_SPECS,
    OFFERING_KINDS,
    SPECIALTY_SPECS,
    cooldown_for,
)
from gmt.vision.regions import ui_scale

log = logging.getLogger(__name__)

Image = NDArray[np.uint8]

# Homóglifos cirílicos/gregos frequentes no RapidOCR quando lê caracteres latinos.
_HOMOGLYPHS = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "і": "i",
        "А": "a",
        "Е": "e",
        "О": "o",
        "Р": "p",
        "С": "c",
        "Х": "x",
    }
)


class OcrEngine(Protocol):
    def read(self, image: Image) -> list[str]:
        """Linhas de texto encontradas na imagem."""
        ...


@dataclass(frozen=True)
class Region:
    """Retângulo na referência 1920x1080, ancorado no canto ou centro indicado."""

    name: str
    x: int
    y: int
    w: int
    h: int
    anchor: str = "left"  # "left", "right" ou "center"

    def rect(self, width: int, height: int) -> tuple[int, int, int, int]:
        """(x0, y0, x1, y1) em pixels do quadro dado."""
        s = ui_scale(width, height)
        if self.anchor == "left":
            x = self.x * s
        elif self.anchor == "right":
            x = width - (1920 - self.x) * s
        elif self.anchor == "center":
            x = width / 2.0 + (self.x - 960) * s
        else:
            raise ValueError(f"Âncora inválida: {self.anchor}")
        x0, y0 = max(int(x), 0), max(int(self.y * s), 0)
        x1, y1 = min(int(x + self.w * s), width), min(int((self.y + self.h) * s), height)
        return x0, y0, x1, y1

    def crop(self, frame: Image) -> Image:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self.rect(w, h)
        return frame[y0:y1, x0:x1]


# Regiões da interface na referência 1920x1080:
PROMPT_REGION = Region("prompt", 1150, 420, 520, 260, anchor="right")
PICKUP_REGION = Region("pickup", 1150, 300, 560, 520, anchor="right")
# Lista "Obtido" do lado esquerdo (medida em quadro real 1080p: x 158-464, y 508-724).
OBTAINED_REGION = Region("obtained", 100, 470, 560, 360, anchor="left")
# Avisos centrais no topo ("Ponto de Teleporte desbloqueado", "Desafio Concluído", "Domínio"...).
BANNER_REGION = Region("banner", 660, 205, 600, 95, anchor="center")


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, homóglifos corrigidos, só letras/números/espaço."""
    text = text.translate(_HOMOGLYPHS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def fuzzy_contains(line: str, keyword: str, cutoff: float = 0.82) -> bool:
    """`keyword` aparece em `line`, tolerando erros pequenos de OCR."""
    line, keyword = normalize(line), normalize(keyword)
    if not keyword:
        return False
    if keyword in line or keyword.replace(" ", "") in line.replace(" ", ""):
        return True
    words, k = line.split(), len(keyword.split())
    for i in range(max(len(words) - k + 1, 0)):
        chunk = " ".join(words[i : i + k])
        if difflib.SequenceMatcher(None, chunk, keyword).ratio() >= cutoff:
            return True
    return False


def similarity(line: str, keyword: str) -> float:
    """Melhor semelhança (0 a 1) entre `keyword` e algum trecho de `line`."""
    line, keyword = normalize(line), normalize(keyword)
    if not keyword:
        return 0.0
    if keyword in line or keyword.replace(" ", "") in line.replace(" ", ""):
        return 1.0
    words, k = line.split(), len(keyword.split())
    best = 0.0
    for i in range(max(len(words) - k + 1, 0)):
        chunk = " ".join(words[i : i + k])
        best = max(best, difflib.SequenceMatcher(None, chunk, keyword).ratio())
    return best


def best_kind(line: str, table: dict[str, tuple[str, ...]], cutoff: float = 0.82) -> str | None:
    """Tipo cuja palavra-chave mais se parece com a linha (só um, para não confundir nomes)."""
    if not table:
        return None
    scored = [
        (max((similarity(line, w) for w in words), default=0.0), kind)
        for kind, words in table.items()
        if words
    ]
    if not scored:
        return None
    score, kind = max(scored)
    return kind if score >= cutoff else None


# --- Baús e Santuários ---
CHEST_KINDS_PT = ("comum", "sofisticado", "precioso", "luxuoso", "estranho")
CHEST_SUBTYPE_BY_PT = {
    "comum": "chest_common",
    "sofisticado": "chest_exquisite",
    "precioso": "chest_precious",
    "luxuoso": "chest_luxurious",
    "estranho": "remarkable_chest",
}
CHEST_PROMPT_RE = re.compile(
    r"\bba\w{0,2}\s*(" + "|".join(k[:-1] + r"\w?" for k in CHEST_KINDS_PT) + r")\b"
)
CHEST_PROMPT_EN_MAP: tuple[tuple[str, str], ...] = (
    ("common chest", "chest_common"),
    ("exquisite chest", "chest_exquisite"),
    ("precious chest", "chest_precious"),
    ("luxurious chest", "chest_luxurious"),
    ("remarkable chest", "remarkable_chest"),
)
CHEST_PROMPT_EN = tuple(k for k, _ in CHEST_PROMPT_EN_MAP)
SHRINE_PROMPT = ("santuario das profundezas", "shrine of depths")

CHEST_REWARD_WORDS = ("exp do aventureiro", "adventure exp", "gema essencial", "primogem")
# Valem só logo depois do aviso de um baú. "Selo Cryo" etc. (moeda regional) vem
# na lista de recompensas dos baús de Snezhnaya (visto nas sessões de 07 e 16/11).
CHEST_DROP_WORDS = (
    "exp do heroi", "heros wit", "mora", "minerio", "obtido",
    "selo anemo", "selo geo", "selo electro", "selo dendro", "selo hydro", "selo pyro",
    "selo cryo",
)  # fmt: skip
BLUEPRINT_WORDS = ("diagrama", "furnishing blueprint", "blueprint")
EXACT_WORDS = frozenset({"adventure exp", "heros wit", "primogem"})

# --- Oculi ---
OCULUS_WORDS: dict[str, tuple[str, ...]] = {
    "anemoculus": ("anemoculus", "anemoculo"),
    "geoculus": ("geoculus", "geoculo"),
    "electroculus": ("electroculus", "electroculo", "eletroculo", "eletroculus"),
    "dendroculus": ("dendroculus", "dendroculo"),
    "hydroculus": ("hydroculus", "hidroculo", "hydroculo", "hidroculus"),
    "pyroculus": ("pyroculus", "piroculo", "pyroculo", "piroculus"),
    "cryoculus": ("cryoculus", "crioculo", "cryoculo", "crioculus"),
    "lunoculus": ("lunoculus", "lunoculo"),
}

# --- Oferendas e Coletáveis Regionais ---
OFFERING_WORDS: dict[str, tuple[str, ...]] = {
    k: CATALOG[k].ocr_keywords for k in OFFERING_KINDS if CATALOG[k].ocr_keywords
}

# --- Colecionáveis Permanentes Diretos ---
DIRECT_COLLECTABLE_WORDS: dict[str, tuple[str, ...]] = {
    "spincrystal": ("cristal rodopiante radiante", "radiant spincrystal"),
    "book": (
        "tabuleta de pedra misteriosa",
        "mysterious stone slate",
        "inscricao iridescente",
        "iridescent inscription",
        "fragmento das inscricoes",
        "fragmento da inscricao de khvarena",
    ),
}

# Quantidade de Mora (só usada logo depois de "Escavar").
ANY_MORA_AMOUNT_RE = re.compile(r"\bmora\s*[x×:]?\s*([1-9]\d{0,2}(?:[., ]\d{3})+|\d{4,6})\b")

# --- Especialidades Locais e Minérios (usados quando include_respawnables=True) ---
SPECIALTY_WORDS: dict[str, tuple[str, ...]] = {
    spec.kind: tuple(normalize(w) for w in spec.ocr_keywords if len(normalize(w)) >= 5)
    for spec in SPECIALTY_SPECS
}
MINERAL_WORDS: dict[str, tuple[str, ...]] = {
    spec.kind: tuple(normalize(w) for w in spec.ocr_keywords if len(normalize(w)) >= 5)
    for spec in MINERAL_SPECS
}

# --- Padrões de Banner / Desbloqueio / Contexto ---
UNLOCK_WORDS = ("desbloquead", "unlocked", "novo ponto", "new teleport", "ativad")
TELEPORT_WORDS = (
    "ponto de teleporte",
    "ponto de teletransporte",
    "teleport waypoint",
    "estacao de transporte de alta velocidade",
    "high speed transport station",
    "local de ancoragem do quebra mar",
    "waverider waypoint",
)
STATUE_WORDS = ("estatua dos sete", "statue of the seven", "statue of seven")
DOMAIN_UNLOCK_WORDS = (
    "dominio desbloqueado",
    "domain unlocked",
    "desbloquear dominio",
    "unlock domain",
)
VIEWPOINT_BANNER_WORDS = (
    "observatorio adicionado",
    "novo observatorio",
    "viewpoint unlocked",
    "viewpoint added",
)
VIEWPOINT_PROMPT_WORDS = ("ponto de observacao", "observar", "viewpoint")

CHALLENGE_DONE_WORDS = (
    "desafio concluido",
    "challenge completed",
    "desafio completado",
    "prova concluida",
)
TIME_TRIAL_PROMPT_WORDS = (
    "desafio contra o tempo",
    "desafios contra o tempo",
    "time trial challenge",
    "iniciar desafio",
)
WARRIOR_PROMPT_WORDS = (
    "desafio do guerreiro",
    "warriors challenge",
    "warrior challenge",
    "desafio do totem",
    "totem challenge",
)
LOCAL_LEGEND_WORDS = ("lenda local", "local legend")
RECIPE_RAW_RE = re.compile(r"\b(?:receita|recipe)\s*[:\-]\s*\S{2,}", re.IGNORECASE)
BLUEPRINT_RAW_RE = re.compile(
    r"\b(?:diagrama|furnishing blueprint|blueprint)\s*[:\-]\s*\S{2,}", re.IGNORECASE
)


def reward_hits(text: str, words: tuple[str, ...]) -> tuple[str, ...]:
    """Palavras de recompensa presentes no texto (palavras curtas só como palavra inteira)."""
    norm = normalize(text)
    hits = []
    for w in words:
        if w in EXACT_WORDS:  # termos em inglês: só o texto exato (evita "Aventureiro EXP")
            ok = w in norm
        elif " " in w:
            ok = fuzzy_contains(norm, w)
        else:  # "mora" não pode casar com "Moraes", "obtido" com "obtidos" tudo bem
            ok = re.search(rf"\b{re.escape(w)}", norm) is not None
        if ok:
            hits.append(w)
    return tuple(hits)


def chest_prompt_subtype(line: str) -> str | None:
    """Retorna o subtipo do baú/santuário se a linha for um aviso de interação, ou None."""
    text = normalize(line)
    if any(fuzzy_contains(text, w) for w in SHRINE_PROMPT):
        return "shrine"
    for phrase, subtype in CHEST_PROMPT_EN_MAP:
        if fuzzy_contains(text, phrase):
            return subtype
    m = CHEST_PROMPT_RE.search(text)
    if m:
        matched = m.group(1)
        for pt_key, subtype in CHEST_SUBTYPE_BY_PT.items():
            if matched.startswith(pt_key[:-1]):
                return subtype
        return "chest"
    words = text.split()
    for i, w in enumerate(words[:-1]):
        if w.startswith("ba") and len(w) <= 4:
            nxt = words[i + 1]
            for pt_key, subtype in CHEST_SUBTYPE_BY_PT.items():
                if difflib.SequenceMatcher(None, nxt, pt_key).ratio() >= 0.8:
                    return subtype
    return None


def is_chest_prompt(line: str) -> bool:
    """Aviso de interação de baú ("Baú Comum" etc.), tolerando a leitura "Bat Comum"."""
    return chest_prompt_subtype(line) is not None


def _detect_context_trigger(line: str) -> str | None:
    """Gatilhos de interação que precedem um baú (ex.: Escavar, Desafio, Seelie)."""
    norm = normalize(line)
    if not norm:
        return None
    if any(fuzzy_contains(norm, w) for w in WARRIOR_PROMPT_WORDS):
        return "warrior_challenge"
    if any(fuzzy_contains(norm, w) for w in TIME_TRIAL_PROMPT_WORDS):
        return "time_trial"
    if fuzzy_contains(norm, "seelie electro") or fuzzy_contains(norm, "electro seelie"):
        return "electro_seelie"
    if any(fuzzy_contains(norm, w) for w in ("seelie", "jardim de seelie", "seelie court")):
        return "seelie"
    if fuzzy_contains(norm, "monetoo"):
        return "monetoo"
    if re.search(r"\b(?:escavar|dig)\b", norm) and len(norm) <= 24:
        return "buried_chest"
    if re.search(r"\b(?:investigar|investigate)\b", norm) and len(norm) <= 28:
        return "investigate"
    if fuzzy_contains(norm, "monumento elemental") or fuzzy_contains(norm, "elemental monument"):
        return "elemental_monument"
    return None


def _detect_navigation_or_banner(
    prompt_lines: list[str], banner_lines: list[str]
) -> list[tuple[str, bool, str]]:
    """Teleportes, Estátuas, Domínios, Observatórios, Desafios Concluídos e Lendas Locais."""
    found: list[tuple[str, bool, str]] = []
    all_lines = [(ln, "banner") for ln in banner_lines] + [(ln, "prompt") for ln in prompt_lines]

    for raw, src in all_lines:
        norm = normalize(raw)
        if not norm:
            continue
        unlocked = any(u in norm for u in UNLOCK_WORDS)

        # Não confunde avisos negativos como "Não é possível teleportar"
        if "nao e possivel" in norm or "cannot teleport" in norm:
            continue

        # 1. Ponto de Teleporte: no mundo aberto o aviso [F] só aparece se ainda bloqueado.
        if any(fuzzy_contains(norm, w) for w in TELEPORT_WORDS) and (
            unlocked or (src == "prompt" and len(norm) <= 48)
        ):
            found.append(("teleport", True, raw))
            continue

        # 2. Estátua dos Sete: banner de desbloqueio é certo; prompt sozinho sugere se pendente.
        if any(fuzzy_contains(norm, w) for w in STATUE_WORDS):
            if unlocked:
                found.append(("statue", True, raw))
            elif src == "prompt" and len(norm) <= 36:
                found.append(("statue", False, raw))
            continue

        # 3. Domínio desbloqueado
        if any(fuzzy_contains(norm, w) for w in DOMAIN_UNLOCK_WORDS) or (
            unlocked and re.search(r"\b(?:dominio|domain)\b", norm)
        ):
            found.append(("domain", True, raw))
            continue

        # 4. Observatório (Viewpoint)
        if any(fuzzy_contains(norm, w) for w in VIEWPOINT_BANNER_WORDS):
            found.append(("viewpoint", True, raw))
            continue
        if (
            src == "prompt"
            and len(norm) <= 28
            and any(re.search(rf"\b{re.escape(w)}\b", norm) for w in VIEWPOINT_PROMPT_WORDS)
        ):
            found.append(("viewpoint", False, raw))
            continue

        # 5. Desafio Concluído (banner central)
        if any(fuzzy_contains(norm, w) for w in CHALLENGE_DONE_WORDS):
            found.append(("time_trial", True, raw))
            continue

        # 6. Lenda Local (banner/conquista)
        if src == "banner" and any(fuzzy_contains(norm, w) for w in LOCAL_LEGEND_WORDS):
            found.append(("local_legend", True, raw))
            continue

    return found


def _exact_or_fuzzy_table_match(
    line: str, table: dict[str, tuple[str, ...]], cutoff: float = 0.86
) -> str | None:
    """Casa itens com nomes compostos ou específicos sem falsos positivos em nomes curtos."""
    norm = normalize(line)
    if len(norm) < 4:
        return None
    # Remove sufixos de quantidade ("x1", "x 2", "×3") para comparação limpa
    cleaned = re.sub(r"\s*[x×]\s*\d+\s*$", "", norm).strip()
    cleaned = re.sub(r"^(?:f\s+|obtido\s+)", "", cleaned).strip()
    if len(cleaned) < 4:
        return None
    best_score = 0.0
    best_k: str | None = None
    for kind, words in table.items():
        for w in words:
            if not w:
                continue
            if cleaned == w or re.search(rf"\b{re.escape(w)}\b", norm):
                score = 1.0
            elif len(w) >= 8 and abs(len(cleaned) - len(w)) <= 4:
                score = difflib.SequenceMatcher(None, cleaned, w).ratio()
            else:
                score = 0.0
            if score > best_score:
                best_score, best_k = score, kind
    return best_k if best_score >= cutoff else None


@dataclass(frozen=True)
class CollectEvent:
    kind: str  # "chest", "anemoculus", "teleport", "lumenspar", "mora_chest", ...
    certain: bool  # False: indício fraco, só sugerir
    t: float
    evidence: tuple[str, ...]
    subtype: str | None = None  # ex.: "chest_precious", "remarkable_chest", "shrine"
    context: str | None = None  # ex.: "buried_chest", "time_trial", "seelie", "monetoo"


@dataclass
class DetectorConfig:
    prompt_region: Region = PROMPT_REGION
    pickup_region: Region = PICKUP_REGION
    obtained_region: Region = OBTAINED_REGION
    banner_region: Region | None = BANNER_REGION
    change_fraction: float = 0.004  # fração de pixels que mudaram para rodar o OCR de novo
    change_level: int = 30  # diferença (0-255) para um pixel contar como mudado
    prompt_memory: float = 8.0  # s: aviso de baú visto há pouco conta como evidência
    context_memory: float = 25.0  # s: contexto de Desafio/Seelie/Escavar antes de abrir o baú
    cooldown: float = 6.0  # s: ignora repetição do mesmo tipo de coleta
    chest_cooldown: float = 15.0  # Baú: a lista "Obtido" repete recompensas segundos depois
    min_interval: float = 1.0  # s: OCR no máximo 1x por segundo por região (CPU)
    banner_interval: float = 2.0  # s: aviso central dura alguns segundos; lê menos (CPU)
    include_respawnables: bool = (
        False  # True: detecta também Especialidades Locais, Minérios e Pesca
    )
    enabled_groups: tuple[str, ...] = ()  # vazio = todos os grupos permitidos


@dataclass
class _RegionState:
    last: Image | None = None
    last_ocr_t: float = -1e9
    lines: list[str] = field(default_factory=list)


class CollectDetector:
    def __init__(
        self,
        engine: OcrEngine,
        config: DetectorConfig | None = None,
        record_dir: Path | None = None,
        max_crops: int = 300,
    ) -> None:
        self.engine = engine
        self.config = config or DetectorConfig()
        self.record_dir = record_dir
        self.max_crops = max_crops
        self._crops = 0
        if record_dir is not None:
            record_dir.mkdir(parents=True, exist_ok=True)
        self._regions = {
            "prompt": _RegionState(),
            "pickup": _RegionState(),
            "obtained": _RegionState(),
            "banner": _RegionState(),
        }
        self._last_chest_prompt = -1e9
        self._last_chest_subtype: str | None = None
        self._contexts: dict[str, float] = {}  # contexto -> instante visto
        self._last_event: dict[str, float] = {}
        self.recent_text: deque[str] = deque(maxlen=30)
        self.ocr_runs = 0

    def _group_allowed(self, kind: str) -> bool:
        groups = self.config.enabled_groups
        if not groups:
            return True
        spec = CATALOG.get(kind)
        return kind in groups or (spec is not None and spec.group in groups)

    def _active_puzzle_context(self, t: float) -> str | None:
        """Retorna o contexto recente mais específico (Escavar, Desafio, Seelie, Monetoo...)."""
        mem = self.config.context_memory
        valid: list[tuple[float, str]] = []
        for ctx, seen_t in self._contexts.items():
            if ctx == "investigate":
                continue
            limit = 12.0 if ctx == "buried_chest" else mem
            if 0 <= t - seen_t <= limit:
                valid.append((seen_t, ctx))
        if not valid:
            return None
        valid.sort(reverse=True)
        return valid[0][1]

    def update(self, frame: Image, t: float) -> list[CollectEvent]:
        cfg = self.config
        prompt = self._read("prompt", cfg.prompt_region.crop(frame), t)
        pickup = self._read("pickup", cfg.pickup_region.crop(frame), t)
        obtained = self._read("obtained", cfg.obtained_region.crop(frame), t)
        banner = (
            self._read("banner", cfg.banner_region.crop(frame), t)
            if cfg.banner_region is not None
            else None
        )

        if prompt is None and pickup is None and obtained is None and banner is None:
            return []

        prompt_lines = prompt or []
        pickup_lines = pickup or []
        obtained_lines = obtained or []
        banner_lines = banner or []
        seen = prompt_lines + pickup_lines + obtained_lines
        all_seen = seen + banner_lines

        # 1. Registra avisos de baú (com raridade/subtipo) e contextos de interação.
        for line in seen:
            sub = chest_prompt_subtype(line)
            if sub is not None:
                self._last_chest_prompt = t
                self._last_chest_subtype = sub
            ctx = _detect_context_trigger(line)
            if ctx is not None:
                self._contexts[ctx] = t

        events: list[CollectEvent] = []

        # 2. Oculi (8 nações/regiões)
        oculi: dict[str, list[str]] = {}
        for line in seen:
            kind = best_kind(line, OCULUS_WORDS)
            if kind is not None:
                oculi.setdefault(kind, []).append(line)
        for kind, hits in oculi.items():
            events.append(CollectEvent(kind, True, t, tuple(hits)))

        # 3. Oferendas e Coletáveis Regionais (Calcedônia, Espato Lúmen, Carpa, Pluma, etc.)
        offerings: dict[str, list[str]] = {}
        for line in seen:
            kind = _exact_or_fuzzy_table_match(line, OFFERING_WORDS, cutoff=0.84)
            if kind is not None:
                offerings.setdefault(kind, []).append(line)
        for kind, hits in offerings.items():
            events.append(CollectEvent(kind, True, t, tuple(hits)))

        # 4. Colecionáveis Permanentes Diretos (Cristal Rodopiante Radiante, Receitas, Tabuletas)
        collectables: dict[str, list[str]] = {}
        for line in seen:
            kind = _exact_or_fuzzy_table_match(line, DIRECT_COLLECTABLE_WORDS, cutoff=0.85)
            if kind is not None:
                collectables.setdefault(kind, []).append(line)
            elif RECIPE_RAW_RE.search(line):
                collectables.setdefault("recipe", []).append(line)
        # Receita/livro dentro da lista de recompensas de um baú é só item do baú.
        chest_drop_list = (t - self._last_chest_prompt) <= cfg.prompt_memory or bool(
            reward_hits(" ".join(seen), CHEST_REWARD_WORDS)
        )
        for kind, hits in collectables.items():
            if chest_drop_list and kind in ("recipe", "book"):
                continue
            events.append(CollectEvent(kind, True, t, tuple(hits)))

        # 5. Navegação, Desbloqueios, Desafios Concluídos e Lendas Locais (prompt + banner)
        nav_hits = _detect_navigation_or_banner(prompt_lines + pickup_lines, banner_lines)
        by_nav: dict[str, tuple[bool, list[str]]] = {}
        for kind, cert, raw in nav_hits:
            if (
                kind == "time_trial"
                and 0 <= t - self._contexts.get("warrior_challenge", -1e9) <= 45
            ):
                kind = "warrior_challenge"
            if kind in ("time_trial", "warrior_challenge"):
                self._contexts[kind] = t
            prev_cert, prev_ev = by_nav.get(kind, (False, []))
            by_nav[kind] = (prev_cert or cert, [*prev_ev, raw])
        for kind, (cert, hits) in by_nav.items():
            events.append(CollectEvent(kind, cert, t, tuple(hits)))

        # 6. Baús (incluindo Baú Estranho por Diagrama, Santuários e contexto de Enigma/Desafio)
        joined = " ".join(seen)
        recent_prompt = (t - self._last_chest_prompt) <= cfg.prompt_memory
        strong = reward_hits(joined, CHEST_REWARD_WORDS)
        drops = reward_hits(joined, CHEST_DROP_WORDS) if recent_prompt else ()
        blueprints = (
            reward_hits(joined, BLUEPRINT_WORDS)
            if (recent_prompt and self._last_chest_subtype == "remarkable_chest")
            or BLUEPRINT_RAW_RE.search(" ".join(seen))
            else ()
        )
        chest_detected = bool(strong or drops or blueprints)
        if chest_detected:
            subtype = self._last_chest_subtype if recent_prompt else None
            if blueprints and subtype is None:
                subtype = "remarkable_chest"
            puzzle_ctx = self._active_puzzle_context(t)
            certain = recent_prompt or bool(blueprints)
            events.append(
                CollectEvent(
                    "chest",
                    certain,
                    t,
                    strong + drops + blueprints,
                    subtype=subtype,
                    context=puzzle_ctx,
                )
            )

        # 7. Tesouro enterrado ("Escavar") que dá Mora: só sugestão.
        # Sessões reais mostraram que "Mora x15000"/"x20000" e "Selo Cryo" aparecem em
        # recompensas de missão/mecânica regional e em baús comuns; não indicam Caixa de Mora.
        if not chest_detected and not oculi:
            norm_joined = normalize(joined)
            recent_dig = 0 <= t - self._contexts.get("buried_chest", -1e9) <= 8.0
            m_amt = ANY_MORA_AMOUNT_RE.search(norm_joined) if recent_dig else None
            if m_amt and int(re.sub(r"\D", "", m_amt.group(1)) or "0") >= 1000:
                events.append(CollectEvent("mora_chest", False, t, (m_amt.group(0),)))

        # 8. Recursos Respawnáveis (Especialidades Locais, Minérios e Pesca) — opcionais
        if cfg.include_respawnables:
            item_lines = pickup_lines + obtained_lines
            respawn_hits: dict[str, list[str]] = {}
            for line in item_lines:
                sp = _exact_or_fuzzy_table_match(line, SPECIALTY_WORDS, cutoff=0.87)
                if sp is not None:
                    respawn_hits.setdefault(sp, []).append(line)
                    continue
                mn = _exact_or_fuzzy_table_match(line, MINERAL_WORDS, cutoff=0.87)
                if mn is not None:
                    respawn_hits.setdefault(mn, []).append(line)
            for line in prompt_lines:
                norm_p = normalize(line)
                if len(norm_p) <= 20 and re.search(r"\b(?:pescar|fish|ponto de pesca)\b", norm_p):
                    respawn_hits.setdefault("fishing_spot", []).append(line)
            for kind, hits in respawn_hits.items():
                events.append(CollectEvent(kind, True, t, tuple(hits)))

        _ = all_seen  # mantém leitura consolidada explícita
        return [e for e in events if self._group_allowed(e.kind) and self._not_repeated(e)]

    def _read(self, name: str, img: Image, t: float) -> list[str] | None:
        """OCR da região se ela mudou; None quando nada mudou."""
        st = self._regions[name]
        interval = self.config.banner_interval if name == "banner" else self.config.min_interval
        if img.size == 0 or t - st.last_ocr_t < interval:
            return None
        size = (img.shape[1] // 2 or 1, img.shape[0] // 2 or 1)
        small = np.asarray(cv2.resize(img, size), np.uint8)
        if name == "banner" and st.last is None and int(np.max(small)) == 0:
            st.last, st.last_ocr_t = small, t
            return None
        if st.last is not None and st.last.shape == small.shape:
            diff = cv2.absdiff(small, st.last)
            changed = (diff.max(axis=2) if diff.ndim == 3 else diff) > self.config.change_level
            if float(changed.mean()) < self.config.change_fraction:
                return None
        st.last, st.last_ocr_t = small, t
        previous = st.lines
        st.lines = self.engine.read(img)
        self.ocr_runs += 1
        for line in st.lines:
            self.recent_text.append(f"{name}: {line}")
        if self.record_dir is not None and st.lines and set(st.lines) != set(previous):
            self._record(name, img, st.lines)
        return st.lines

    def _record(self, name: str, img: Image, lines: list[str]) -> None:
        stamp = time.strftime("%H%M%S")
        with (self.record_dir / "ocr.log").open("a", encoding="utf-8") as fh:  # type: ignore[operator]
            fh.write(f"[{stamp}] {name}: {' | '.join(lines)}\n")
        if self._crops < self.max_crops:
            self._crops += 1
            path = self.record_dir / f"{stamp}_{self._crops:03d}_{name}.jpg"  # type: ignore[operator]
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                buf.tofile(str(path))

    def _not_repeated(self, e: CollectEvent) -> bool:
        last = self._last_event.get(e.kind, -1e9)
        wait = cooldown_for(
            e.kind, default=self.config.cooldown, chest_cooldown=self.config.chest_cooldown
        )
        if e.t - last < wait:
            return False
        self._last_event[e.kind] = e.t
        return True


class RapidOcr:
    """OCR local com RapidOCR (ONNX, roda na CPU, instala pelo pip)."""

    def __init__(self, threads: int = 2) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError('RapidOCR não instalado: pip install -e ".[ocr]"') from exc
        _limit_onnx_threads(threads)
        self._engine = RapidOCR()

    def read(self, image: Image) -> list[str]:
        result, _ = self._engine(image)
        return [str(item[1]) for item in (result or [])]

    def read_boxes(self, image: Image) -> list[tuple[list[list[float]], str, float]]:
        result, _ = self._engine(image)
        return [(item[0], str(item[1]), float(item[2])) for item in (result or [])]


class ThreadedDetector:
    """Roda o detector noutra thread para o OCR não atrasar o rastreio."""

    def __init__(self, detector: CollectDetector) -> None:
        import threading

        self.detector = detector
        self._lock = threading.Lock()
        self._pending: tuple[Image, float] | None = None
        self._events: list[CollectEvent] = []
        self._wake = threading.Event()
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def update(self, frame: Image, t: float) -> list[CollectEvent]:
        with self._lock:
            self._pending = (frame, t)
            events, self._events = self._events, []
        self._wake.set()
        return events

    def _loop(self) -> None:
        while not self._stop:
            self._wake.wait(0.5)
            self._wake.clear()
            with self._lock:
                job, self._pending = self._pending, None
            if job is None:
                continue
            try:
                found = self.detector.update(*job)
            except Exception:  # noqa: BLE001 - OCR falhou num quadro: segue no próximo
                log.exception("Falha no detector de coleta")
                continue
            if found:
                with self._lock:
                    self._events.extend(found)

    def close(self) -> None:
        self._stop = True
        self._wake.set()
        self._thread.join(timeout=2.0)


def _limit_onnx_threads(threads: int) -> None:
    try:
        import onnxruntime as ort
        import rapidocr_onnxruntime.utils as rutils
    except ImportError:
        return

    def options() -> object:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        return opts

    if hasattr(rutils, "SessionOptions"):
        rutils.SessionOptions = options
