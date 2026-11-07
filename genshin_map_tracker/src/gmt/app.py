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
from typing import Any, Protocol, TextIO

from gmt.data.markers import Marker, MarkerStore
from gmt.detect.events import CollectDetector, CollectEvent
from gmt.detect.resolver import ResolverConfig, decide, kinds_for_event, resolve
from gmt.geo.calibration import Calibration
from gmt.localization.localizer import Fix, Localizer
from gmt.vision.minimap import Image, crop_minimap, find_player_arrow
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
        g = self.global_px(layer, x, y)
        return None if g is None else self.browser.unproject(*g)

    def global_px(self, layer: str, x: float, y: float) -> tuple[float, float, int] | None:
        """Pixel do mapa base -> pixel global do Leaflet (x, y, zoom)."""
        tl = self.layers.get(layer)
        if tl is None:
            return None
        return x + tl.origin_x, y + tl.origin_y, tl.zoom


class ChainConverter:
    def __init__(self, *converters: PositionConverter) -> None:
        self.converters = converters

    def to_site(self, layer: str, x: float, y: float) -> tuple[float, float] | None:
        for c in self.converters:
            out = c.to_site(layer, x, y)
            if out is not None:
                return out
        return None

    def global_px(self, layer: str, x: float, y: float) -> tuple[float, float, int] | None:
        for c in self.converters:
            fn = getattr(c, "global_px", None)
            out = fn(layer, x, y) if fn is not None else None
            if out is not None:
                return out  # type: ignore[no-any-return]
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
    lost_dir: Path | None = None  # salva imagens dos momentos em que a posição se perde
    confirm_timeout: float = 30.0  # s esperando você confirmar um caso incerto no site
    require_arrow: bool = True  # só localiza com a seta do jogador no centro do minimapa
    uncertain_log: Path | None = None  # registro dos casos marcados sem confirmação
    max_lost_images: int = 40


EVENT_NAMES = {"chest": "baú"}


