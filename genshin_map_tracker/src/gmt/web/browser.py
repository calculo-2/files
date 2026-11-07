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
from typing import Any, Literal, Protocol

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
  if (window.__gmt.follow === false) return {ok: true, moved: false, paused: true};
  const box = m.getContainer().getBoundingClientRect();
  // Painel (barra lateral) por cima da borda esquerda do mapa: mede a largura dele para
  // centralizar na área que a pessoa realmente vê.
  let panel = 0;
  const el = document.elementFromPoint(box.left + 5, box.top + box.height / 2);
  if (el && !m.getContainer().contains(el)) {
    let e = el;
    while (e.parentElement && e.parentElement.getBoundingClientRect().width < box.width * 0.6) {
      e = e.parentElement;
    }
    const r = e.getBoundingClientRect();
    const narrow = r.width < box.width * 0.6;
    if (r.left <= box.left + 5 && narrow) panel = Math.max(0, r.right - box.left);
  }
  const z = zoom === null ? m.getZoom() : zoom;
  const target = window.L.latLng(lat, lng);
  const center = m.unproject(m.project(target, z).subtract([panel / 2, 0]), z);
  const seen = window.L.point(box.width / 2 + panel / 2, box.height / 2);
  const d = seen.distanceTo(m.latLngToContainerPoint(target));
  if (zoom === null && d < minPx) return {ok: true, moved: false, px: d, panel: panel};
  if (zoom === null) m.panTo(center, {animate: animate, duration: 0.4});
  else m.setView(center, zoom, {animate: animate});
  return {ok: true, moved: true, px: d, panel: panel};
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

# Painel flutuante do gmt dentro da página do mapa: seguir/soltar, centralizar, zoom e
# status. Arrastar o mapa com o mouse solta o "seguir" (a pessoa quer olhar em volta).
CONTROLS_JS = r"""
() => {
  const G = window.__gmt; const m = G && G.map();
  if (!m) return false;
  if (G.follow === undefined) G.follow = true;
  let box = document.getElementById('gmt-panel');
  if (!box) {
    box = document.createElement('div');
    box.id = 'gmt-panel';
    box.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:100000;display:flex;' +
      'flex-direction:column;gap:6px;padding:8px;border-radius:10px;font:13px sans-serif;' +
      'background:rgba(20,24,32,.88);color:#fff;box-shadow:0 2px 10px rgba(0,0,0,.4)';
    box.innerHTML =
      '<div id="gmt-status" style="opacity:.85">gmt: aguardando posição</div>' +
      '<div style="display:flex;gap:6px">' +
      '<button id="gmt-follow" style="flex:1;padding:6px 10px;border:0;' +
      'border-radius:6px"></button>' +
      '<button id="gmt-zin" style="width:34px">+</button>' +
      '<button id="gmt-zout" style="width:34px">−</button></div>';
    document.body.appendChild(box);
    // Um botão só: "Seguir-me" (centraliza em você e segue) / "Soltar" (para de seguir).
    const paint = () => {
      const b = document.getElementById('gmt-follow');
      b.textContent = G.follow ? 'Soltar' : 'Seguir-me';
      b.title = G.follow ? 'O mapa está seguindo você' : 'O mapa está solto';
      b.style.background = G.follow ? '#555' : '#1e90ff';
      b.style.color = '#fff';
    };
    G.setFollow = (on) => {
      G.follow = on; paint();
      if (on && G.player) m.panTo(G.player.getLatLng());
    };
    document.getElementById('gmt-follow').onclick = () => G.setFollow(!G.follow);
    document.getElementById('gmt-zin').onclick = () => m.zoomIn();
    document.getElementById('gmt-zout').onclick = () => m.zoomOut();
    m.on('dragstart', () => G.setFollow(false));
    paint();
  }
  return true;
}
"""

