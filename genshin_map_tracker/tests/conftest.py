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
    draw_arrow(frame, circle.cx, circle.cy, circle.r)
    return frame


ARROW_BGR = (249, 220, 12)  # ciano da seta do jogador (HSV ~ 93, 242, 249)


def draw_arrow(frame: np.ndarray, cx: float, cy: float, r: float, angle: float = 0.0) -> None:
    """Seta triangular ciano com o centroide em (cx, cy), apontando em `angle` (rad)."""
    size = r * 0.12
    pts = []
    for k, rad in ((0, 1.6), (1, 1.0), (2, 1.0)):
        a = angle + k * 2 * np.pi / 3
        pts.append((cx + size * rad * np.cos(a), cy + size * rad * np.sin(a)))
    arr = np.array(pts)
    arr += np.array([cx, cy]) - arr.mean(axis=0)
    cv2.fillPoly(frame, [np.rint(arr * 16).astype(np.int32)], ARROW_BGR, cv2.LINE_AA, shift=4)


@pytest.fixture(autouse=True)
def deterministic_opencv() -> None:
    """O índice FLANN usa números aleatórios; fixa a semente para testes repetíveis."""
    cv2.setRNGSeed(0)


@pytest.fixture
def frame_1080p() -> tuple[np.ndarray, Circle]:
    circle = Circle(cx=169.0, cy=125.0, r=100)
    return make_frame(1920, 1080, circle), circle
