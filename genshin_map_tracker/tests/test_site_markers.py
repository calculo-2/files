"""Marcação pela interface numa réplica local da estrutura do appsample."""

from __future__ import annotations

from pathlib import Path

import pytest

from .webtools import CHROMIUM, require_browser, serve

require_browser()

from gmt.web.appsample import DEFAULT_TYPE_IDS, type_ids_from_buttons  # noqa: E402
from gmt.web.browser import BrowserConfig, MapBrowser  # noqa: E402

# Mesmo formato da tabela do site: mx/my normalizados (0..1), tipo por índice, found por linha.
PAGE = """<!doctype html><html><head><meta charset="utf-8"><script src="/leaflet.js"></script>
<style>.leaflet-popup{position:absolute}</style></head><body style="margin:0">
<div id="side"><button title="Baú Comum"><img src="https://cdn/gim/markers/o17.png?v=3"></button>
<button title="Geoculus"><img src="https://cdn/gim/markers/o6.png?v=3"></button></div>
<div id="map" style="width:1000px;height:700px"></div>
<script>
window.loggedIn = true;
(function () {
  const m = L.map('map').setView([0.1, 0.4], 12);
  // 'cover' (Geoculus) está exatamente em cima de 'b4' e foi desenhado depois (fica por cima).
  const pts = [['b1', 0.1, 0.4, 0], ['b2', 0.102, 0.4, 0], ['g1', 0.1, 0.403, 1],
               ['b3', 0.2, 0.5, 0], ['b4', 0.15, 0.45, 0], ['cover', 0.15, 0.45, 1]];
  const n = pts.length, t = {count: n, ids: [], rowOf: new Map(), mx: new Float64Array(n),
    my: new Float64Array(n), type: new Uint16Array(n), typeKeys: ['o17', 'o6'],
    found: new Uint8Array(n), visible: new Uint8Array(n).fill(1)};
  pts.forEach(([id, lat, lng, ty], i) => {
    const p = m.project([lat, lng], 0);
    t.ids.push(id); t.rowOf.set(id, i); t.mx[i] = p.x / 256; t.my[i] = p.y / 256; t.type[i] = ty;
  });
  t.found[3] = 1;
  const Layer = L.Layer.extend({onAdd() {}, onRemove() {}});
  const layer = new Layer(); layer.table = t; layer.addTo(m);
  // Como o hitTest do site: linhas sob o ponto, a de cima (desenhada depois) primeiro.
  layer.hitTest = (cp) => {
    const out = [];
    for (let i = n - 1; i >= 0; i--) {
      const s0 = m.options.crs.scale(0);
      const q = m.latLngToContainerPoint(m.unproject(L.point(t.mx[i] * s0, t.my[i] * s0), 0));
      if (Math.abs(q.x - cp.x) <= 14 && cp.y - q.y <= 24 && q.y - cp.y <= 8) out.push(i);
    }
    return out;
  };
  m.on('click', e => {
    const cp = e.containerPoint; let best = -1, bd = 1e9;
    for (let i = 0; i < n; i++) {
      const s0 = m.options.crs.scale(0);
      const q = m.latLngToContainerPoint(m.unproject(L.point(t.mx[i] * s0, t.my[i] * s0), 0));
      const d = q.distanceTo(cp); if (d < bd) { bd = d; best = i; }
    }
    if (best < 0 || bd > 15) return;
    // Cartão do próprio site (como no appsample real), fora do Leaflet.
    let card = document.getElementById('card');
    if (!card) { card = document.createElement('div'); card.id = 'card';
      card.style.cssText = 'position:fixed;left:500px;top:100px;background:#fff;padding:8px';
      document.body.appendChild(card); }
    const title = t.type[best] ? 'Geoculus' : 'Baú Sofisticado';
    const action = t.found[best] ? '<span>Encontrado</span>'
      : '<button class="btn btn-sm btn-success px-5">Marcar como encontrado</button>';
    card.innerHTML = '<b>' + title + '</b><div>Baú · Ocultar tudo</div>' + action;
    const btn = card.querySelector('button');
    if (btn) btn.onclick = () => {
      if (window.loggedIn) { t.found[best] = 1; card.innerHTML = '<b>' + title + '</b>'; }
      else { const d = document.createElement('div'); d.setAttribute('role', 'dialog');
             d.textContent = 'Entrar'; document.body.appendChild(d); }
    };
  });
})();
</script></body></html>"""


@pytest.fixture
def site(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    with serve(root) as base:
        cfg = BrowserConfig(
            url=f"{base}/index.html",
            profile=tmp_path / "p",
            headless=True,
            executable_path=CHROMIUM,
            load_timeout=15,
        )
        b = MapBrowser(cfg)
        try:
            b.open()
            yield b
        finally:
            b.close()


def _global(b: MapBrowser, lat: float, lng: float, zoom: int) -> tuple[float, float]:
    p = b._page.evaluate(f"() => window.__gmt.map().project([{lat}, {lng}], {zoom})")
    return p["x"], p["y"]


def test_nearby_filters_type_and_distance(site: MapBrowser) -> None:
    gx, gy = _global(site, 0.1, 0.4, 14)
    near = site.nearby_site_markers(gx, gy, 14, 300, ["o17"])
    assert near is not None
    assert [m.id for m in near] == ["b1", "b2"]
    assert near[0].distance < 1 and not near[0].found
    geo = site.nearby_site_markers(gx, gy, 14, 300, ["o6"])
    assert geo is not None and [m.id for m in geo] == ["g1"]


def test_mark_found_ui(site: MapBrowser) -> None:
    zoom_before = site.state()["zoom"]
    assert site.mark_found_ui("b1") == "marked"
    assert site.state()["zoom"] == zoom_before, "deve voltar ao zoom do usuário"
    assert site.mark_found_ui("b1") == "already"
    assert site.mark_found_ui("b3") == "already"
    assert site.mark_found_ui("nao-existe") == "not_found"


def test_refuses_wrong_marker_type(site: MapBrowser) -> None:
    assert site.mark_found_ui("g1", expect=("Baú Comum", "Baú Sofisticado")) == "wrong_marker"
    assert site.mark_found_ui("b1", expect=("Baú Comum", "Baú Sofisticado")) == "marked"


def test_covered_icon_is_not_clicked(site: MapBrowser) -> None:
    zoom_before = site.state()["zoom"]
    assert site.mark_found_ui("b4") == "overlap"
    assert site.state()["zoom"] == zoom_before, "volta ao zoom do usuário mesmo sem clicar"
    found = site._page.evaluate(
        "() => { let L; window.__gmt.map().eachLayer(l => { if (l.table) L = l; });"
        " return Array.from(L.table.found); }"
    )
    assert found[4] == 0 and found[5] == 0, "não pode marcar nem o baú nem o ícone de cima"


def test_mark_requires_login(site: MapBrowser) -> None:
    site._page.evaluate("() => { window.loggedIn = false; }")
    assert site.mark_found_ui("b2", timeout=2) == "need_login"


def test_categories_from_sidebar(site: MapBrowser) -> None:
    cats = site.site_categories()
    assert cats["chest"] == ("o17",)
    assert cats["geoculus"] == ("o6",)
    assert cats["pyroculus"] == DEFAULT_TYPE_IDS["pyroculus"]  # reserva quando não há botão


def test_type_ids_from_buttons_offline() -> None:
    ids = type_ids_from_buttons([{"title": "Baú Precioso", "type": "o45"}])
    assert ids["chest"] == ("o45",)
