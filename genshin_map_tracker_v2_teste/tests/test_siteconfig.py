from __future__ import annotations

import json
from pathlib import Path

import pytest

from gmt.config import load_config
from gmt.web.prepare import add_to_config
from gmt.web.siteconfig import SiteConfigError, page_url, parse_site_maps


def fake_page(maps: list[object]) -> str:
    """Imita o formato do Next.js: JSON dentro de uma string JS em self.__next_f.push."""
    payload = '1:{"config":{"id":"gim","maps":' + json.dumps(maps) + "}}"
    escaped = json.dumps(payload)[1:-1]
    return f'<html><script>self.__next_f.push([1,"{escaped}"])</script></html>'


TEYVAT = {
    "id": 2,
    "key": "teyvat",
    "tiles": {
        "type": "centered",
        "urlTemplate": "https://cdn/x/v1/{z}/tile-{x}_{y}.jpg",
        "tileSize": 256,
        "minZoom": 10,
        "maxZoom": 15,
        "tileBounds": {"14": {"minX": -32, "maxX": 31, "minY": -32, "maxY": 43}},
        "blackTilesUrl": "https://cdn/x/v1/black-tile.json",
    },
}


def test_parse_site_maps() -> None:
    other = {"id": 9, "key": "chasm", "tiles": {"urlTemplate": "u", "tileBounds": "$5:ref"}}
    maps = parse_site_maps(fake_page([TEYVAT, other, "$6:ref"]))
    assert [m.key for m in maps] == ["teyvat"]
    m = maps[0]
    assert m.tile_bounds[14] == (-32, 31, -32, 43)
    assert m.centered and m.leaflet_offset(14) == 8192
    assert m.black_tiles_url == "https://cdn/x/v1/black-tile.json"


def test_parse_errors_and_urls() -> None:
    with pytest.raises(SiteConfigError):
        parse_site_maps("<html>nada</html>")
    assert page_url("teyvat").endswith("/pt/")
    assert page_url("chasm").endswith("/pt/chasm/")
    with pytest.raises(SiteConfigError):
        page_url("atlantida")


def test_add_to_config_replaces_layer(tmp_path: Path) -> None:
    meta = tmp_path / "m.json"
    meta.write_text(json.dumps({"tile_zoom": 14, "tile_origin_x": 10, "tile_origin_y": 20}))
    cfg = tmp_path / "config.toml"
    cfg.write_text('[capture]\nfps = 5\n\n[[maps]]\nlayer = "teyvat"\nimage = "velho.png"\n'
                   "\n[detect]\nauto_mark = false\n", encoding="utf-8")  # fmt: skip
    assert add_to_config(cfg, "teyvat", Path("mapas/teyvat_z14.png"), meta)
    loaded = load_config(cfg)
    assert [(m.layer, str(m.image)) for m in loaded.maps] == [("teyvat", "mapas/teyvat_z14.png")]
    assert loaded.maps[0].tile_origin_y == 20
    assert loaded.detect.auto_mark is False, "outras seções não podem sumir"
    assert loaded.capture.fps == 5
    assert not add_to_config(cfg, "teyvat", Path("mapas/teyvat_z14.png"), meta)  # nada muda
    assert add_to_config(cfg, "chasm", Path("mapas/chasm_z14.png"), meta)
    assert [m.layer for m in load_config(cfg).maps] == ["teyvat", "chasm"]


def test_add_to_config_creates_file(tmp_path: Path) -> None:
    meta = tmp_path / "m.json"
    meta.write_text(json.dumps({"tile_zoom": 14, "tile_origin_x": 1, "tile_origin_y": 2}))
    cfg = tmp_path / "novo.toml"
    assert add_to_config(cfg, "teyvat", Path("mapas/t.png"), meta)
    assert load_config(cfg).maps[0].tile_zoom == 14