STATUS_JS = r"""
([text, ok]) => {
  const el = document.getElementById('gmt-status');
  if (!el) return false;
  el.textContent = text;
  el.style.color = ok ? '#9fe29f' : '#ffb3b3';
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


# Marcadores do site perto de um ponto (pixel global no zoom dado), lidos da tabela
# da camada de marcadores do appsample: ids, posição normalizada (mx, my), tipo e "found".
SITE_NEARBY_JS = r"""
([gx, gy, zoom, radius, types]) => {
  const m = window.__gmt && window.__gmt.map();
  if (!m) return {error: 'mapa não encontrado'};
  let layer = null;
  m.eachLayer(l => { if (l.table && l.table.mx) layer = l; });
  if (!layer) return {error: 'camada de marcadores não encontrada'};
  const t = layer.table, s = m.options.crs.scale(zoom), want = new Set(types || []);
  const out = [];
  for (let i = 0; i < t.count; i++) {
    const type = t.typeKeys ? t.typeKeys[t.type[i]] : null;
    if (want.size && !want.has(type)) continue;
    const x = t.mx[i] * s, y = t.my[i] * s, d = Math.hypot(x - gx, y - gy);
    if (d <= radius) out.push({id: String(t.ids[i]), type: type, d: d, x: x, y: y,
                               found: t.found ? !!t.found[i] : false});
  }
  out.sort((a, b) => a.d - b.d);
  return {markers: out.slice(0, 20), total: t.count};
}
"""

# Centraliza no marcador e devolve o ponto da tela onde ele ficou.
SITE_CENTER_JS = r"""
([id]) => {
  const m = window.__gmt && window.__gmt.map();
  let layer = null;
  m && m.eachLayer(l => { if (l.table && l.table.rowOf) layer = l; });
  if (!layer) return null;
  const t = layer.table, row = t.rowOf.get(String(id)) ?? t.rowOf.get(Number(id));
  if (row === undefined) return null;
  const s0 = m.options.crs.scale(0);
  const ll = m.unproject(window.L.point(t.mx[row] * s0, t.my[row] * s0), 0);
  // Zoom máximo para separar marcadores vizinhos antes do clique; o app volta depois.
  const prevZoom = m.getZoom(), maxZoom = m.getMaxZoom();
  m.setView(ll, Number.isFinite(maxZoom) ? maxZoom : prevZoom + 4, {animate: false});
  const cp = m.latLngToContainerPoint(ll), r = m.getContainer().getBoundingClientRect();
  return {x: r.left + cp.x, y: r.top + cp.y, found: t.found ? !!t.found[row] : false,
          prevZoom: prevZoom};
}
"""

SITE_FOUND_JS = r"""
([id]) => {
  const m = window.__gmt && window.__gmt.map();
  let layer = null;
  m && m.eachLayer(l => { if (l.table && l.table.rowOf) layer = l; });
  if (!layer || !layer.table.found) return null;
  const row = layer.table.rowOf.get(String(id)) ?? layer.table.rowOf.get(Number(id));
  return row === undefined ? null : !!layer.table.found[row];
}
"""

# Botão "marcar como encontrado" do popup: variante "success" do site.
# A janela do marcador no appsample é um cartão do próprio site (não o popup do Leaflet):
# título ("Baú Sofisticado"), categoria e o botão verde "Marcar como encontrado".
# Procura o botão visível pelo texto (ou pela classe btn-success) e o marca para o clique.
POPUP_JS = r"""
([labels]) => {
  const norm = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const want = labels.map(norm);
  const visible = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
           r.top < innerHeight && r.left < innerWidth; };
  document.querySelectorAll('[data-gmt-found]').forEach(e => e.removeAttribute('data-gmt-found'));
  const buttons = Array.from(document.querySelectorAll('button')).filter(visible);
  let btn = buttons.find(b => want.includes(norm(b.innerText)));
  if (!btn) btn = buttons.find(b => /btn-success/.test(b.className) && !b.closest('#gmt-panel'));
  if (!btn) return {open: false};
  btn.setAttribute('data-gmt-found', '1');
  // Sobe até o cartão que contém o botão para ler o título do marcador.
  let card = btn; for (let i = 0; i < 6 && card.parentElement; i++) card = card.parentElement;
  return {open: true, hasButton: true, text: card.innerText.slice(0, 300)};
}
"""

# Rótulos do botão de marcar (o site traduz pela língua da página).
FOUND_LABELS = ["Marcar como encontrado", "Mark as found", "Marcar como encontrada"]


class ActionSink(Protocol):
    def action(self, text: str) -> None: ...


class BrowserError(RuntimeError):
    pass


MarkResult = Literal[
    "marked", "already", "need_login", "no_popup", "not_found", "wrong_marker", "failed"
]


@dataclass(frozen=True)
class SiteMarker:
    id: str
    type: str | None
    distance: float  # pixels globais no zoom pedido
    found: bool
    x: float = 0.0  # pixel global no zoom pedido
    y: float = 0.0


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
    compact: bool = False  # janela de aplicativo: sem abas nem barra de endereço
    window: tuple[int, int, int, int] | None = None  # x, y, largura, altura (tela inteira)
    controls: bool = True  # painel flutuante do gmt dentro do mapa


class MapBrowser:
    def __init__(self, config: BrowserConfig, sink: ActionSink | None = None) -> None:
        self.config = config
        self.sink = sink
        self._pw: Any = None
        self._ctx: Any = None
        self._page: Any = None
        self._last_move = 0.0
        self._expect: tuple[str, ...] = ()
        self.map_found = False

    # -------------------------------------------------------------- ciclo

    def open(self) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserError('Playwright não instalado: pip install -e ".[web]"') from exc

        cfg = self.config
        self._pw = sync_playwright().start()
        args: list[str] = []
        if cfg.compact:
            args.append(f"--app={cfg.url}")
        if cfg.window is not None:
            x, y, w, h = cfg.window
            args += [f"--window-position={x},{y}", f"--window-size={w},{h}"]
        opts: dict[str, Any] = {"headless": cfg.headless, "no_viewport": True, "args": args}
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
        self._page = self._pick_page()
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
        if self.map_found and cfg.controls:
            self._eval(CONTROLS_JS)
        if self.map_found:
            self._say(f"mapa encontrado (zoom {state.get('zoom')})")
        else:
            self._say(f"mapa NÃO encontrado na página: {state}")
        return state

    def _pick_page(self) -> Any:
        """Escolhe a aba do mapa. No modo aplicativo o Chrome pode abrir também uma aba em
        branco; ela é fechada para sobrar só a janela do mapa."""
        pages = list(self._ctx.pages)
        if self.config.compact:
            time.sleep(1.0)  # dá tempo da janela de aplicativo aparecer
            pages = list(self._ctx.pages)
            site = [p for p in pages if not p.url.startswith("about:")]
            if site:
                for extra in pages:
                    if extra not in site[:1]:
                        with contextlib.suppress(Exception):
                            extra.close()
                return site[0]
        return pages[0] if pages else self._ctx.new_page()

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

    def set_status(self, text: str, ok: bool = True) -> None:
        """Texto de status no painel flutuante (recria o painel se a página recarregou)."""
        if self.config.controls and not self._eval(STATUS_JS, [text, ok]):
            self._eval(CONTROLS_JS)

    @property
    def following(self) -> bool:
        return self._eval("() => window.__gmt ? window.__gmt.follow !== false : true") is not False

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

    # ---------------------------------------------------- marcadores do site

    def site_categories(self) -> dict[str, tuple[str, ...]]:
        """{tipo interno: ids do site} lido da barra lateral (com reserva fixa)."""
        from gmt.web.appsample import CATEGORY_JS, type_ids_from_buttons

        return type_ids_from_buttons(self._eval(CATEGORY_JS) or [])

    def nearby_site_markers(
        self, gx: float, gy: float, zoom: int, radius: float, types: list[str]
    ) -> list[SiteMarker] | None:
        """Marcadores do site dos tipos dados num raio (pixels globais no `zoom`)."""
        res = self._eval(SITE_NEARBY_JS, [gx, gy, zoom, radius, types])
        if not res or "markers" not in res:
            log.debug("Marcadores do site indisponíveis: %s", res)
            return None
        return [
            SiteMarker(
                m["id"], m["type"], float(m["d"]), bool(m["found"]), float(m["x"]), float(m["y"])
            )
            for m in res["markers"]
        ]

    def site_marker_found(self, marker_id: str) -> bool:
        """O marcador já está como encontrado no site (por você ou pelo app)?"""
        return bool(self._eval(SITE_FOUND_JS, [marker_id]))

    def mark_found_ui(
        self, marker_id: str, timeout: float = 5.0, expect: tuple[str, ...] = ()
    ) -> MarkResult:
        """Marca pela interface do site, como uma pessoa: abre o marcador e clica no botão.

        Só acontece no navegador. Depende de login no site (o progresso fica na conta).
        """
        if self._page is None:
            return "failed"
        self._expect = expect  # nomes aceitos no título do cartão (ex.: "Baú Comum")
        spot = self._eval(SITE_CENTER_JS, [marker_id])
        if not spot:
            return "not_found"
        try:
            return self._click_found(marker_id, spot, timeout)
        finally:
            zoom = spot.get("prevZoom")
            if zoom is not None:  # volta ao zoom em que o usuário estava
                self._eval("([z]) => window.__gmt.map().setZoom(z, {animate: false})", [zoom])

    def _click_found(self, marker_id: str, spot: dict[str, Any], timeout: float) -> MarkResult:
        if spot.get("found"):
            return "already"
        time.sleep(0.4)  # deixa o mapa redesenhar
        self._page.mouse.click(spot["x"], spot["y"])
        deadline = time.monotonic() + timeout
        popup: dict[str, Any] = {}
        while time.monotonic() < deadline:
            popup = self._eval(POPUP_JS, [FOUND_LABELS]) or {}
            if popup.get("open"):
                break
            if self._eval(SITE_FOUND_JS, [marker_id]):
                return "already"
            time.sleep(0.2)
        if not popup.get("open"):
            return "no_popup"
        expect = self._expect
        if expect and not any(n.lower() in popup.get("text", "").lower() for n in expect):
            log.warning("Cartão aberto não é do tipo esperado: %r", popup.get("text", "")[:80])
            return "wrong_marker"
        self._page.click('[data-gmt-found="1"]')
        while time.monotonic() < deadline + timeout:
            if self._eval(SITE_FOUND_JS, [marker_id]):
                self._say(f"marcado como encontrado no site: {marker_id}")
                return "marked"
            if self._page.query_selector('[role="dialog"]'):
                self._say("o site pediu login: entre na sua conta no Chrome do gmt")
                return "need_login"
            time.sleep(0.25)
        return "failed"

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
