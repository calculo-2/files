"""Controle do mapa interativo no navegador (Playwright).

Toda automação acontece só no navegador; o jogo nunca recebe nada.

Como acha o mapa: antes da página carregar, injeta um gancho que registra cada
mapa Leaflet criado (L.Map.addInitHook, API pública do Leaflet). Isso funciona
mesmo que o site não exponha o mapa numa variável global. Se o site não usar
Leaflet, `open()` avisa e o resto do app continua (só sem seguir no mapa).

Ritmo humano: só move o mapa quando a posição andou o bastante na tela e no
máximo uma vez a cada `min_interval` segundos.
"""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

HOOK_JS = r"""
(() => {
  const G = window.__gmt = window.__gmt || {maps: []};
  const hook = (L) => {
    try {
      if (!L || !L.Map || L.__gmtHooked) return;
      L.__gmtHooked = true;
      L.Map.addInitHook(function () { G.maps.push(this); });
    } catch (e) { G.hookError = String(e); }
  };
  if (window.L) hook(window.L);
  let current = window.L;
  try {
    Object.defineProperty(window, 'L', {
      configurable: true,
      get() { return current; },
      set(v) { current = v; hook(v); },
    });
  } catch (e) { G.defineError = String(e); }

  G.map = () => {
    const alive = G.maps.filter(m => m && m._container && document.contains(m._container));
    if (alive.length) return alive[alive.length - 1];
    // Plano B: procurar entre as variáveis globais.
    if (window.L && window.L.Map) {
      for (const k of Object.keys(window)) {
        try { if (window[k] instanceof window.L.Map) return window[k]; } catch (e) {}
      }
    }
    return null;
  };
})();
"""

FOLLOW_JS = r"""
([lat, lng, zoom, minPx, animate]) => {
  const m = window.__gmt && window.__gmt.map();
  if (!m) return {ok: false, reason: 'mapa não encontrado'};
  const target = window.L.latLng(lat, lng);
  const d = m.latLngToContainerPoint(m.getCenter()).distanceTo(m.latLngToContainerPoint(target));
  if (zoom === null && d < minPx) return {ok: true, moved: false, px: d};
  if (zoom === null) m.panTo(target, {animate: animate, duration: 0.4});
  else m.setView(target, zoom, {animate: animate});
  return {ok: true, moved: true, px: d};
}
"""

PLAYER_JS = r"""
([lat, lng, color]) => {
  const G = window.__gmt; const m = G && G.map();
  if (!m) return false;
  if (!G.player || G.player._map !== m) {
    G.player = window.L.circleMarker([lat, lng], {
      radius: 9, color: '#fff', weight: 3, fillColor: color, fillOpacity: 0.9,
      interactive: false}).addTo(m);
  }
  G.player.setLatLng([lat, lng]);
  G.player.setStyle({fillColor: color});
  return true;
}
"""

HIGHLIGHT_JS = r"""
([lat, lng, label, seconds]) => {
  const G = window.__gmt; const m = G && G.map();
  if (!m) return false;
  const c = window.L.circleMarker([lat, lng], {
    radius: 22, color: '#ffd400', weight: 4, fill: false, interactive: false}).addTo(m);
  if (label) c.bindTooltip(label, {permanent: true, direction: 'top'}).openTooltip();
  setTimeout(() => m.removeLayer(c), seconds * 1000);
  return true;
}
"""

STATE_JS = r"""
() => {
  const m = window.__gmt && window.__gmt.map();
  if (!m) return {found: false, hooked: !!(window.L && window.L.__gmtHooked),
                  leaflet: !!window.L, maps: (window.__gmt || {maps: []}).maps.length};
  const c = m.getCenter();
  return {found: true, lat: c.lat, lng: c.lng, zoom: m.getZoom(),
          minZoom: m.getMinZoom(), maxZoom: m.getMaxZoom()};
}
"""

UNPROJECT_JS = r"""
([x, y, zoom]) => {
  const m = window.__gmt && window.__gmt.map();
  if (!m) return null;
  const ll = m.unproject(window.L.point(x, y), zoom);
  return [ll.lat, ll.lng];
}
"""


class ActionSink(Protocol):
    def action(self, text: str) -> None: ...


class BrowserError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserConfig:
    url: str = "https://genshin-impact-map.appsample.com/pt/"
    profile: Path = Path(".chrome-gmt")
    min_interval: float = 1.0  # segundos entre movimentos do mapa
    min_pan_px: float = 40.0  # só move se a posição andou isso na tela
    zoom: int | None = None  # zoom fixo ao seguir; None = mantém o do usuário
    animate: bool = True
    headless: bool = False
    executable_path: str | None = None
    mark_js: str | None = None  # JS específico do site para marcar como coletado: usa {id}
    load_timeout: float = 45.0


