from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from gmt.localization.localizer import Localizer, LocalizerConfig
from gmt.localization.mapindex import MapIndex
from gmt.localization.tracking import KalmanFilter2D
from gmt.vision.minimap import Minimap

from .synthetic import make_map, make_minimap


@pytest.fixture(scope="module")
def world() -> np.ndarray:
    return make_map(2400, seed=0)


@pytest.fixture(scope="module")
def index(world: np.ndarray) -> MapIndex:
    return MapIndex.build("teyvat", world)


def _err(fix_xy: tuple[float, float] | None, x: float, y: float) -> float:
    assert fix_xy is not None
    return float(np.hypot(fix_xy[0] - x, fix_xy[1] - y))


def test_global_accuracy(world: np.ndarray, index: MapIndex) -> None:
    loc = Localizer([index])
    rng = np.random.default_rng(5)
    errors, fails = [], 0
    for i in range(30):
        x, y = rng.uniform(300, 2100, 2)
        loc.reset()
        fix = loc.update(make_minimap(world, x, y, seed=i), float(i))
        if fix.ok:
            errors.append(_err(fix.raw, x, y))
        else:
            fails += 1
    assert fails <= 3, f"busca global falhou {fails}/30"
    assert max(errors) < 2.0
    assert float(np.mean(errors)) < 0.8
    assert loc.scale == pytest.approx(2.0, rel=0.02)


def test_tracking_follows_path(world: np.ndarray, index: MapIndex) -> None:
    loc = Localizer([index])
    x, y = 800.0, 900.0
    methods, errors = [], []
    for i in range(60):
        x += 5.0
        y += 3.0 * np.sin(i / 5)
        fix = loc.update(make_minimap(world, x, y, seed=100 + i), i * 0.2)
        methods.append(fix.method)
        if fix.raw is not None:
            errors.append(_err(fix.raw, x, y))
    acquired = next(m for m in methods if m != "lost")
    assert acquired == "global"
    assert methods.index("global") <= 3, "deve achar a posição nos primeiros quadros"
    assert methods.count("local") >= 55
    assert max(errors) < 3.0
    assert float(np.mean(errors)) < 1.0


def test_smoothed_position_close_to_truth(world: np.ndarray, index: MapIndex) -> None:
    loc = Localizer([index])
    x = 1000.0
    for i in range(30):
        x += 4.0
        fix = loc.update(make_minimap(world, x, 1200.0, seed=300 + i), i * 0.2)
    assert fix.x is not None and fix.y is not None
    assert _err((fix.x, fix.y), x, 1200.0) < 3.0


def _garbage_minimap(seed: int) -> Minimap:
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 255, (201, 201, 3), dtype=np.uint8), (5, 5), 0)
    template = make_minimap(np.zeros((10, 10, 3), np.uint8), 5, 5)
    return Minimap(image=img, mask=template.mask, circle=template.circle)


def test_lost_after_repeated_failures(world: np.ndarray, index: MapIndex) -> None:
    cfg = LocalizerConfig(lost_after=3)
    loc = Localizer([index], cfg)
    assert loc.update(make_minimap(world, 1500, 1500, seed=1), 0.0).ok
    methods = [loc.update(_garbage_minimap(i), 0.2 * (i + 1)).method for i in range(4)]
    assert methods[:2] == ["predicted", "predicted"]
    assert methods[2:] == ["lost", "lost"]
    # Recupera com a busca global quando o minimapa volta a fazer sentido.
    fix = loc.update(make_minimap(world, 1500, 1500, seed=2), 2.0)
    assert fix.method == "local", "reencontra perto da última posição, sem busca global"
    assert _err(fix.raw, 1500, 1500) < 4.0


def test_unknown_image_never_gives_position(index: MapIndex) -> None:
    loc = Localizer([index])
    for i in range(5):
        assert not loc.update(_garbage_minimap(50 + i), 0.2 * i).ok


def test_teleport_needs_confirmation(world: np.ndarray, index: MapIndex) -> None:
    loc = Localizer([index], LocalizerConfig(teleport_confirmations=2))
    fixes = [
        loc.update(make_minimap(world, 1000 + 4 * i, 1000, seed=400 + i), 0.2 * i) for i in range(5)
    ]
    assert fixes[-1].method == "local"
    first = loc.update(make_minimap(world, 1800, 1700, seed=500), 1.0)
    assert first.method == "predicted", "um salto isolado não deve ser aceito"
    assert first.x is not None and first.x < 1100
    second = loc.update(make_minimap(world, 1800, 1700, seed=501), 1.6)
    assert second.method == "global"
    assert _err((second.x or 0, second.y or 0), 1800, 1700) < 3.0


def test_detects_layer(world: np.ndarray, index: MapIndex) -> None:
    other_world = make_map(1600, seed=7)
    other = MapIndex.build("subterraneo", other_world)
    loc = Localizer([index, other])
    fix = loc.update(make_minimap(other_world, 800, 700, seed=9), 0.0)
    assert fix.layer == "subterraneo"
    assert _err(fix.raw, 800, 700) < 4.0
    fix = loc.update(make_minimap(world, 1200, 1300, seed=10), 5.0)
    assert fix.layer == "teyvat"


def test_fixed_scale_rejects_wrong_zoom(world: np.ndarray, index: MapIndex) -> None:
    loc = Localizer([index], LocalizerConfig(scale=3.0, scale_tolerance=0.1))
    fix = loc.update(make_minimap(world, 1200, 1200, scale=2.0, seed=11), 0.0)
    assert not fix.ok


def test_index_cache_roundtrip(tmp_path: Path, world: np.ndarray) -> None:
    path = tmp_path / "mapa.png"
    ok, buf = cv2.imencode(".png", world[:1200, :1200])
    assert ok
    buf.tofile(str(path))
    first = MapIndex.from_file(path)
    cache = tmp_path / "mapa.png.index.npz"
    assert cache.exists()
    second = MapIndex.from_file(path)
    np.testing.assert_array_equal(first.points, second.points)
    assert second.name == "mapa"


def test_kalman_smooths_constant_velocity() -> None:
    kf = KalmanFilter2D()
    rng = np.random.default_rng(0)
    for i in range(40):
        t = i * 0.2
        kf.update(10 * t + rng.normal(0, 1), 5.0 + rng.normal(0, 1), t)
    px, py = kf.predict(8.0)
    assert px == pytest.approx(80.0, abs=3.0)
    assert py == pytest.approx(5.0, abs=2.0)


def test_kalman_predict_requires_init() -> None:
    with pytest.raises(RuntimeError):
        KalmanFilter2D().predict(0.0)
