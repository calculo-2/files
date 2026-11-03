"""Mapa e minimapa sintéticos para testar a localização sem o jogo.

O mapa imita o estilo do Genshin: terreno suave com estradas, prédios e marcos
espalhados de forma única. O minimapa é um recorte circular desse mapa em outra
escala, com brilho alterado, ruído, ícones por cima e a seta no centro.
"""

from __future__ import annotations

import cv2
import numpy as np

from gmt.vision.minimap import Minimap, crop_minimap
from gmt.vision.regions import Circle

from .conftest import draw_arrow

MINIMAP_CIRCLE = Circle(169.0, 125.0, 100.0)


def make_map(size: int = 2400, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    terrain = np.zeros((size, size), np.float32)
    for cells, weight in ((6, 60), (24, 30), (96, 12)):
        noise = rng.random((cells, cells), dtype=np.float32)
        terrain += cv2.resize(noise, (size, size), interpolation=cv2.INTER_CUBIC) * weight
    img = cv2.cvtColor(np.clip(terrain + 70, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)

    n = size * size // 9000
    for _ in range(n):
        kind = rng.integers(0, 4)
        color = tuple(int(c) for c in rng.integers(30, 230, 3))
        x, y = (int(v) for v in rng.integers(0, size, 2))
        if kind == 0:  # estrada
            pts = np.cumsum(rng.integers(-40, 41, (5, 2)), axis=0) + (x, y)
            cv2.polylines(img, [pts.astype(np.int32)], False, color, int(rng.integers(2, 6)))
        elif kind == 1:  # prédio
            w, h = (int(v) for v in rng.integers(8, 40, 2))
            cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
            cv2.rectangle(img, (x, y), (x + w, y + h), (20, 20, 20), 1)
        elif kind == 2:  # marco redondo
            cv2.circle(img, (x, y), int(rng.integers(4, 18)), color, int(rng.choice([-1, 2])))
        else:  # polígono
            pts = rng.integers(-25, 26, (int(rng.integers(3, 7)), 2)) + (x, y)
            cv2.fillPoly(img, [pts.astype(np.int32)], color)
    return img


def make_minimap(
    world: np.ndarray,
    x: float,
    y: float,
    scale: float = 2.0,
    seed: int = 0,
    noise: float = 3.0,
) -> Minimap:
    """Minimapa centrado em (x, y) do mapa; `scale` = px do mapa por px do minimapa."""
    rng = np.random.default_rng(seed)
    r = MINIMAP_CIRCLE.r
    size = int(2 * r + 1)
    # Recorte do mapa na escala do minimapa, centrado exatamente em (x, y).
    m = np.float32([[1 / scale, 0, r - x / scale], [0, 1 / scale, r - y / scale]])
    disc = cv2.warpAffine(world, m, (size, size), flags=cv2.INTER_AREA,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))  # fmt: skip
    disc = np.clip(disc.astype(np.float32) * 0.9 + 18 + rng.normal(0, noise, disc.shape), 0, 255)
    disc = disc.astype(np.uint8)
    for _ in range(3):  # ícones de missão/baú por cima do mapa
        ix, iy = (int(v) for v in rng.integers(30, size - 30, 2))
        cv2.circle(disc, (ix, iy), 7, (240, 240, 250), -1)
        cv2.circle(disc, (ix, iy), 7, (60, 40, 30), 1)
    draw_arrow(disc, r, r, r, float(rng.uniform(0, 2 * np.pi)))

    frame = np.full((1080, 1920, 3), 90, np.uint8)
    c = MINIMAP_CIRCLE
    x0, y0 = int(c.cx - r), int(c.cy - r)
    circle_mask = np.zeros((size, size), np.uint8)
    cv2.circle(circle_mask, (int(r), int(r)), int(r), 255, -1)
    roi = frame[y0 : y0 + size, x0 : x0 + size]
    roi[circle_mask > 0] = disc[circle_mask > 0]
    return crop_minimap(frame, c)
