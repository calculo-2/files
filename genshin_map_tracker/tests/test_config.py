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
