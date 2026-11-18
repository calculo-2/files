"""Controle do mapa com o Leaflet de verdade num site falso local."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from .webtools import CHROMIUM, require_browser, serve

require_browser()

from gmt.web.browser import BrowserConfig, MapBrowser  # noqa: E402

# O mapa é criado dentro de uma função, sem variável global: o gancho precisa achá-lo.
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mapa</title>
<script src="/leaflet.js"></script></head><body style="margin:0">
<div id="map" style="width:1000px;height:700px"></div>
<script>
window.siteApi = {found: [], markFound(id) { this.found.push(id); }};
(function () {
  const m = L.map('map', {crs: L.CRS.Simple, minZoom: -2, maxZoom: 4}).setView([0, 0], 1);
})();
</script></body></html>"""


class Sink:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def action(self, text: str) -> None:
        self.lines.append(text)


@pytest.fixture
def browser(tmp_path: Path):  # type: ignore[no-untyped-def]
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE, encoding="utf-8")
    with serve(site) as base:
        sink = Sink()
        cfg = BrowserConfig(
            url=f"{base}/index.html",
            profile=tmp_path / "perfil",
            headless=True,
            executable_path=CHROMIUM,
            min_interval=0.3,
            min_pan_px=40,
            animate=False,
            mark_js="window.siteApi.markFound({id})",
            load_timeout=15,
        )
        b = MapBrowser(cfg, sink)
        try:
            yield b, sink
        finally:
            b.close()


def test_finds_hidden_map_and_follows(browser) -> None:  # type: ignore[no-untyped-def]
    b, sink = browser
    state = b.open()
    assert state["found"] and state["zoom"] == 1
    assert b.follow(-50.0, 80.0)
    st = b.state()
    assert (st["lat"], st["lng"]) == pytest.approx((-50.0, 80.0), abs=1e-6)
    assert any("centralizar" in line for line in sink.lines)


def test_human_pace(browser) -> None:  # type: ignore[no-untyped-def]
    b, _ = browser
    b.open()
    assert b.follow(-50.0, 80.0)
    assert not b.follow(-200.0, 300.0), "antes do intervalo mínimo não deve mover"
    st = b.state()
    assert (st["lat"], st["lng"]) == pytest.approx((-50.0, 80.0))
    time.sleep(0.35)
    assert b.follow(-200.0, 300.0), "depois do intervalo deve mover"


def test_small_moves_are_ignored(browser) -> None:  # type: ignore[no-untyped-def]
    b, _ = browser
    b.open()
    assert b.follow(-50.0, 80.0)
    time.sleep(0.35)
    # Zoom 1 em CRS.Simple: 1 unidade = 2 px na tela; 5 unidades = 10 px < 40 px.
    assert not b.follow(-50.0, 85.0)
    time.sleep(0.35)
    assert b.follow(-50.0, 120.0)  # 40 unidades = 80 px


def test_player_highlight_unproject_mark(browser) -> None:  # type: ignore[no-untyped-def]
    b, sink = browser
    b.open()
    b.show_player(-10.0, 20.0)
    b.show_player(-11.0, 21.0, confident=False)
    b.highlight(-12.0, 22.0, "Baú?", seconds=5)
    page = b._page
    assert page.evaluate("window.__gmt.player.getLatLng().lat") == -11.0
    # CRS.Simple: no zoom 0, pixel (x, y) = (lng, -lat).
    assert b.unproject(30.0, 40.0, 0) == pytest.approx((-40.0, 30.0))
    assert b.mark('chest"42')
    assert page.evaluate("window.siteApi.found") == ['chest"42']
    assert any("marcar coletado" in line for line in sink.lines)


def test_page_without_map(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html><body>sem mapa</body></html>", encoding="utf-8")
    with serve(site) as base:
        b = MapBrowser(
            BrowserConfig(
                url=f"{base}/index.html",
                profile=tmp_path / "p",
                headless=True,
                executable_path=CHROMIUM,
                load_timeout=2,
            )  # fmt: skip
        )
        try:
            state = b.open()
            assert not state["found"] and not b.map_found
            assert not b.follow(0, 0)
        finally:
            b.close()


def test_follow_centers_in_visible_area(tmp_path: Path) -> None:
    """Com uma barra lateral por cima do mapa, o alvo fica no meio da parte visível."""
    page = PAGE.replace(
        '<div id="map" style="width:1000px;height:700px"></div>',
        '<div id="map" style="width:1000px;height:700px"></div>'
        '<div id="side" style="position:absolute;left:0;top:0;width:300px;height:700px;'
        'background:#fff;z-index:2000"><p>painel</p></div>',
    )
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(page, encoding="utf-8")
    with serve(site) as base:
        b = MapBrowser(BrowserConfig(url=f"{base}/index.html", profile=tmp_path / "p",
                                     headless=True, executable_path=CHROMIUM, animate=False,
                                     load_timeout=15))  # fmt: skip
        try:
            b.open()
            assert b.follow(-40.0, 60.0, force=True)
            x = b._page.evaluate("() => window.__gmt.map().latLngToContainerPoint([-40, 60]).x")
            assert x == pytest.approx(300 + (1000 - 300) / 2, abs=2)
        finally:
            b.close()


def test_floating_controls(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE, encoding="utf-8")
    with serve(site) as base:
        cfg = BrowserConfig(
            url=f"{base}/index.html",
            profile=tmp_path / "p",
            headless=True,
            executable_path=CHROMIUM,
            animate=False,
            min_interval=0,
            load_timeout=15,
            compact=True,
            window=(0, 0, 900, 700),
        )
        b = MapBrowser(cfg)
        try:
            b.open()
            page = b._page
            assert page.inner_text("#gmt-follow") == "Soltar"
            b.show_player(-10.0, 20.0)
            b.set_status("Posição: teyvat", True)
            assert page.inner_text("#gmt-status") == "Posição: teyvat"
            # Arrastar o mapa solta o "seguir"; o app para de mover o mapa.
            page.evaluate("() => window.__gmt.map().fire('dragstart')")
            assert page.inner_text("#gmt-follow") == "Seguir-me"
            assert not b.following
            assert not b.follow(-60.0, 90.0)
            # "Seguir-me" volta a seguir e centraliza no jogador.
            page.click("#gmt-follow")
            assert b.following
            time.sleep(0.6)
            c = b.state()
            assert (c["lat"], c["lng"]) == pytest.approx((-10.0, 20.0), abs=0.5)
            zoom = c["zoom"]
            page.click("#gmt-zin")
            time.sleep(0.4)
            assert b.state()["zoom"] == zoom + 1
        finally:
            b.close()
