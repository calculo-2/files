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

    center_x: float = 169.0
    center_y: float = 125.0
    radius: float = 100.0

    def __post_init__(self) -> None:
        if self.radius <= 0:
            raise ConfigError("minimap.radius deve ser positivo")


@dataclass(frozen=True)
class SiteConfig:
    """Mapa interativo no navegador."""

    url: str = "https://genshin-impact-map.appsample.com/pt/"
    profile: Path = Path(".chrome-gmt")  # perfil do Chrome só do gmt (faça login nele uma vez)
    follow: bool = True
    min_interval: float = 1.0
    min_pan_px: float = 40.0
    zoom: int | None = None
    mark_js: str | None = None  # comando JS do site para marcar coletado; {id} = id do marcador
    compact: bool = True  # janela de aplicativo (sem abas/endereço), boa para o 2º monitor
    window: tuple[int, int, int, int] | None = None  # x, y, largura, altura da janela do mapa
    controls: bool = True  # painel flutuante: Seguir-me/Soltar, zoom, status


@dataclass(frozen=True)
class MapLayerConfig:
    """Uma camada do mapa base e como converter seus pixels para o site.

    Duas formas (escolha uma):
    - `calibration`: arquivo JSON de calibração por pontos (gmt.geo.calibration);
    - `tile_zoom` + `tile_origin_*`: mapa montado com os tiles do próprio site no zoom
      `tile_zoom`, cujo pixel (0, 0) corresponde ao pixel global (origin_x, origin_y)
      do Leaflet. A conversão então é exata, feita pelo próprio site.
    """

    layer: str
    image: Path
    calibration: Path | None = None
    tile_zoom: int | None = None
    tile_origin_x: float = 0.0
    tile_origin_y: float = 0.0


@dataclass(frozen=True)
class DetectConfig:
    enabled: bool = True
    radius: float = 0.0  # raio de busca do baú, em unidades do site; 0 = automático
    auto_mark: bool = True  # False: só sugere, nunca marca sozinho


@dataclass(frozen=True)
class Config:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    minimap: MinimapConfig = field(default_factory=MinimapConfig)
    site: SiteConfig = field(default_factory=SiteConfig)
    maps: tuple[MapLayerConfig, ...] = ()
    detect: DetectConfig = field(default_factory=DetectConfig)
    database: Path = Path("out/progresso.db")
    pause_hotkey: str = "ctrl+alt+p"


def _window(value: Any) -> tuple[int, int, int, int] | None:
    """[x, y, largura, altura] -> tupla; None se ausente."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise ConfigError("site.window deve ser [x, y, largura, altura]")
    x, y, w, h = (int(v) for v in value)
    return x, y, w, h


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
        site_d = _section(data, "site")
        site = SiteConfig(
            url=str(site_d.get("url", SiteConfig.url)),
            profile=Path(site_d.get("profile", str(SiteConfig.profile))),
            follow=bool(site_d.get("follow", True)),
            min_interval=float(site_d.get("min_interval", SiteConfig.min_interval)),
            min_pan_px=float(site_d.get("min_pan_px", SiteConfig.min_pan_px)),
            zoom=int(site_d["zoom"]) if "zoom" in site_d else None,
            mark_js=site_d.get("mark_js"),
            compact=bool(site_d.get("compact", True)),
            window=_window(site_d.get("window")),
            controls=bool(site_d.get("controls", True)),
        )
        raw_maps = data.get("maps", [])
        if not isinstance(raw_maps, list):
            raise ConfigError("[[maps]] deve ser uma lista de camadas")
        maps = tuple(
            MapLayerConfig(
                layer=str(m["layer"]),
                image=Path(m["image"]),
                calibration=Path(m["calibration"]) if m.get("calibration") else None,
                tile_zoom=int(m["tile_zoom"]) if "tile_zoom" in m else None,
                tile_origin_x=float(m.get("tile_origin_x", 0.0)),
                tile_origin_y=float(m.get("tile_origin_y", 0.0)),
            )
            for m in raw_maps
        )
        det = _section(data, "detect")
        detect = DetectConfig(
            enabled=bool(det.get("enabled", True)),
            radius=float(det.get("radius", 0.0)),
            auto_mark=bool(det.get("auto_mark", True)),
        )
        general = _section(data, "general")
        database = Path(general.get("database", "out/progresso.db"))
        hotkey = str(general.get("pause_hotkey", "ctrl+alt+p"))
    except ConfigError:
        raise
    except KeyError as exc:
        raise ConfigError(f"Campo obrigatório ausente em {path}: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Valor inválido em {path}: {exc}") from exc

    log.info("Configuração carregada de %s", path)
    return Config(capture, minimap, site, maps, detect, database, hotkey)
