"""Configuração do app, carregada de um arquivo TOML opcional."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

Backend = Literal["auto", "dxcam", "mss"]
_BACKENDS: tuple[str, ...] = ("auto", "dxcam", "mss")


class ConfigError(ValueError):
    """Valor inválido no arquivo de configuração."""


@dataclass(frozen=True)
class CaptureConfig:
    fps: float = 5.0
    backend: Backend = "auto"
    output_dir: Path = Path("out")

    def __post_init__(self) -> None:
        if not 1 <= self.fps <= 30:
            raise ConfigError(f"capture.fps deve estar entre 1 e 30 (recebido {self.fps})")
        if self.backend not in _BACKENDS:
            raise ConfigError(f"capture.backend deve ser um de {_BACKENDS}")


@dataclass(frozen=True)
class MinimapConfig:
    """Círculo do minimapa em pixels na resolução de referência 1920x1080."""

    center_x: float = 168.0
    center_y: float = 125.0
    radius: float = 100.0

    def __post_init__(self) -> None:
        if self.radius <= 0:
            raise ConfigError("minimap.radius deve ser positivo")


@dataclass(frozen=True)
class Config:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    minimap: MinimapConfig = field(default_factory=MinimapConfig)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] deve ser uma seção")
    return value


def load_config(path: Path | None = None) -> Config:
    """Lê o TOML em `path` (ou ./config.toml). Sem arquivo, usa os padrões."""
    path = path or Path("config.toml")
    if not path.exists():
        log.info("Sem %s; usando configuração padrão.", path)
        return Config()

    with path.open("rb") as fh:
        data = tomllib.load(fh)

    cap = _section(data, "capture")
    mm = _section(data, "minimap")
    try:
        capture = CaptureConfig(
            fps=float(cap.get("fps", CaptureConfig.fps)),
            backend=cap.get("backend", CaptureConfig.backend),
            output_dir=Path(cap.get("output_dir", str(CaptureConfig.output_dir))),
        )
        minimap = MinimapConfig(
            center_x=float(mm.get("center_x", MinimapConfig.center_x)),
            center_y=float(mm.get("center_y", MinimapConfig.center_y)),
            radius=float(mm.get("radius", MinimapConfig.radius)),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"Valor inválido em {path}: {exc}") from exc

    log.info("Configuração carregada de %s", path)
    return Config(capture=capture, minimap=minimap)
