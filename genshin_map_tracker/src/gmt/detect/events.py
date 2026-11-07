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
import unicodedata
from collections import deque
from dataclasses import dataclass, field
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


CHEST_PROMPT_WORDS = ("bau", "chest")
CHEST_REWARD_WORDS = ("exp de aventura", "adventure exp", "gema essencial", "primogem")
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
    change_fraction: float = 0.004  # fração de pixels que mudaram para rodar o OCR de novo
    change_level: int = 30  # diferença (0-255) para um pixel contar como mudado
    prompt_memory: float = 8.0  # s: aviso de baú visto há pouco conta como evidência
    cooldown: float = 6.0  # s: ignora repetição do mesmo tipo de coleta
    min_interval: float = 0.4  # s: OCR no máximo ~2,5x por segundo por região


@dataclass
class _RegionState:
    last: Image | None = None
    last_ocr_t: float = -1e9
    lines: list[str] = field(default_factory=list)


class CollectDetector:
    def __init__(self, engine: OcrEngine, config: DetectorConfig | None = None) -> None:
        self.engine = engine
        self.config = config or DetectorConfig()
        self._regions = {"prompt": _RegionState(), "pickup": _RegionState()}
        self._last_chest_prompt = -1e9
        self._last_event: dict[str, float] = {}
        self.recent_text: deque[str] = deque(maxlen=20)
        self.ocr_runs = 0

    def update(self, frame: Image, t: float) -> list[CollectEvent]:
        cfg = self.config
        prompt = self._read("prompt", cfg.prompt_region.crop(frame), t)
        pickup = self._read("pickup", cfg.pickup_region.crop(frame), t)

        if prompt is not None and any(
            fuzzy_contains(line, w) for line in prompt for w in CHEST_PROMPT_WORDS
        ):
            self._last_chest_prompt = t

        events: list[CollectEvent] = []
        if pickup is None:
            return events
        oculi: dict[str, list[str]] = {}
        for line in pickup:
            kind = best_kind(line, OCULUS_WORDS)
            if kind is not None:
                oculi.setdefault(kind, []).append(line)
        for kind, hits in oculi.items():
            events.append(CollectEvent(kind, True, t, tuple(hits)))
        # O OCR pode quebrar "Gema Essencial" em duas caixas: confere também o texto junto.
        joined = " ".join(pickup)
        rewards = tuple(w for w in CHEST_REWARD_WORDS if fuzzy_contains(joined, w))
        if rewards:
            recent_prompt = t - self._last_chest_prompt <= cfg.prompt_memory
            events.append(CollectEvent("chest", recent_prompt, t, rewards))
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
        st.lines = self.engine.read(img)
        self.ocr_runs += 1
        for line in st.lines:
            self.recent_text.append(f"{name}: {line}")
        return st.lines

    def _not_repeated(self, e: CollectEvent) -> bool:
        last = self._last_event.get(e.kind, -1e9)
        if e.t - last < self.config.cooldown:
            return False
        self._last_event[e.kind] = e.t
        return True


class RapidOcr:
    """OCR local com RapidOCR (ONNX, roda na CPU, instala pelo pip)."""

    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError('RapidOCR não instalado: pip install -e ".[ocr]"') from exc
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