@dataclass
class _PendingMark:
    """Coleta com dúvida esperando confirmação no site."""

    deadline: float  # time.monotonic()
    candidates: list[Any]  # SiteMarker, do mais provável ao menos
    kind: str
    layer: str
    name: str
    reason: str


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
        self._site_types: dict[str, tuple[str, ...]] | None = None
        self._lost_saved = 0
        self._pending: list[_PendingMark] = []
        self._hidden = False
        self._panel_t = -1e9
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
        circle = minimap_circle(w, h, self.minimap_ref)  # type: ignore[arg-type]
        if self.options.require_arrow and not self._minimap_visible(frame, circle, t):
            return None
        mm = crop_minimap(frame, circle)
        fix = self.localizer.update(mm, t)
        site = None
        if fix.ok and fix.layer is not None and fix.x is not None and fix.y is not None:
            site = self.converter.to_site(fix.layer, fix.x, fix.y)
        self.last_fix, self.last_site = fix, site

        if fix.ok and self._was_lost:
            self.console.action(f"posição encontrada em {fix.layer}")
        if not fix.ok and not self._was_lost and fix.method == "lost":
            self.console.action("posição PERDIDA; procurando...")
            self._save_lost(frame, mm)
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
        self._panel_status(fix, t)
        self._process_pending()
        return fix

    def _minimap_visible(self, frame: Image, circle: Any, t: float) -> bool:
        """A seta do jogador fica sempre no centro do minimapa. Sem ela ali, o mapa grande
        ou um menu está aberto, e o canto da tela mostra outra coisa: não localiza."""
        arrow = find_player_arrow(frame, circle, search=0.2)
        ok = arrow is not None and math.hypot(arrow.x - circle.cx, arrow.y - circle.cy) <= (
            0.12 * circle.r
        )
        if not ok and not self._hidden:
            self._hidden = True
            self.console.action("minimapa oculto (mapa ou menu aberto): localização pausada")
            setter = getattr(self.browser, "set_status", None)
            if setter is not None:
                setter("Minimapa oculto: mapa ou menu aberto", False)
        elif ok and self._hidden:
            self._hidden = False
            self.console.action("minimapa de volta: retomando")
        return ok

    def _panel_status(self, fix: Fix, t: float) -> None:
        """Status no painel flutuante do mapa (no máximo 1x por segundo)."""
        setter = getattr(self.browser, "set_status", None)
        if setter is None or t - self._panel_t < 1.0:
            return
        self._panel_t = t
        if fix.ok:
            setter(f"Posição: {fix.layer} · confiança {fix.confidence:.2f}", True)
        else:
            setter("Posição perdida: procurando...", False)

    def _save_lost(self, frame: Image, mm: object) -> None:
        """Guarda o quadro e o minimapa de quando a posição se perdeu (para diagnóstico)."""
        opts = self.options
        if opts.lost_dir is None or self._lost_saved >= opts.max_lost_images:
            return
        import cv2

        self._lost_saved += 1
        opts.lost_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{time.strftime('%H%M%S')}_{self._lost_saved:02d}"
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            buf.tofile(str(opts.lost_dir / f"{stamp}_tela.jpg"))
        ok, buf = cv2.imencode(".png", mm.with_alpha())  # type: ignore[attr-defined]
        if ok:
            buf.tofile(str(opts.lost_dir / f"{stamp}_minimapa.png"))

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
        if self._handle_with_site_markers(event, fix, minimap_r, name):
            return
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

    def _handle_with_site_markers(
        self, event: CollectEvent, fix: Fix, minimap_r: float, name: str
    ) -> bool:
        """Usa os marcadores do próprio site (appsample). False se não der para usar."""
        nearby = getattr(self.browser, "nearby_site_markers", None)
        global_px = getattr(self.converter, "global_px", None)
        if nearby is None or global_px is None or not fix.ok or fix.layer is None:
            return False
        assert fix.x is not None and fix.y is not None and self.browser is not None
        g = global_px(fix.layer, fix.x, fix.y)
        if g is None:
            return False
        gx, gy, zoom = g
        if self._site_types is None:
            self._site_types = self.browser.site_categories()  # type: ignore[attr-defined]
        types = [t for k in kinds_for_event(event.kind) for t in self._site_types.get(k, ())]
        radius = (
            self.options.radius or minimap_r * (fix.scale or 1.0) * self.options.radius_fraction
        )
        found = nearby(gx, gy, zoom, radius, types)
        if found is None:
            return False  # tabela do site indisponível: usa o banco local
        pending = [m for m in found if not m.found]
        conf = fix.confidence if event.certain else 0.0
        decision, reason = decide(
            [m.distance for m in pending], ResolverConfig(radius=radius), conf
        )
        if decision == "none":
            self.console.action(f"{name}: nenhum marcador pendente por perto no site ({reason})")
            return True
        if decision == "mark" and self.options.auto_mark:
            self._mark_site(pending[0], event.kind, fix.layer, name, reason, "auto")
            return True
        self.console.action(
            f"{name}: confirme no site qual foi ({reason}); "
            f"sem resposta em {self.options.confirm_timeout:.0f} s marco o mais provável"
        )
        unproject = getattr(self.browser, "unproject", None)
        for i, m in enumerate(pending[:3], 1):
            ll = unproject(m.x, m.y, zoom) if unproject is not None else None
            if ll is not None:
                self.browser.highlight(
                    ll[0], ll[1], f"{name}? ({i})", seconds=self.options.confirm_timeout
                )
        self._pending.append(
            _PendingMark(
                time.monotonic() + self.options.confirm_timeout,
                pending[:3],
                event.kind,
                fix.layer,
                name,
                reason,
            )  # fmt: skip
        )
        return True

    def _mark_site(
        self, target: Any, kind: str, layer: str, name: str, reason: str, how: str
    ) -> str:
        from gmt.web.appsample import KIND_NAMES

        kinds = kinds_for_event(kind)
        expect = tuple(n for k in kinds for n in KIND_NAMES.get(k, ()))
        result: str = self.browser.mark_found_ui(target.id, expect=expect)  # type: ignore[union-attr]
        msg = {
            "marked": "marcado no site",
            "already": "já estava marcado",
            "need_login": "o site pediu login (entre na sua conta no Chrome do gmt)",
            "wrong_marker": "o marcador aberto não era desse tipo; marque no site",
            "overlap": "ícone coberto por outro mesmo no zoom máximo; marque no site",
        }.get(result, f"não deu para marcar ({result}); marque no site")
        self.console.action(f"{name} {target.id}: {msg} ({reason})")
        if self.store is not None and result in ("marked", "already"):
            self.store.upsert([Marker(target.id, kind, layer, target.x, target.y)])
            self.store.mark_found(target.id, how=how)
        return result

    def _process_pending(self) -> None:
        """Casos incertos: se a pessoa não marcou no site a tempo, marca o mais provável."""
        if not self._pending:
            return
        now = time.monotonic()
        still: list[_PendingMark] = []
        for p in self._pending:
            if now < p.deadline:
                still.append(p)
                continue
            is_found = getattr(self.browser, "site_marker_found", None)
            chosen = next((c for c in p.candidates if is_found and is_found(c.id)), None)
            if chosen is not None:
                self.console.action(f"{p.name} {chosen.id}: confirmado por você no site")
                self._log_uncertain(p, chosen.id, "confirmado por você")
                continue
            target = p.candidates[0]
            result = self._mark_site(target, p.kind, p.layer, p.name, "sem confirmação", "incerto")
            self._log_uncertain(p, target.id, f"marcado sem confirmação ({result})")
        self._pending = still

    def _log_uncertain(self, p: _PendingMark, chosen: str, outcome: str) -> None:
        path = self.options.uncertain_log
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        cands = ", ".join(f"{c.id} a {c.distance:.0f}px" for c in p.candidates)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                f"[{time.strftime('%H:%M:%S')}] {p.name}: {outcome}: {chosen} "
                f"| motivo: {p.reason} | candidatos: {cands}\n"
            )

    # ---------------------------------------------------------------- loop

    def run(self, frames: object) -> None:
        """Consome um iterador de (quadro, retângulo) como o de gmt.capture.grabber.frames.

        Quadro None = jogo fora de foco: não lê a tela, mas resolve os casos pendentes
        (a pessoa costuma ir ao mapa no outro monitor justamente quando há dúvida).
        """
        for frame, _rect in frames:  # type: ignore[attr-defined]
            if frame is None:
                if not self.paused.is_set():
                    self._process_pending()
                continue
            self.step(frame, time.perf_counter())