class MapBrowser:
    def __init__(self, config: BrowserConfig, sink: ActionSink | None = None) -> None:
        self.config = config
        self.sink = sink
        self._pw: Any = None
        self._ctx: Any = None
        self._page: Any = None
        self._last_move = 0.0
        self.map_found = False

    # -------------------------------------------------------------- ciclo

    def open(self) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserError('Playwright não instalado: pip install -e ".[web]"') from exc

        cfg = self.config
        self._pw = sync_playwright().start()
        opts: dict[str, Any] = {"headless": cfg.headless, "no_viewport": True}
        if cfg.executable_path:
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(cfg.profile), executable_path=cfg.executable_path, **opts
            )
        else:
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    str(cfg.profile), channel="chrome", **opts
                )
            except Exception:  # noqa: BLE001
                log.info("Chrome não encontrado; usando o Chromium do Playwright.")
                self._ctx = self._pw.chromium.launch_persistent_context(str(cfg.profile), **opts)
        self._ctx.add_init_script(HOOK_JS)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._say(f"abrir {cfg.url}")
        self._page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)

        deadline = time.monotonic() + cfg.load_timeout
        state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            state = self.state()
            if state.get("found"):
                break
            time.sleep(0.5)
        self.map_found = bool(state.get("found"))
        if self.map_found:
            self._say(f"mapa encontrado (zoom {state.get('zoom')})")
        else:
            self._say(f"mapa NÃO encontrado na página: {state}")
        return state

    def close(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._pw, "stop")):
            if obj is not None:
                # O usuário pode já ter fechado o navegador.
                with contextlib.suppress(Exception):
                    getattr(obj, meth)()
        self._ctx = self._pw = self._page = None

    # ------------------------------------------------------------ comandos

    def state(self) -> dict[str, Any]:
        return dict(self._eval(STATE_JS) or {})

    def follow(self, lat: float, lng: float, force: bool = False) -> bool:
        """Centraliza o mapa na posição, respeitando o ritmo. Retorna True se moveu."""
        now = time.monotonic()
        if not force and now - self._last_move < self.config.min_interval:
            return False
        zoom = self.config.zoom if force else None
        res = self._eval(FOLLOW_JS, [lat, lng, zoom, self.config.min_pan_px, self.config.animate])
        if not res or not res.get("ok"):
            return False
        if res.get("moved"):
            self._last_move = now
            self._say(f"centralizar em ({lat:.2f}, {lng:.2f})")
            return True
        return False

    def show_player(self, lat: float, lng: float, confident: bool = True) -> None:
        self._eval(PLAYER_JS, [lat, lng, "#1e90ff" if confident else "#999999"])

    def highlight(self, lat: float, lng: float, label: str = "", seconds: float = 20.0) -> None:
        if self._eval(HIGHLIGHT_JS, [lat, lng, label, seconds]):
            self._say(f"destacar {label or 'ponto'} em ({lat:.2f}, {lng:.2f})")

    def unproject(self, x: float, y: float, zoom: int) -> tuple[float, float] | None:
        """Pixel global do Leaflet no zoom dado -> (lat, lng). Para mapas base feitos de tiles."""
        res = self._eval(UNPROJECT_JS, [x, y, zoom])
        return (float(res[0]), float(res[1])) if res else None

    def mark(self, marker_id: str) -> bool:
        """Marca como coletado no site, se houver um comando configurado para este site."""
        if not self.config.mark_js:
            return False
        js = self.config.mark_js.replace("{id}", _js_string(marker_id))
        try:
            self._page.evaluate(js)
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao marcar %s no site: %r", marker_id, exc)
            return False
        self._say(f"marcar coletado: {marker_id}")
        return True

    # ------------------------------------------------------------ internos

    def _eval(self, js: str, arg: Any = None) -> Any:
        if self._page is None:
            return None
        try:
            return self._page.evaluate(js, arg) if arg is not None else self._page.evaluate(js)
        except Exception as exc:  # noqa: BLE001 - página recarregando ou fechada
            log.debug("Falha no navegador: %r", exc)
            return None

    def _say(self, text: str) -> None:
        if self.sink is not None:
            self.sink.action(f"mapa: {text}")
        log.info("mapa: %s", text)


def _js_string(value: str) -> str:
    import json

    return json.dumps(value)
