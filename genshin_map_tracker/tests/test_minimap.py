from __future__ import annotations

import numpy as np
import pytest

from gmt.vision.minimap import ARROW_RADIUS, crop_minimap, draw_debug, refine_circle
from gmt.vision.regions import Circle

from .conftest import make_frame


def test_crop_shape_and_mask(frame_1080p: tuple[np.ndarray, Circle]) -> None:
    frame, circle = frame_1080p
    mm = crop_minimap(frame, circle)
    assert mm.image.shape == (201, 201, 3)
    assert mm.mask.shape == (201, 201)
    r = 100
    assert mm.mask[r, r] == 0, "centro (seta) deve ficar fora da máscara"
    assert mm.mask[0, 0] == 0, "canto fora do círculo deve ficar fora"
    assert mm.mask[r, r + int(r * ARROW_RADIUS) + 10] == 255, "anel útil deve estar na máscara"
    assert mm.mask[r, 2 * r] == 0, "borda decorativa deve ser descartada"


def test_crop_content_matches_frame(frame_1080p: tuple[np.ndarray, Circle]) -> None:
    frame, circle = frame_1080p
    mm = crop_minimap(frame, circle)
    # pixel do recorte (r+40, r) corresponde a (cx+40, cy) no quadro
    np.testing.assert_array_equal(mm.image[100, 140], frame[125, 208])


def test_masked_and_alpha(frame_1080p: tuple[np.ndarray, Circle]) -> None:
    frame, circle = frame_1080p
    mm = crop_minimap(frame, circle)
    masked = mm.masked()
    assert masked[0, 0].sum() == 0
    bgra = mm.with_alpha()
    assert bgra.shape == (201, 201, 4)
    np.testing.assert_array_equal(bgra[:, :, 3], mm.mask)


def test_crop_near_edge_is_padded() -> None:
    frame = np.full((300, 300, 3), 100, dtype=np.uint8)
    mm = crop_minimap(frame, Circle(cx=20, cy=20, r=50))
    assert mm.image.shape == (101, 101, 3)
    assert mm.mask[0:25, 0:25].max() == 0, "área fora do quadro não pode estar na máscara"


def test_crop_outside_frame_raises() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        crop_minimap(frame, Circle(cx=500, cy=500, r=20))


@pytest.mark.parametrize(("dx", "dy", "dr"), [(0, 0, 0), (8, -6, 4), (-10, 5, -7)])
def test_refine_circle_finds_offset(dx: int, dy: int, dr: int) -> None:
    real = Circle(cx=168 + dx, cy=125 + dy, r=100 + dr)
    frame = make_frame(1920, 1080, real, seed=1)
    found = refine_circle(frame, Circle(cx=168, cy=125, r=100))
    assert found is not None
    assert found.cx == pytest.approx(real.cx, abs=3)
    assert found.cy == pytest.approx(real.cy, abs=3)
    assert found.r == pytest.approx(real.r, abs=4)


def test_refine_circle_none_on_blank() -> None:
    frame = np.full((1080, 1920, 3), 50, dtype=np.uint8)
    assert refine_circle(frame, Circle(cx=168, cy=125, r=100)) is None


def test_draw_debug_does_not_modify_input(frame_1080p: tuple[np.ndarray, Circle]) -> None:
    frame, circle = frame_1080p
    before = frame.copy()
    out = draw_debug(frame, circle)
    np.testing.assert_array_equal(frame, before)
    assert out.shape == frame.shape
