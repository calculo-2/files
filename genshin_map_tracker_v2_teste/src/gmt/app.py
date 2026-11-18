"""Loop principal: tela -> posição -> mapa no navegador -> coleta/interação -> marcação.

A "janela de status" é o próprio console: cada comando enviado ao mapa aparece
com horário, além de uma linha de posição a cada poucos segundos. Tudo também
vai para out/acoes.log.
"""

from __future__ import annotations

import inspect
import logging
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

from gmt.data.catalog import CATALOG, OCULUS_KINDS, PUZZLE_KINDS, label_for_kind, radius_factor_for
from gmt.data.markers import Marker, MarkerStore
from gmt.detect.events import CollectDetector, CollectEvent
from gmt.detect.resolver import (
    ResolverConfig,
    decide,
    kinds_for_event,
    priority_tiers_for_event,
    resolve,
)
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
    hide_frames: int = 3  # quadros seguidos para considerar o minimapa oculto/de volta
    uncertain_log: Path | None = None  # registro dos casos marcados sem confirmação
    max_lost_images: int = 60
    lost_snapshot_every: float = 10.0  # s entre imagens enquanto a posição segue perdida
    puzzle_fallback: bool = True  # resolve Baús de Enigma quando não há Baú comum no raio
    only_visible_on_site: bool = False  # filtra só categorias visíveis na barra lateral
    # Categorias novas ainda não conferidas com prints reais: por padrão só destaca no
    # mapa e registra em incertos.log, sem marcar sozinho. True: trata como baú/oculus.
    auto_mark_experimental: bool = False


# Tipos validados em sessões reais (baús e oculi): podem ser marcados sozinhos.
VALIDATED_KINDS: frozenset[str] = frozenset({"chest", "oculus", *OCULUS_KINDS})


EVENT_NAMES: dict[str, str] = {k: s.label_pt for k, s in CATALOG.items()}


