from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from gmt.data.markers import ImportMapping, Marker, MarkerStore, parse_markers
from gmt.detect.resolver import ResolverConfig, kinds_for_event, resolve
from gmt.geo.calibration import Calibration, CalibrationError, RefPoint


def _site(x: float, y: float) -> tuple[float, float]:
    """Transformação "verdadeira" de exemplo: escala 0.25, eixo Y invertido (estilo Leaflet)."""
    return 0.25 * x - 300.0, -0.25 * y + 120.0


def _points(n: int, noise: float = 0.0, seed: int = 0) -> list[RefPoint]:
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        x, y = rng.uniform(0, 8000, 2)
        sx, sy = _site(x, y)
        pts.append(
            RefPoint(f"tp{i}", (x, y), (sx + rng.normal(0, noise), sy + rng.normal(0, noise)))
        )
    return pts


@pytest.mark.parametrize("model", ["similarity", "affine"])
def test_calibration_recovers_transform(model: str) -> None:
    cal = Calibration("teyvat", _points(4), model=model)  # type: ignore[arg-type]
    assert max(cal.fit()) < 1e-6
    sx, sy = cal.to_site(1234.0, 5678.0)
    assert (sx, sy) == pytest.approx(_site(1234.0, 5678.0))
    assert cal.to_map(sx, sy) == pytest.approx((1234.0, 5678.0))
    assert cal.scale == pytest.approx(0.25)


def test_similarity_with_two_points_and_noise() -> None:
    cal = Calibration("teyvat", _points(2))
    cal.fit()
    assert cal.to_site(4000, 4000) == pytest.approx(_site(4000, 4000), abs=1e-6)
    noisy = Calibration("teyvat", _points(8, noise=0.5, seed=3))
    res = noisy.fit()
    assert max(res) < 2.0
    assert noisy.to_site(4000, 4000) == pytest.approx(_site(4000, 4000), abs=1.0)


def test_residual_flags_bad_point() -> None:
    pts = _points(5)
    bad = pts[2]
    pts[2] = RefPoint(bad.name, bad.map_xy, (bad.site_xy[0] + 50, bad.site_xy[1]))
    res = Calibration("teyvat", pts).fit()
    assert int(np.argmax(res)) == 2


def test_calibration_needs_points_and_roundtrip(tmp_path: Path) -> None:
    with pytest.raises(CalibrationError):
        Calibration("teyvat", _points(1)).fit()
    with pytest.raises(CalibrationError):
        Calibration("teyvat").to_site(0, 0)
    cal = Calibration("teyvat", _points(3))
    cal.fit()
    path = tmp_path / "cal.json"
    cal.save(path)
    again = Calibration.load(path)
    assert again.to_site(10, 20) == pytest.approx(cal.to_site(10, 20))


@pytest.fixture
def store() -> MarkerStore:
    s = MarkerStore(":memory:")
    s.upsert(
        [
            Marker("c1", "chest", "teyvat", 100, 100),
            Marker("c2", "chest", "teyvat", 103, 100),
            Marker("c3", "chest", "teyvat", 160, 100),
            Marker("a1", "anemoculus", "teyvat", 101, 101),
            Marker("u1", "chest", "enkanomiya", 100, 100),
        ],
        source="teste",
    )
    return s


def test_nearby_filters_kind_layer_and_found(store: MarkerStore) -> None:
    near = store.nearby("teyvat", 100, 100, 10, kinds=["chest"])
    assert [m.id for m, _ in near] == ["c1", "c2"]
    store.mark_found("c1")
    assert [m.id for m, _ in store.nearby("teyvat", 100, 100, 10, kinds=["chest"])] == ["c2"]
    with_found = store.nearby("teyvat", 100, 100, 10, kinds=["chest"], include_found=True)
    assert with_found[0][0].found
    store.unmark("c1")
    assert store.found_ids() == set()
    assert store.count("chest") == 4


def test_progress_export_import(store: MarkerStore, tmp_path: Path) -> None:
    store.mark_found("c1", how="manual")
    store.mark_found("a1")
    path = tmp_path / "progresso.json"
    assert store.export_progress(path) == 2
    other = MarkerStore(tmp_path / "outro.db")
    assert other.import_progress(path) == 2
    assert other.found_ids() == {"c1", "a1"}


def test_resolver_decisions(store: MarkerStore) -> None:
    cfg = ResolverConfig(radius=30)
    # Dois baús a 0 e 3 de distância: ambíguo -> só sugere.
    r = resolve(store, cfg, "chest", "teyvat", 100, 100, 0.9)
    assert r.decision == "suggest" and len(r.candidates) == 2
    # Perto do baú isolado: marca.
    r = resolve(store, cfg, "chest", "teyvat", 158, 100, 0.9)
    assert r.decision == "mark" and r.marker is not None and r.marker.id == "c3"
    # Posição incerta: só sugere.
    assert resolve(store, cfg, "chest", "teyvat", 158, 100, 0.2).decision == "suggest"
    # Oculus de tipo desconhecido procura todos os oculi.
    r = resolve(store, cfg, "oculus", "teyvat", 100, 100, 0.9)
    assert r.decision == "mark" and r.marker is not None and r.marker.id == "a1"
    # Nada por perto.
    assert resolve(store, cfg, "chest", "teyvat", 5000, 5000, 0.9).decision == "none"
    # Camada certa.
    r = resolve(store, cfg, "chest", "enkanomiya", 100, 100, 0.9)
    assert r.marker is not None and r.marker.id == "u1"


def test_kinds_for_event() -> None:
    assert kinds_for_event("chest") == ("chest",)
    assert "pyroculus" in kinds_for_event("oculus")
    with pytest.raises(ValueError):
        kinds_for_event("flor")


def test_parse_markers_generic_json() -> None:
    data = {
        "data": {
            "points": [
                {"pid": 7, "type": 12, "pos": {"lng": 1.5, "lat": -2.0}, "title": "Baú"},
                {"pid": 8, "type": 99, "pos": {"lng": 0, "lat": 0}, "title": "Minério"},
                {"pid": 9, "type": 31, "pos": {"lng": 3, "lat": 4}, "title": "Anemoculus"},
            ]
        }
    }
    mapping = ImportMapping(
        items="data.points", id="pid", kind="type", x="pos.lng", y="pos.lat", name="title",
        kind_map={"12": "chest", "31": "anemoculus"},
    )  # fmt: skip
    markers = parse_markers(json.loads(json.dumps(data)), mapping)
    assert [(m.id, m.kind, m.x, m.y) for m in markers] == [
        ("7", "chest", 1.5, -2.0),
        ("9", "anemoculus", 3.0, 4.0),
    ]
    assert math.isclose(markers[0].y, -2.0)
