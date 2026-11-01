from __future__ import annotations

import numpy as np
import pytest

from gmt.vision.minimap import (
    ARROW_RADIUS,
    calibrate_center,
    crop_minimap,
    draw_debug,
    find_player_arrow,
)
from gmt.vision.regions import Circle

from .conftest import draw_arrow, make_frame


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
    # pixel do recorte (linha r, coluna r+40) corresponde a (cy, cx+40) no quadro
    np.testing.assert_array_equal(mm.image[100, 140], frame[125, 209])


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


@pytest.mark.parametrize(("dx", "dy"), [(0, 0), (8, -6), (-10, 5)])
def test_find_player_arrow(dx: int, dy: int) -> None:
    real = Circle(cx=169.0 + dx, cy=125.0 + dy, r=100)
    frame = make_frame(1920, 1080, real, seed=1)
    blob = find_player_arrow(frame, Circle(cx=169.0, cy=125.0, r=100))
    assert blob is not None
    assert blob.x == pytest.approx(real.cx, abs=1)
    assert blob.y == pytest.approx(real.cy, abs=1)


def test_find_player_arrow_none_without_arrow() -> None:
    frame = np.full((1080, 1920, 3), 50, dtype=np.uint8)
    assert find_player_arrow(frame, Circle(cx=169.0, cy=125.0, r=100)) is None


def test_calibrate_center_uses_median_over_rotations() -> None:
    approx = Circle(cx=169.0, cy=125.0, r=100)
    frames = []
    for angle in np.linspace(0, 2 * np.pi, 6, endpoint=False):
        f = np.full((1080, 1920, 3), 60, dtype=np.uint8)
        draw_arrow(f, 172.0, 121.0, 100, angle)
        frames.append(f)
    frames.append(np.full((1080, 1920, 3), 60, dtype=np.uint8))  # quadro sem seta é ignorado
    result = calibrate_center(frames, approx)
    assert result is not None
    found, blobs = result
    assert len(blobs) == 6
    assert (found.cx, found.cy) == pytest.approx((172.0, 121.0), abs=1)
    assert found.r == approx.r


def test_calibrate_center_none_when_no_arrow() -> None:
    blank = np.full((1080, 1920, 3), 60, dtype=np.uint8)
    assert calibrate_center([blank], Circle(169.0, 125.0, 100)) is None


def test_draw_debug_does_not_modify_input(frame_1080p: tuple[np.ndarray, Circle]) -> None:
    frame, circle = frame_1080p
    before = frame.copy()
    out = draw_debug(frame, circle)
    np.testing.assert_array_equal(frame, before)
    assert out.shape == frame.shape
