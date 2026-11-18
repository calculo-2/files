"""Regiões da interface do jogo em coordenadas relativas.

A interface do Genshin escala pelo menor lado relativo a 1920x1080 e fica
ancorada nos cantos. O minimapa fica no canto superior esquerdo, então em
ultrawide (21:9) ele não se move para o centro: só escala pela altura.
"""

from __future__ import annotations

from dataclasses import dataclass

from gmt.config import MinimapConfig

REF_WIDTH = 1920
REF_HEIGHT = 1080


@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    r: float


def ui_scale(width: int, height: int) -> float:
    """Fator de escala da interface em relação a 1920x1080."""
    if width <= 0 or height <= 0:
        raise ValueError(f"Resolução inválida: {width}x{height}")
    return min(width / REF_WIDTH, height / REF_HEIGHT)


def minimap_circle(width: int, height: int, ref: MinimapConfig | None = None) -> Circle:
    """Círculo do minimapa (em pixels do quadro) para a resolução dada."""
    ref = ref or MinimapConfig()
    s = ui_scale(width, height)
    return Circle(cx=ref.center_x * s, cy=ref.center_y * s, r=ref.radius * s)


def to_reference(circle: Circle, width: int, height: int) -> MinimapConfig:
    """Converte um círculo medido num quadro de volta para a referência 1080p."""
    s = ui_scale(width, height)
    return MinimapConfig(center_x=circle.cx / s, center_y=circle.cy / s, radius=circle.r / s)
