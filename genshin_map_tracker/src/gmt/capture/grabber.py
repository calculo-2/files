"""Laço de captura com limite de FPS e medição de CPU."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import psutil

from gmt.capture.backends import CaptureBackend, Frame
from gmt.capture.window import GameWindow, Rect

log = logging.getLogger(__name__)


@dataclass
class CaptureStats:
    frames: int = 0
    black_frames: int = 0
    skipped_not_focused: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    cpu_samples: list[float] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at

    @property
    def real_fps(self) -> float:
        return self.frames / self.elapsed if self.elapsed > 0 else 0.0

    @property
    def avg_cpu(self) -> float:
        """CPU média do app, em % de UM núcleo (100% = um núcleo cheio)."""
        return sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0.0


def is_black(frame: Frame, threshold: float = 4.0) -> bool:
    """Quadro quase todo preto: sinal de captura bloqueada ou jogo carregando."""
    return float(frame.mean()) < threshold


def frames(
    backend: CaptureBackend,
    locate: Callable[[], GameWindow | None],
    fps: float,
    stats: CaptureStats,
    duration: float | None = None,
) -> Iterator[tuple[Frame, Rect]]:
    """Gera quadros da janela do jogo no ritmo `fps`.

    Pula quadros quando o jogo está minimizado ou fora de foco, para não gastar CPU.
    """
    interval = 1.0 / fps
    proc = psutil.Process()
    proc.cpu_percent(None)  # primeira leitura zera o contador
    last_cpu_sample = time.perf_counter()
    end = None if duration is None else time.perf_counter() + duration

    while end is None or time.perf_counter() < end:
        tick = time.perf_counter()
        window = locate()
        if window is None or window.is_minimized or not window.is_foreground:
            stats.skipped_not_focused += 1
        else:
            frame = backend.grab(window.client)
            if frame is not None:
                stats.frames += 1
                if is_black(frame):
                    stats.black_frames += 1
                yield frame, window.client

        now = time.perf_counter()
        if now - last_cpu_sample >= 1.0:
            stats.cpu_samples.append(proc.cpu_percent(None))
            last_cpu_sample = now

        sleep_for = interval - (time.perf_counter() - tick)
        if sleep_for > 0:
            time.sleep(sleep_for)
