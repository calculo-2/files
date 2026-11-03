"""Teste do site-probe contra um site falso local (sem internet)."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

pytest.importorskip("playwright")

CHROMIUM = os.environ.get("GMT_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
if not Path(CHROMIUM).exists():
    pytest.skip("Chromium para testes não encontrado", allow_module_level=True)

from gmt.web.probe import run_probe  # noqa: E402

# Leaflet mínimo de mentira: só o que o probe consulta.
FAKE_PAGE = """<!doctype html><html><head><title>Mapa falso</title></head><body>
<a href="/terms.html">Termos de uso</a>
<script>
window.L = {version: '9.9.9', CRS: {}};
L.CRS.Simple = {transformation: {_a: 1, _b: 0, _c: -1, _d: 0}, infinite: true};
L.Map = class { constructor() { this.options = {crs: L.CRS.Simple}; this._layers = []; }
  getZoom() { return 3 } getCenter() { return {lat: -10, lng: 20} }
  getMinZoom() { return 0 } getMaxZoom() { return 6 }
  eachLayer(fn) { this._layers.forEach(fn) } };
window.mapa = new L.Map();
mapa._layers.push({_url: '/tiles/{z}/{x}/{y}.png', options: {tileSize: 256}});
for (const [x, y] of [[1, 1], [1, 2]]) {
  const img = new Image(); img.src = `/tiles/3/${x}/${y}.png`; document.body.appendChild(img);
}
fetch('/data/markers.json').then(r => r.json()).then(d => window.markers = d);
localStorage.setItem('achados', '[1,2,3]');
</script></body></html>"""


@pytest.fixture
def site(tmp_path: Path) -> Iterator[str]:
    root = tmp_path / "site"
    (root / "data").mkdir(parents=True)
    (root / "index.html").write_text(FAKE_PAGE, encoding="utf-8")
    (root / "terms.html").write_text("<h1>Termos</h1><p>Sem bots.</p>", encoding="utf-8")
    (root / "robots.txt").write_text("User-agent: *\nDisallow: /api/\n", encoding="utf-8")
    (root / "data" / "markers.json").write_text('{"chests": [1]}', encoding="utf-8")
    ok, png = cv2.imencode(".png", np.full((8, 8, 3), 128, np.uint8))
    assert ok
    for x, y in ((1, 1), (1, 2)):
        d = root / "tiles" / "3" / str(x)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{y}.png").write_bytes(png.tobytes())

    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()


def test_probe_report(site: str, tmp_path: Path) -> None:
    out = tmp_path / "out"
    path = run_probe(
        site, out, tmp_path / "perfil", wait=2, headless=True, executable_path=CHROMIUM
    )
    report = json.loads(path.read_text(encoding="utf-8"))

    page = report["page"]
    assert page["libs"]["leaflet"] == "9.9.9"
    assert page["leaflet"][0]["global"] == "mapa"
    assert page["leaflet"][0]["crs"]["name"] == "Simple"
    assert page["leaflet"][0]["layers"][0]["url"] == "/tiles/{z}/{x}/{y}.png"
    assert page["storage"]["localStorage"]["achados"]["preview"] == "[1,2,3]"

    template = next(iter(report["tile_templates"]))
    assert template.endswith("/tiles/{z}/{x}/{y}.png")
    assert sorted(report["tile_templates"][template]) == ["3/1/1", "3/1/2"]

    assert report["json_responses"][0]["url"].endswith("/data/markers.json")
    assert (out / report["json_responses"][0]["file"]).exists()
    assert report["legal_pages"][0]["file"] == "termos_1.txt"
    assert "Sem bots" in (out / "termos_1.txt").read_text(encoding="utf-8")
    assert "Disallow: /api/" in (out / "robots.txt").read_text(encoding="utf-8")
    assert (out / "pagina.png").exists()