@dataclass
class _PendingMark:
    """Coleta com dúvida esperando confirmação no site."""

    deadline: float  # time.monotonic()
    candidates: list[Any]  # SiteMarker, do mais provável ao menos
    kind: str
    expect_kinds: tuple[str, ...]
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
        self._lost_snap_t = -1e9
        self._pending: list[_PendingMark] = []
        self._hidden = False
        self._arrow_last = True
        self._arrow_streak = 0
        self._panel_t = -1e9
        self.last_fix: Fix | None = None
        self.last_site: tuple[float, float] | None = None
        self._was_lost = False
        self._last_puzzle_mark: tuple[float, float, float] | None = None  # (t, x, y)
        self.marked_count = 0

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
            self._lost_snap_t = t
        elif fix.method == "lost" and t - self._lost_snap_t >= self.options.lost_snapshot_every:
            self._save_lost(frame, mm)
            self._lost_snap_t = t
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
        arrow = find_player_arrow(frame, circle, search=0.2)
        ok = arrow is not None and math.hypot(arrow.x - circle.cx, arrow.y - circle.cy) <= (
            0.12 * circle.r
        )
        if ok != self._arrow_last:
            if arrow is None:
                raw = find_player_arrow(frame, circle, search=0.2, max_area=1.0)
                where = "seta não achada" if raw is None else f"mancha ciano área {raw.area}"
            else:
                off = math.hypot(arrow.x - circle.cx, arrow.y - circle.cy)
                where = f"seta área {arrow.area} a {off:.1f} px do centro"
            log.debug("t=%.2f minimapa %s (%s)", t, "visível" if ok else "oculto", where)
        self._arrow_streak = self._arrow_streak + 1 if ok == self._arrow_last else 1
        self._arrow_last = ok
        if self._arrow_streak < self.options.hide_frames:
            return ok
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
        setter = getattr(self.browser, "set_status", None)
        if setter is None or t - self._panel_t < 1.0:
            return
        self._panel_t = t
        if fix.ok:
            setter(f"Posição: {fix.layer} · confiança {fix.confidence:.2f}", True)
        else:
            setter("Posição perdida: procurando...", False)

    def _panel_event(self, text: str) -> None:
        setter = getattr(self.browser, "set_last_event", None)
        if setter is not None:
            setter(text)

    def _save_lost(self, frame: Image, mm: object) -> None:
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

    def _search_radius(self, fix: Fix, minimap_r: float, factor: float = 1.0) -> float:
        if self.options.radius > 0:
            return self.options.radius * factor
        assert fix.layer is not None and fix.x is not None and fix.y is not None
        r_px = minimap_r * (fix.scale or 1.0) * self.options.radius_fraction * factor
        a = self.converter.to_site(fix.layer, fix.x, fix.y)
        b = self.converter.to_site(fix.layer, fix.x + r_px, fix.y)
        if a is None or b is None:
            return 0.0
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _puzzle_recently_marked_here(self, event: CollectEvent, fix: Fix, base_r: float) -> bool:
        """Evita marcar um 2º enigma logo depois de 'Desafio Concluído' marcar o desafio."""
        if self._last_puzzle_mark is None or not fix.ok or fix.x is None or fix.y is None:
            return False
        pt, px, py = self._last_puzzle_mark
        return 0 <= (event.t - pt) <= 15.0 and math.hypot(fix.x - px, fix.y - py) <= max(
            base_r * 2.5, 40.0
        )

    def _record_puzzle_mark_if_needed(
        self, tier_kinds: tuple[str, ...], t: float, fix: Fix
    ) -> None:
        if (
            fix.ok
            and fix.x is not None
            and fix.y is not None
            and any(CATALOG.get(k) and CATALOG[k].group == "puzzle" for k in tier_kinds)
        ):
            self._last_puzzle_mark = (t, fix.x, fix.y)

    def _handle_event(
        self, event: CollectEvent, fix: Fix, site: tuple[float, float] | None, minimap_r: float
    ) -> None:
        name = label_for_kind(event.kind, event.subtype)
        ctx_note = f" [{label_for_kind(event.context)}]" if event.context else ""
        certainty = "" if event.certain else " (indício fraco)"
        quiet_probe = not event.certain and event.kind in ("statue", "viewpoint")

        if not quiet_probe:
            self.console.info(
                f"coleta detectada: {name}{ctx_note}{certainty} <- {' | '.join(event.evidence)}"
            )

        if self._handle_with_site_markers(event, fix, minimap_r, name, quiet_probe=quiet_probe):
            return
        if self.store is None or site is None or fix.layer is None:
            if not quiet_probe:
                self.console.action(f"{name}: posição desconhecida; marque no site manualmente")
            return

        lat, lng = site
        factor = radius_factor_for(event.kind, event.context)
        radius = self._search_radius(fix, minimap_r, factor=factor)
        allow_puzzle_fb = self.options.puzzle_fallback and not self._puzzle_recently_marked_here(
            event, fix, minimap_r * (fix.scale or 1.0) * self.options.radius_fraction
        )
        conf = fix.confidence if event.certain else 0.0
        res = resolve(
            self.store,
            ResolverConfig(radius=radius, puzzle_fallback=allow_puzzle_fb),
            event.kind,
            fix.layer,
            lng,
            lat,
            conf,
            subtype=event.subtype,
            context=event.context,
        )
        if res.decision == "none":
            if not quiet_probe:
                self.console.action(f"{name}: nenhum marcador pendente por perto ({res.reason})")
            return
        if quiet_probe:
            self.console.info(
                f"interação detectada: {name} pendente por perto <- {' | '.join(event.evidence)}"
            )
        if res.decision == "mark" and self._experimental(event):
            self._suggest_only(event, name, [(c.id, d) for c, d in res.candidates], res.reason)
            for c, _d in res.candidates:
                if self.browser is not None:
                    self.browser.highlight(c.y, c.x, f"{name}? (em teste)")
            return
        if res.decision == "mark" and self.options.auto_mark:
            m = res.marker
            assert m is not None
            self.store.mark_found(m.id, how="auto")
            done = self.browser.mark(m.id) if self.browser else False
            self.marked_count += 1
            self._record_puzzle_mark_if_needed((m.kind,), event.t, fix)
            where = "no site e no progresso local" if done else "no progresso local"
            self.console.action(f"{name} {m.id} marcado {where} ({res.reason})")
            self._panel_event(f"Marcado ({self.marked_count}): {name}")
            if self.browser is not None and not done:
                self.browser.highlight(m.y, m.x, f"{name} coletado: clique para marcar")
            return
        self.console.action(f"{name}: confirme no site qual foi ({res.reason})")
        self._panel_event(f"Confirmar no mapa: {name}")
        if self.browser is not None:
            for i, (m, _d) in enumerate(res.candidates, 1):
                self.browser.highlight(m.y, m.x, f"{name}? ({i})")

    def _experimental(self, event: CollectEvent) -> bool:
        return event.kind not in VALIDATED_KINDS and not self.options.auto_mark_experimental

    def _suggest_only(
        self, event: CollectEvent, name: str, cands: list[tuple[str, float]], reason: str
    ) -> None:
        """Categoria em teste: avisa e registra, mas não marca (nem depois do tempo)."""
        txt = ", ".join(f"{i} a {d:.0f}px" for i, d in cands)
        self.console.action(
            f"{name}: categoria em teste, NÃO marco sozinho; confira no mapa ({txt})"
        )
        self._panel_event(f"Em teste (confira): {name}")
        path = self.options.uncertain_log
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                f"[{time.strftime('%H:%M:%S')}] {name}: sugestão (categoria em teste, não marcado)"
                f" | motivo: {reason} | evidência: {' | '.join(event.evidence)}"
                f" | candidatos: {txt}\n"
            )

    def _call_nearby(
        self, nearby: Any, gx: float, gy: float, zoom: int, radius: float, types: list[str]
    ) -> list[Any] | None:
        sig = inspect.signature(nearby)
        res: list[Any] | None
        if "only_visible" in sig.parameters:
            res = nearby(
                gx, gy, zoom, radius, types, only_visible=self.options.only_visible_on_site
            )
        else:
            res = nearby(gx, gy, zoom, radius, types)
        return res

    def _handle_with_site_markers(
        self,
        event: CollectEvent,
        fix: Fix,
        minimap_r: float,
        name: str,
        *,
        quiet_probe: bool = False,
    ) -> bool:
        """Usa os marcadores do próprio site (appsample) com resolução em cascata."""
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

        base_r = (
            self.options.radius or minimap_r * (fix.scale or 1.0) * self.options.radius_fraction
        )
        factor = radius_factor_for(event.kind, event.context)
        radius = base_r * factor
        allow_puzzle_fb = self.options.puzzle_fallback and not self._puzzle_recently_marked_here(
            event, fix, base_r
        )
        tiers = priority_tiers_for_event(
            event.kind,
            subtype=event.subtype,
            context=event.context,
            puzzle_fallback=allow_puzzle_fb,
        )

        chosen_tier: tuple[str, ...] = ()
        pending: list[Any] = []
        any_table_ok = False
        all_queried_types: list[str] = []

        for tier in tiers:
            types = list(dict.fromkeys(t for k in tier for t in self._site_types.get(k, ())))
            if not types:
                continue
            for tp in types:
                if tp not in all_queried_types:
                    all_queried_types.append(tp)
            tier_r = (
                radius * max((radius_factor_for(k) for k in tier), default=1.0) / max(factor, 1e-6)
            )
            found = self._call_nearby(nearby, gx, gy, zoom, tier_r, types)
            if found is None:
                return False  # tabela do site indisponível: usa o banco local
            any_table_ok = True
            cand_pending = [m for m in found if not m.found]
            if cand_pending:
                chosen_tier = tier
                pending = cand_pending
                radius = tier_r
                break

        if not any_table_ok:
            return False

        conf = fix.confidence if event.certain else 0.0
        decision, reason = decide(
            [m.distance for m in pending], ResolverConfig(radius=radius), conf
        )
        if decision == "suggest" and not event.certain:
            reason = (
                "indício fraco: recompensa de baú sem o aviso de abrir"
                if event.kind == "chest"
                else "interação vista; confirme no mapa"
            )
        if decision == "none":
            if quiet_probe:
                return True
            if event.kind == "chest" and not allow_puzzle_fb:
                self.console.action(
                    f"{name}: baú do desafio/enigma recém-marcado; ignorando duplicata"
                )
                return True
            far = self._call_nearby(nearby, gx, gy, zoom, radius * 6, all_queried_types) or []
            near_txt = "nenhum até 6x o raio"
            if far:
                m0 = far[0]
                state = "já marcado" if m0.found else "pendente"
                near_txt = (
                    f"mais próximo {m0.id} a {m0.distance:.0f} px ({state}; raio {radius:.0f})"
                )
            self.console.action(f"{name}: nenhum marcador pendente no raio do site ({near_txt})")
            return True

        if quiet_probe:
            self.console.info(
                f"interação detectada: {name} pendente no raio <- {' | '.join(event.evidence)}"
            )

        expect_kinds = chosen_tier or kinds_for_event(event.kind)
        if self._experimental(event):
            if quiet_probe:  # só passou perto (ex.: aviso de estátua): nem avisa
                return True
            self._suggest_only(event, name, [(m.id, m.distance) for m in pending[:3]], reason)
            unproject = getattr(self.browser, "unproject", None)
            for m in pending[:3]:
                ll = unproject(m.x, m.y, zoom) if unproject is not None else None
                if ll is not None:
                    self.browser.highlight(ll[0], ll[1], f"{name}? (em teste)", seconds=30.0)
            return True
        if decision == "mark" and event.kind == "chest" and set(chosen_tier) <= set(PUZZLE_KINDS):
            # Baú achado só numa categoria de Baú de Enigma: não validado em sessão real.
            # Vai para confirmação (marca sozinho após o tempo e registra como incerto).
            decision, reason = "suggest", "baú encontrado só como Baú de Enigma no site"
        if decision == "mark" and self.options.auto_mark:
            res_code = self._mark_site(
                pending[0], event.kind, expect_kinds, fix.layer, name, reason, "auto"
            )
            if res_code in ("marked", "already"):
                self._record_puzzle_mark_if_needed(expect_kinds, event.t, fix)
            return True

        self.console.action(
            f"{name}: confirme no site qual foi ({reason}); "
            f"sem resposta em {self.options.confirm_timeout:.0f} s marco o mais provável"
        )
        self._panel_event(f"Confirmar no mapa: {name}")
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
                expect_kinds,
                fix.layer,
                name,
                reason,
            )
        )
        return True

    def _mark_site(
        self,
        target: Any,
        kind: str,
        expect_kinds: tuple[str, ...],
        layer: str,
        name: str,
        reason: str,
        how: str,
    ) -> str:
        from gmt.web.appsample import KIND_NAMES

        expect = tuple(dict.fromkeys(n for k in expect_kinds for n in KIND_NAMES.get(k, ())))
        try:
            result: str = self.browser.mark_found_ui(target.id, expect=expect)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            log.exception("Erro ao marcar %s no site", target.id)
            result = "failed"
        msg = {
            "marked": "marcado no site",
            "already": "já estava marcado",
            "need_login": "o site pediu login (entre na sua conta no Chrome do gmt)",
            "wrong_marker": "o marcador aberto não era desse tipo; marque no site",
            "overlap": "ícone coberto por outro mesmo no zoom máximo; marque no site",
        }.get(result, f"não deu para marcar ({result}); marque no site")
        self.console.action(f"{name} {target.id}: {msg} ({reason})")
        if result == "marked":
            self.marked_count += 1
            self._panel_event(f"Marcado ({self.marked_count}): {name}")
        if self.store is not None and result in ("marked", "already"):
            store_kind = expect_kinds[0] if expect_kinds else kind
            self.store.upsert([Marker(target.id, store_kind, layer, target.x, target.y)])
            self.store.mark_found(target.id, how=how)
        return result

    def _process_pending(self) -> None:
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
            result = self._mark_site(
                target, p.kind, p.expect_kinds, p.layer, p.name, "sem confirmação", "incerto"
            )
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
        for frame, _rect in frames:  # type: ignore[attr-defined]
            if frame is None:
                if not self.paused.is_set():
                    self._process_pending()
                continue
            self.step(frame, time.perf_counter())
