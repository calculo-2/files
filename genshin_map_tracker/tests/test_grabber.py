from __future__ import annotations

import numpy as np

from gmt.capture.backends import Frame
from gmt.capture.grabber import CaptureStats, frames, is_black
from gmt.capture.window import GameWindow, Rect

RECT = Rect(0, 0, 64, 36)


class FakeBackend:
    name = "fake"

    def __init__(self, value: int = 120) -> None:
        self.value = value
        self.calls = 0

    def grab(self, rect: Rect) -> Frame | None:
        self.calls += 1
        return np.full((rect.height, rect.width, 3), self.value, dtype=np.uint8)

    def close(self) -> None:
        pass


def _window(foreground: bool = True, minimized: bool = False) -> GameWindow:
    return GameWindow(1, "Genshin Impact", RECT, foreground, minimized)


def test_respects_fps_and_counts() -> None:
    stats = CaptureStats()
    got = list(frames(FakeBackend(), _window, fps=20, stats=stats, duration=0.5))
    assert 7 <= len(got) <= 11  # ~10 quadros em 0,5 s a 20 FPS
    assert stats.frames == len(got)
    assert stats.black_frames == 0
    assert got[0][1] == RECT


def test_skips_when_not_focused() -> None:
    backend = FakeBackend()
    stats = CaptureStats()
    got = list(frames(backend, lambda: _window(foreground=False), 20, stats, 0.2))
    assert got == []
    assert backend.calls == 0
    assert stats.skipped_not_focused > 0


def test_skips_when_game_closed() -> None:
    stats = CaptureStats()
    assert list(frames(FakeBackend(), lambda: None, 20, stats, 0.2)) == []


def test_counts_black_frames() -> None:
    stats = CaptureStats()
    list(frames(FakeBackend(value=0), _window, 20, stats, 0.2))
    assert stats.black_frames == stats.frames > 0


def test_is_black() -> None:
    assert is_black(np.zeros((4, 4, 3), np.uint8))
    assert not is_black(np.full((4, 4, 3), 90, np.uint8))
