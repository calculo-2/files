from __future__ import annotations

import cv2
import numpy as np
import pytest

from gmt.vision.regions import Circle


def make_frame(width: int, height: int, circle: Circle, seed: int = 0) -> np.ndarray:
    """Quadro sintético: fundo cinza, minimapa texturizado com borda clara e seta no centro."""
    rng = np.random.default_rng(seed)
    frame = np.full((height, width, 3), 60, dtype=np.uint8)
    texture = rng.integers(80, 200, size=(height, width, 3), dtype=np.uint8)
    texture = cv2.GaussianBlur(texture, (7, 7), 0)
    mask = np.zeros((height, width), dtype=np.uint8)
    c = (int(round(circle.cx)), int(round(circle.cy)))
    cv2.circle(mask, c, int(round(circle.r)), 255, -1)
    frame[mask > 0] = texture[mask > 0]
    cv2.circle(frame, c, int(round(circle.r)), (240, 240, 240), 3)
    cv2.circle(frame, c, max(2, int(circle.r * 0.1)), (0, 220, 255), -1)
    return frame


@pytest.fixture
def frame_1080p() -> tuple[np.ndarray, Circle]:
    circle = Circle(cx=168, cy=125, r=100)
    return make_frame(1920, 1080, circle), circle
