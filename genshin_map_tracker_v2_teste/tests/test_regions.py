from __future__ import annotations

import pytest

from gmt.config import MinimapConfig
from gmt.vision.regions import Circle, minimap_circle, to_reference, ui_scale


@pytest.mark.parametrize(
    ("w", "h", "scale"),
    [
        (1920, 1080, 1.0),
        (2560, 1440, 4 / 3),
        (1366, 768, 768 / 1080),
        (3440, 1440, 4 / 3),  # ultrawide escala pela altura
        (2560, 1080, 1.0),
        (1920, 1200, 1.0),  # 16:10 escala pela largura
    ],
)
def test_ui_scale(w: int, h: int, scale: float) -> None:
    assert ui_scale(w, h) == pytest.approx(scale)


def test_ui_scale_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        ui_scale(0, 1080)


def test_minimap_circle_scales_from_top_left() -> None:
    ref = MinimapConfig(center_x=168, center_y=125, radius=100)
    c = minimap_circle(2560, 1440, ref)
    assert (c.cx, c.cy, c.r) == pytest.approx((224, 166.667, 133.333), rel=1e-3)
    # Ultrawide: o minimapa fica no mesmo lugar que em 16:9 com a mesma altura.
    assert minimap_circle(3440, 1440, ref) == c


@pytest.mark.parametrize(("w", "h"), [(1920, 1080), (2560, 1440), (1366, 768), (3440, 1440)])
def test_reference_round_trip(w: int, h: int) -> None:
    ref = MinimapConfig(center_x=170.5, center_y=123.0, radius=98.0)
    back = to_reference(minimap_circle(w, h, ref), w, h)
    assert (back.center_x, back.center_y, back.radius) == pytest.approx(
        (ref.center_x, ref.center_y, ref.radius)
    )


def test_circle_is_value_object() -> None:
    assert Circle(1, 2, 3) == Circle(1.0, 2.0, 3.0)
