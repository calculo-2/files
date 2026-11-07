"""Detecção de coleta pela tela, por OCR em regiões fixas da interface.

O que se procura (jogo em PT-BR; inglês também aceito):
- Baú: o aviso de interação com o nome do baú ("Baú Comum", "Baú Precioso"...) e,
  logo depois, a lista de itens recebidos com recompensas típicas de baú
  ("EXP de Aventura", "Gema Essencial", "Mora").
- Oculus: a lista de itens recebidos mostrando o nome do oculus.

ATENÇÃO: as regiões e os textos exatos ainda precisam ser confirmados com prints
reais (use `gmt detect-test`). Os nomes em PT-BR de alguns itens são estimativas;
por isso a comparação ignora acentos e aceita pequenas diferenças.

Para economizar CPU, o OCR só roda numa região quando a imagem dela mudou.
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

from gmt.vision.regions import ui_scale

log = logging.getLogger(__name__)

Image = NDArray[np.uint8]


class OcrEngine(Protocol):
    def read(self, image: Image) -> list[str]:
        """Linhas de texto encontradas na imagem."""
        ...


@dataclass(frozen=True)
class Region:
    """Retângulo na referência 1920x1080, ancorado no canto indicado."""

    name: str
    x: int
    y: int
    w: int
    h: int
    anchor: str = "left"  # "left" ou "right": de qual lado da tela a interface se prende

    def rect(self, width: int, height: int) -> tuple[int, int, int, int]:
        """(x0, y0, x1, y1) em pixels do quadro dado."""
        s = ui_scale(width, height)
        x = self.x * s if self.anchor == "left" else width - (1920 - self.x) * s
        x0, y0 = max(int(x), 0), max(int(self.y * s), 0)
        x1, y1 = min(int(x + self.w * s), width), min(int((self.y + self.h) * s), height)
        return x0, y0, x1, y1

    def crop(self, frame: Image) -> Image:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self.rect(w, h)
        return frame[y0:y1, x0:x1]


# Estimativas iniciais para 1920x1080 (a confirmar com prints reais).
PROMPT_REGION = Region("prompt", 1150, 420, 520, 260, anchor="right")
PICKUP_REGION = Region("pickup", 1150, 300, 560, 520, anchor="right")
# Lista "Obtido" do lado esquerdo (medida em quadro real 1080p: x 158-464, y 508-724).
OBTAINED_REGION = Region("obtained", 100, 470, 560, 360, anchor="left")


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, só letras/números/espaço."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def fuzzy_contains(line: str, keyword: str, cutoff: float = 0.82) -> bool:
    """`keyword` aparece em `line`, tolerando erros pequenos de OCR.

    O OCR às vezes junta palavras ("expde aventura"), então também compara sem espaços.
    """
    line, keyword = normalize(line), normalize(keyword)
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
    scored = [(max(similarity(line, w) for w in words), kind) for kind, words in table.items()]
    score, kind = max(scored)
    return kind if score >= cutoff else None


# Nomes reais no jogo em PT-BR (conferidos no site e em prints do jogo, 07/11/2026):
# "Baú Comum", "Baú Sofisticado", "Baú Precioso", "Baú Luxuoso", "Baú Estranho".
# O aviso tem letra branca sobre fundo claro e o OCR lê "Baú" como "Bat"/"Bau"/"Ba".
CHEST_KINDS_PT = ("comum", "sofisticado", "precioso", "luxuoso", "estranho")
CHEST_PROMPT_RE = re.compile(
    r"\bba\w{0,2}\s*(" + "|".join(k[:-1] + r"\w?" for k in CHEST_KINDS_PT) + r")\b"
)
CHEST_PROMPT_EN = ("common chest", "exquisite chest", "precious chest", "luxurious chest")
# Santuário das Profundezas (aberto com chave): o site o lista junto com os baús.
SHRINE_PROMPT = ("santuario das profundezas", "shrine of depths")
# Recompensa que só baú dá no mundo aberto. Real no jogo: "EXP do Aventureiro".
# Valem sozinhas (indício fraco): quase só baú dá isso no mundo aberto.
CHEST_REWARD_WORDS = ("exp do aventureiro", "adventure exp", "gema essencial", "primogem")
# Valem só logo depois do aviso de um baú (sozinhas aparecem em outras situações, como
# Mora ao derrotar inimigos). Vistas em sessões reais: "EXP do Herói" depois de
# "Baú Sofisticado"; a lista "Obtido" da esquerda.
CHEST_DROP_WORDS = ("exp do heroi", "heros wit", "mora", "minerio", "obtido")
EXACT_WORDS = frozenset({"adventure exp", "heros wit", "primogem"})


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


def is_chest_prompt(line: str) -> bool:
    """Aviso de interação de baú ("Baú Comum" etc.), tolerando a leitura "Bat Comum"."""
    text = normalize(line)
    if CHEST_PROMPT_RE.search(text):
        return True
    words = text.split()
    for i, w in enumerate(words[:-1]):  # "ba?" + tipo do baú parecido (erro de OCR no tipo)
        if w.startswith("ba") and len(w) <= 4:
            nxt = words[i + 1]
            if any(difflib.SequenceMatcher(None, nxt, k).ratio() >= 0.8 for k in CHEST_KINDS_PT):
                return True
    return any(fuzzy_contains(text, w) for w in CHEST_PROMPT_EN + SHRINE_PROMPT)


OCULUS_WORDS = {
    "anemoculus": ("anemoculus", "anemoculo"),
    "geoculus": ("geoculus", "geoculo"),
    "electroculus": ("electroculus", "electroculo", "eletroculo"),
    "dendroculus": ("dendroculus", "dendroculo"),
    "hydroculus": ("hydroculus", "hidroculo", "hydroculo"),
    "pyroculus": ("pyroculus", "piroculo", "pyroculo"),
    "cryoculus": ("cryoculus", "crioculo", "cryoculo"),
    "lunoculus": ("lunoculus", "lunoculo"),
}


@dataclass(frozen=True)
class CollectEvent:
    kind: str  # "chest" ou o tipo do oculus
    certain: bool  # False: indício fraco, só sugerir
    t: float
    evidence: tuple[str, ...]


@dataclass
class DetectorConfig:
    prompt_region: Region = PROMPT_REGION
    pickup_region: Region = PICKUP_REGION
    obtained_region: Region = OBTAINED_REGION
    change_fraction: float = 0.004  # fração de pixels que mudaram para rodar o OCR de novo
    change_level: int = 30  # diferença (0-255) para um pixel contar como mudado
    prompt_memory: float = 8.0  # s: aviso de baú visto há pouco conta como evidência
    cooldown: float = 6.0  # s: ignora repetição do mesmo tipo de coleta
    # Baú: a lista "Obtido" da esquerda repete as recompensas alguns segundos depois.
    chest_cooldown: float = 15.0
    min_interval: float = 1.0  # s: OCR no máximo 1x por segundo por região (CPU)


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
        # Registro para calibrar: texto lido (ocr.log) e recortes das regiões com texto novo.
        self.record_dir = record_dir
        self.max_crops = max_crops
        self._crops = 0
        if record_dir is not None:
            record_dir.mkdir(parents=True, exist_ok=True)
        self._regions = {
            "prompt": _RegionState(),
            "pickup": _RegionState(),
            "obtained": _RegionState(),
        }
        self._last_chest_prompt = -1e9
        self._last_event: dict[str, float] = {}
        self.recent_text: deque[str] = deque(maxlen=20)
        self.ocr_runs = 0

    def update(self, frame: Image, t: float) -> list[CollectEvent]:
        cfg = self.config
        prompt = self._read("prompt", cfg.prompt_region.crop(frame), t)
        pickup = self._read("pickup", cfg.pickup_region.crop(frame), t)
        obtained = self._read("obtained", cfg.obtained_region.crop(frame), t)

        # O aviso do baú e a lista de itens aparecem no mesmo lugar: confere as duas regiões.
        seen = (prompt or []) + (pickup or []) + (obtained or [])
        if any(is_chest_prompt(line) for line in seen):
            self._last_chest_prompt = t

        events: list[CollectEvent] = []
        if prompt is None and pickup is None and obtained is None:
            return events
        oculi: dict[str, list[str]] = {}
        for line in seen:
            kind = best_kind(line, OCULUS_WORDS)
            if kind is not None:
                oculi.setdefault(kind, []).append(line)
        for kind, hits in oculi.items():
            events.append(CollectEvent(kind, True, t, tuple(hits)))
        # O OCR pode quebrar "Gema Essencial" em duas caixas: confere também o texto junto.
        joined = " ".join(seen)
        recent_prompt = t - self._last_chest_prompt <= cfg.prompt_memory
        strong = reward_hits(joined, CHEST_REWARD_WORDS)
        drops = reward_hits(joined, CHEST_DROP_WORDS) if recent_prompt else ()
        if strong or drops:
            events.append(CollectEvent("chest", recent_prompt, t, strong + drops))
        return [e for e in events if self._not_repeated(e)]

    def _read(self, name: str, img: Image, t: float) -> list[str] | None:
        """OCR da região se ela mudou; None quando nada mudou."""
        st = self._regions[name]
        if img.size == 0 or t - st.last_ocr_t < self.config.min_interval:
            return None
        # Texto novo ocupa pouca área: mede a fração de pixels que mudaram bastante,
        # e não a diferença média da região inteira.
        size = (img.shape[1] // 2 or 1, img.shape[0] // 2 or 1)
        small = np.asarray(cv2.resize(img, size), np.uint8)
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
        wait = self.config.chest_cooldown if e.kind == "chest" else self.config.cooldown
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
    """Roda o detector noutra thread para o OCR não atrasar o rastreio.

    Sempre processa o quadro mais recente; quadros que chegam enquanto o OCR
    trabalha são descartados (a notificação do jogo fica vários segundos na tela).
    """

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
    """Limita as threads do onnxruntime usado pelo RapidOCR (por padrão ele usa todos
    os núcleos, o que disputava CPU com o jogo). A versão 1.2 do RapidOCR não tem
    opção para isso; trocamos a fábrica de SessionOptions do módulo dele."""
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
