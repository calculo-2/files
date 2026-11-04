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
