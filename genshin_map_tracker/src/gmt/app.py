"""Loop principal: tela -> posição -> mapa no navegador -> coleta -> marcação.

A "janela de status" é o próprio console: cada comando enviado ao mapa aparece
com horário, além de uma linha de posição a cada poucos segundos. Tudo também
vai para out/acoes.log.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from gmt.data.markers import MarkerStore
from gmt.detect.events import CollectDetector, CollectEvent
from gmt.detect.resolver import ResolverConfig, resolve
from gmt.geo.calibration import Calibration
from gmt.localization.localizer import Fix, Localizer
from gmt.vision.minimap import Image, crop_minimap
from gmt.vision.regions import minimap_circle

log = logging.getLogger(__name__)


# ------------------------------------------------------------------- console


class StatusConsole:
    """Mostra no console o que o app está fazendo (e grava em arquivo)."""

    def __init__(
        self, stream: TextIO | None = None, log_file: Path | None = None, every: float = 2.0
    ) -> None:
        self.stream = stream or sys.stdout
        self.log_file = log_file
        self.every = every
        self._last_status = -1e9
        self.lines: list[str] = []
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)

    def _emit(self, line: str) -> None:
        self.lines.append(line)
        print(line, file=self.stream, flush=True)
        if self.log_file:
            with self.log_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def action(self, text: str) -> None:
        self._emit(f"[{time.strftime('%H:%M:%S')}] -> {text}")

    def info(self, text: str) -> None:
        self._emit(f"[{time.strftime('%H:%M:%S')}]    {text}")

    def status(
        self, fix: Fix, site: tuple[float, float] | None, t: float, force: bool = False
    ) -> None:
        if not force and t - self._last_status < self.every:
            return
        self._last_status = t
        if not fix.ok:
            self.info("posição: PERDIDA")
            return
        where = f" | site ({site[0]:.2f}, {site[1]:.2f})" if site else ""
        self.info(
            f"posição: {fix.layer} ({fix.x:.0f}, {fix.y:.0f}) confiança {fix.confidence:.2f}"
            f" [{fix.method}]{where}"
        )


# ---------------------------------------------------------------- conversão


class PositionConverter(Protocol):
    def to_site(self, layer: str, x: float, y: float) -> tuple[float, float] | None:
        """Pixel do mapa base -> (lat, lng) do site, ou None se não souber converter."""
        ...


class CalibrationConverter:
    """Usa calibrações por pontos; o site guarda (x, y) = (lng, lat)."""

    def __init__(self, calibrations: dict[str, Calibration]) -> None:
        self.calibrations = calibrations

    def to_site(self, layer: str, x: float, y: float) -> tuple[float, float] | None:
        cal = self.calibrations.get(layer)
        if cal is None or cal.matrix is None:
            return None
        lng, lat = cal.to_site(x, y)
        return lat, lng


class SiteUnprojector(Protocol):
    def unproject(self, x: float, y: float, zoom: int) -> tuple[float, float] | None: ...


@dataclass(frozen=True)
class TileLayer:
    zoom: int
    origin_x: float
    origin_y: float


class TileConverter:
    """Mapa base montado com os tiles do site: conversão exata pelo próprio Leaflet."""

    def __init__(self, browser: SiteUnprojector, layers: dict[str, TileLayer]) -> None:
        self.browser = browser
        self.layers = layers

    def to_site(self, layer: str, x: float, y: float) -> tuple[float, float] | None:
        tl = self.layers.get(layer)
        if tl is None:
            return None
        return self.browser.unproject(x + tl.origin_x, y + tl.origin_y, tl.zoom)


class ChainConverter:
    def __init__(self, *converters: PositionConverter) -> None:
        self.converters = converters

    def to_site(self, layer: str, x: float, y: float) -> tuple[float, float] | None:
        for c in self.converters:
            out = c.to_site(layer, x, y)
            if out is not None:
                return out
        return None


# ------------------------------------------------------------------ app


class MapControl(Protocol):
    def follow(self, lat: float, lng: float, force: bool = False) -> bool: ...
    def show_player(self, lat: float, lng: float, confident: bool = True) -> None: ...
    def highlight(self, lat: float, lng: float, label: str = "", seconds: float = 20.0) -> None: ...
    def mark(self, marker_id: str) -> bool: ...


class EventSource(Protocol):
    def update(self, frame: Image, t: float) -> list[CollectEvent]: ...


@dataclass
class AppOptions:
    follow: bool = True
    auto_mark: bool = True
    radius: float = 0.0  # unidades do site; 0 = automático pelo tamanho do minimapa
    radius_fraction: float = 0.12  # raio automático = fração do raio do minimapa no mapa


EVENT_NAMES = {"chest": "baú"}


class App:
    def __init__(
        self,
        localizer: Localizer,
        converter: PositionConverter,
        console: StatusConsole,
        minimap_ref: object,
        browser: MapControl | None = None,
        store: MarkerStore | None = None,
        detector: EventSource | CollectDetector | None = None,
        options: AppOptions | None = None,
    ) -> None:
        self.localizer = localizer
        self.converter = converter
        self.console = console
        self.minimap_ref = minimap_ref
        self.browser = browser
        self.store = store
        self.detector = detector
        self.options = options or AppOptions()
        self.paused = threading.Event()
        self.last_fix: Fix | None = None
        self.last_site: tuple[float, float] | None = None
        self._was_lost = False

    def toggle_pause(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
            self.localizer.reset()
            self.console.action("RETOMADO")
        else:
            self.paused.set()
            self.console.action("PAUSADO (atalho de novo para retomar)")

    # -------------------------------------------------------------- quadro

    def step(self, frame: Image, t: float) -> Fix | None:
        if self.paused.is_set():
            return None
        h, w = frame.shape[:2]
        mm = crop_minimap(frame, minimap_circle(w, h, self.minimap_ref))  # type: ignore[arg-type]
        fix = self.localizer.update(mm, t)
        site = None
        if fix.ok and fix.layer is not None and fix.x is not None and fix.y is not None:
            site = self.converter.to_site(fix.layer, fix.x, fix.y)
        self.last_fix, self.last_site = fix, site

        if fix.ok and self._was_lost:
            self.console.action(f"posição encontrada em {fix.layer}")
        if not fix.ok and not self._was_lost and fix.method == "lost":
            self.console.action("posição PERDIDA; procurando...")
        self._was_lost = not fix.ok

        if site is not None and self.browser is not None:
            lat, lng = site
            self.browser.show_player(lat, lng, confident=fix.confidence >= 0.5)
            if self.options.follow and fix.method in ("global", "local"):
                self.browser.follow(lat, lng)

        if self.detector is not None:
            for event in self.detector.update(frame, t):
                self._handle_event(event, fix, site, mm.circle.r)

        self.console.status(fix, site, t)
        return fix

    def _search_radius(self, fix: Fix, minimap_r: float) -> float:
        if self.options.radius > 0:
            return self.options.radius
        assert fix.layer is not None and fix.x is not None and fix.y is not None
        r_px = minimap_r * (fix.scale or 1.0) * self.options.radius_fraction
        a = self.converter.to_site(fix.layer, fix.x, fix.y)
        b = self.converter.to_site(fix.layer, fix.x + r_px, fix.y)
        if a is None or b is None:
            return 0.0
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _handle_event(
        self, event: CollectEvent, fix: Fix, site: tuple[float, float] | None, minimap_r: float
    ) -> None:
        name = EVENT_NAMES.get(event.kind, event.kind)
        certainty = "" if event.certain else " (indício fraco)"
        self.console.info(f"coleta detectada: {name}{certainty} <- {' | '.join(event.evidence)}")
        if self.store is None or site is None or fix.layer is None:
            self.console.action(f"{name}: posição desconhecida; marque no site manualmente")
            return
        lat, lng = site
        radius = self._search_radius(fix, minimap_r)
        conf = fix.confidence if event.certain else 0.0
        res = resolve(
            self.store, ResolverConfig(radius=radius), event.kind, fix.layer, lng, lat, conf
        )
        if res.decision == "none":
            self.console.action(f"{name}: nenhum marcador pendente por perto ({res.reason})")
            return
        if res.decision == "mark" and self.options.auto_mark:
            m = res.marker
            assert m is not None
            self.store.mark_found(m.id, how="auto")
            done = self.browser.mark(m.id) if self.browser else False
            where = "no site e no progresso local" if done else "no progresso local"
            self.console.action(f"{name} {m.id} marcado {where} ({res.reason})")
            if self.browser is not None and not done:
                self.browser.highlight(m.y, m.x, f"{name} coletado: clique para marcar")
            return
        self.console.action(f"{name}: confirme no site qual foi ({res.reason})")
        if self.browser is not None:
            for i, (m, _d) in enumerate(res.candidates, 1):
                self.browser.highlight(m.y, m.x, f"{name}? ({i})")

    # ---------------------------------------------------------------- loop

    def run(self, frames: object) -> None:
        """Consome um iterador de (quadro, retângulo) como o de gmt.capture.grabber.frames."""
        for frame, _rect in frames:  # type: ignore[attr-defined]
            self.step(frame, time.perf_counter())
