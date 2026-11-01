"""Recorte e limpeza do minimapa circular."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from gmt.vision.regions import Circle

log = logging.getLogger(__name__)

Image = NDArray[np.uint8]

# Fração do raio descartada na borda (anel decorativo do minimapa).
EDGE_TRIM = 0.06
# Fração do raio ocupada pela seta do jogador no centro.
ARROW_RADIUS = 0.16


@dataclass(frozen=True)
class Minimap:
    image: Image  # recorte quadrado BGR, sem máscara
    mask: Image  # 255 = pixel útil do mapa, 0 = descartar
    circle: Circle  # círculo no sistema de coordenadas do recorte

    def masked(self) -> Image:
        """Imagem BGR com tudo fora da máscara zerado."""
        return np.asarray(cv2.bitwise_and(self.image, self.image, mask=self.mask), np.uint8)

    def with_alpha(self) -> Image:
        """Imagem BGRA com fundo transparente, boa para salvar em PNG e conferir."""
        bgra = np.asarray(cv2.cvtColor(self.image, cv2.COLOR_BGR2BGRA), np.uint8)
        bgra[:, :, 3] = self.mask
        return bgra


def crop_minimap(frame: Image, circle: Circle) -> Minimap:
    """Recorta o quadrado em volta do minimapa e monta a máscara útil.

    Se o círculo encostar na borda do quadro, a parte de fora vira preto e sai da máscara.
    """
    h, w = frame.shape[:2]
    r = int(round(circle.r))
    cx, cy = int(round(circle.cx)), int(round(circle.cy))
    size = 2 * r + 1

    x0, y0 = cx - r, cy - r
    crop = np.zeros((size, size, 3), dtype=np.uint8)
    inside = np.zeros((size, size), dtype=np.uint8)

    sx0, sy0 = max(x0, 0), max(y0, 0)
    sx1, sy1 = min(x0 + size, w), min(y0 + size, h)
    if sx1 <= sx0 or sy1 <= sy0:
        raise ValueError("Círculo do minimapa está fora do quadro.")
    crop[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = frame[sy0:sy1, sx0:sx1, :3]
    inside[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = 255

    mask = np.zeros((size, size), dtype=np.uint8)
    useful_r = max(1, int(round(r * (1 - EDGE_TRIM))))
    cv2.circle(mask, (r, r), useful_r, 255, thickness=-1)
    cv2.circle(mask, (r, r), max(1, int(round(r * ARROW_RADIUS))), 0, thickness=-1)
    mask = np.asarray(cv2.bitwise_and(mask, inside), np.uint8)

    return Minimap(image=crop, mask=mask, circle=Circle(cx=float(r), cy=float(r), r=float(r)))


def refine_circle(frame: Image, approx: Circle, search: float = 0.35) -> Circle | None:
    """Procura o contorno real do minimapa perto do círculo estimado.

    Usa a transformada de Hough. Retorna None se não achar um círculo plausível.
    """
    h, w = frame.shape[:2]
    pad = int(approx.r * (1 + search))
    x0, y0 = max(int(approx.cx) - pad, 0), max(int(approx.cy) - pad, 0)
    x1, y1 = min(int(approx.cx) + pad, w), min(int(approx.cy) + pad, h)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    gray = cv2.medianBlur(gray, 5)
    found = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.0,
        minDist=approx.r,
        param1=100,
        param2=30,
        minRadius=int(approx.r * (1 - search)),
        maxRadius=int(approx.r * (1 + search)),
    )
    if found is None:
        return None

    best: Circle | None = None
    best_dist = float("inf")
    for cx, cy, r in found[0]:
        c = Circle(cx=float(cx) + x0, cy=float(cy) + y0, r=float(r))
        dist = float(np.hypot(c.cx - approx.cx, c.cy - approx.cy))
        if dist < best_dist:
            best, best_dist = c, dist
    if best is None or best_dist > approx.r * search:
        return None
    return best


def draw_debug(frame: Image, circle: Circle) -> Image:
    """Cópia do quadro com o círculo do minimapa desenhado, para conferência."""
    out = frame[:, :, :3].copy()
    center = (int(round(circle.cx)), int(round(circle.cy)))
    cv2.circle(out, center, int(round(circle.r)), (0, 255, 0), 2)
    cv2.circle(out, center, int(round(circle.r * ARROW_RADIUS)), (0, 0, 255), 1)
    cv2.drawMarker(out, center, (0, 255, 255), cv2.MARKER_CROSS, 12, 1)
    return out
