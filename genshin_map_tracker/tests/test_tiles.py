from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from gmt.web.tiles import TileJob, download_tiles, estimate, stitch

from .webtools import serve


def test_estimate_and_url() -> None:
    job = TileJob("https://x/t/{z}/{x}/{y}.webp", 5, -2, 1, 0, 2)
    assert job.count == 12
    assert job.pixel_size == (1024, 768)
    assert job.url(-1, 2) == "https://x/t/5/-1/2.webp"
    assert "12 tiles" in estimate(job)


def test_requires_confirmation_and_limit(tmp_path: Path) -> None:
    job = TileJob("http://127.0.0.1:9/{z}/{x}/{y}.png", 1, 0, 9, 0, 9)
    with pytest.raises(PermissionError):
        download_tiles(job, tmp_path)
    with pytest.raises(ValueError):
        download_tiles(job, tmp_path, confirm=True, max_tiles=50)


def test_download_resume_and_stitch(tmp_path: Path) -> None:
    site = tmp_path / "site"
    for x in range(2):
        for y in range(2):
            d = site / "t" / "3" / str(x)
            d.mkdir(parents=True, exist_ok=True)
            img = np.full((256, 256, 3), 40 + 50 * (2 * y + x), np.uint8)
            ok, buf = cv2.imencode(".png", img)
            assert ok
            (d / f"{y}.png").write_bytes(buf.tobytes())
    with serve(site) as base:
        job = TileJob(f"{base}/t/{{z}}/{{x}}/{{y}}.png", 3, 0, 2, 0, 1)  # x=2 não existe
        cache = tmp_path / "cache"
        assert download_tiles(job, cache, delay=0, confirm=True) == 6
        assert download_tiles(job, cache, delay=0, confirm=True) == 0  # tudo em cache
    meta_path = stitch(job, cache, tmp_path / "mapa.png")
    meta = json.loads(meta_path.read_text())
    assert meta == {**meta, "tile_zoom": 3, "tile_origin_x": 0, "tile_origin_y": 0}
    out = cv2.imread(str(tmp_path / "mapa.png"))
    assert out.shape == (512, 768, 3)
    assert out[10, 10, 0] == 40 and out[300, 300, 0] == 190 and out[10, 600, 0] == 0


def test_black_tiles_and_skip() -> None:
    from gmt.web.tiles import parse_black_tiles

    black = parse_black_tiles({"data": {"11": "-1_-3,2_4", "12": "0_0"}}, 11)
    assert black == {(-1, -3), (2, 4)}
    job = TileJob("u/{z}/tile-{x}_{y}.jpg", 11, -1, 2, -3, 4, skip=black, leaflet_offset=1024)
    assert job.count == 4 * 8 - 2
    assert job.url(-1, 2) == "u/11/tile--1_2.jpg"


def test_probe_tile_regex() -> None:
    from gmt.web.probe import TILE_RE

    url = "https://game-cdn.appsample.com/gim/map-teyvat/v72-rc1/11/tile--1_0.jpg"
    m = TILE_RE.search(url)
    assert m is not None and m.groups()[:3] == ("11", "-1", "0")
    assert TILE_RE.search("https://x/t/3/1/2.png") is not None


def test_stitch_y_up(tmp_path: Path) -> None:
    """appsample: y cresce para cima; o tile y=1 fica em cima do y=0."""
    cache = tmp_path / "c"
    cache.mkdir()
    for y, val in ((0, 50), (1, 200)):
        ok, buf = cv2.imencode(".png", np.full((256, 256, 3), val, np.uint8))
        assert ok
        (cache / f"11_0_{y}.img").write_bytes(buf.tobytes())
    job = TileJob("u/{z}/tile-{x}_{y}.jpg", 11, 0, 0, 0, 1, y_up=True, leaflet_offset=1024)
    meta = json.loads(stitch(job, cache, tmp_path / "m.png").read_text())
    out = cv2.imread(str(tmp_path / "m.png"))
    assert out[10, 10, 0] == 200 and out[300, 10, 0] == 50
    # Leaflet: y_leaflet = 1024 - 1 - y_site; topo da imagem = y_site 1 -> y_leaflet 1022.
    assert meta["tile_origin_x"] == 1024 * 256 and meta["tile_origin_y"] == 1022 * 256
