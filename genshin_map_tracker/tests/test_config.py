from __future__ import annotations

from pathlib import Path

import pytest

from gmt.config import Config, ConfigError, load_config


def test_defaults_when_missing(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nao_existe.toml") == Config()


def test_load_partial(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[capture]\nfps = 10\nbackend = "mss"\n[minimap]\nradius = 97.5\n', "utf-8")
    cfg = load_config(p)
    assert cfg.capture.fps == 10
    assert cfg.capture.backend == "mss"
    assert cfg.minimap.radius == 97.5
    assert cfg.minimap.center_x == 169.0


@pytest.mark.parametrize(
    "body",
    [
        "[capture]\nfps = 0\n",
        "[capture]\nfps = 60\n",
        '[capture]\nbackend = "obs"\n',
        "[minimap]\nradius = -1\n",
        '[capture]\nfps = "rápido"\n',
        "capture = 3\n",
    ],
)
def test_invalid_values(tmp_path: Path, body: str) -> None:
    p = tmp_path / "config.toml"
    p.write_text(body, "utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_example_config_is_valid() -> None:
    example = Path(__file__).parent.parent / "config.example.toml"
    assert load_config(example) == Config()


def test_full_config(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        """
[site]
url = "http://exemplo/mapa"
zoom = 5
mark_js = "api.found({id})"

[[maps]]
layer = "teyvat"
image = "mapas/teyvat.png"
tile_zoom = 5
tile_origin_x = 256

[[maps]]
layer = "chasm"
image = "mapas/chasm.png"
calibration = "mapas/chasm.json"

[detect]
auto_mark = false
radius = 3.5

[general]
pause_hotkey = "ctrl+shift+f9"
""",
        "utf-8",
    )
    cfg = load_config(p)
    assert cfg.site.url == "http://exemplo/mapa" and cfg.site.zoom == 5
    assert cfg.site.mark_js == "api.found({id})"
    assert [m.layer for m in cfg.maps] == ["teyvat", "chasm"]
    assert cfg.maps[0].tile_zoom == 5 and cfg.maps[0].tile_origin_x == 256
    assert cfg.maps[1].calibration == Path("mapas/chasm.json")
    assert cfg.detect.auto_mark is False and cfg.detect.radius == 3.5
    assert cfg.pause_hotkey == "ctrl+shift+f9"


def test_map_without_image_is_error(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[[maps]]\nlayer = "teyvat"\n', "utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_hotkey_parsing() -> None:
    from gmt.hotkey import HotkeyError, parse_hotkey

    assert parse_hotkey("ctrl+alt+p") == (0x0002 | 0x0001, ord("P"))
    assert parse_hotkey("Shift+F9") == (0x0004, 0x78)
    with pytest.raises(HotkeyError):
        parse_hotkey("ctrl+banana")
