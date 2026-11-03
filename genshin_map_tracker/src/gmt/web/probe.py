"""Diagnóstico do site do mapa interativo (rodar no PC do usuário).

Abre o site uma vez, num perfil de Chrome separado, e registra o que for preciso
para planejar a integração: biblioteca de mapa, URLs dos blocos (tiles) do mapa,
endpoints de dados de marcadores, chaves do armazenamento local e os termos de uso.

Comportamento: uma única visita, como uma pessoa abrindo a página. Não clica em
nada, não faz login e não baixa o mapa inteiro. Nada é enviado para fora do PC;
o relatório fica numa pasta local para o usuário decidir se compartilha.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

MAX_JSON_FILES = 25
MAX_JSON_BYTES = 5 * 1024 * 1024
TILE_RE = re.compile(r"/(\d{1,2})/(-?\d+)/(-?\d+)\.(png|jpe?g|webp)", re.I)
LEGAL_RE = re.compile(r"term|termo|privac|tos\b|legal|condi", re.I)

# Roda dentro da página: detecta bibliotecas de mapa e lê o estado sem alterar nada.
INSPECT_JS = r"""
() => {
  const out = {libs: {}, leaflet: [], globals: [], storage: {}, location: location.href};
  if (window.L && window.L.version) out.libs.leaflet = window.L.version;
  if (window.ol) out.libs.openlayers = true;
  if (window.mapboxgl) out.libs.mapbox = window.mapboxgl.version || true;
  if (window.maplibregl) out.libs.maplibre = window.maplibregl.version || true;
  if (window.google && window.google.maps) out.libs.googlemaps = true;

  // Globais criados pela página (comparando com um iframe vazio).
  try {
    const f = document.createElement('iframe'); f.style.display = 'none';
    document.body.appendChild(f);
    const base = new Set(Object.getOwnPropertyNames(f.contentWindow));
    out.globals = Object.getOwnPropertyNames(window).filter(k => !base.has(k)).slice(0, 300);
    f.remove();
  } catch (e) { out.globals_error = String(e); }

  const crsInfo = (crs) => {
    if (!crs) return null;
    const t = crs.transformation || {};
    let name = crs.code || null;
    if (!name && window.L.CRS) for (const k in window.L.CRS) if (window.L.CRS[k] === crs) name = k;
    return {name: name, infinite: !!crs.infinite,
            transformation: [t._a, t._b, t._c, t._d], extends: Object.keys(crs).slice(0, 20)};
  };
  // Instâncias de mapa Leaflet acessíveis por variáveis globais.
  if (window.L && window.L.Map) {
    for (const k of out.globals) {
      let v; try { v = window[k]; } catch (e) { continue; }
      if (v instanceof window.L.Map) {
        const info = {global: k, zoom: v.getZoom(), center: v.getCenter(),
                      minZoom: v.getMinZoom(), maxZoom: v.getMaxZoom(),
                      crs: crsInfo(v.options.crs),
                      layers: []};
        v.eachLayer(l => info.layers.push({
          type: l.constructor && l.constructor.name, url: l._url || null,
          options: l.options ? JSON.parse(JSON.stringify(l.options, (kk, vv) =>
            typeof vv === 'function' ? undefined : vv)) : null}));
        out.leaflet.push(info);
      }
    }
  }

  const stores = [['localStorage', localStorage], ['sessionStorage', sessionStorage]];
  for (const [name, store] of stores) {
    const items = {};
    try {
      for (let i = 0; i < store.length; i++) {
        const k = store.key(i); const v = store.getItem(k) || '';
        items[k] = {length: v.length, preview: v.slice(0, 300)};
      }
    } catch (e) { items.__error = String(e); }
    out.storage[name] = items;
  }
  out.canvases = document.querySelectorAll('canvas').length;
  out.title = document.title;
  return out;
}
"""

LINKS_JS = r"""
() => Array.from(document.querySelectorAll('a[href]'))
  .map(a => ({text: (a.innerText || '').trim().slice(0, 80), href: a.href}))
"""


class ProbeError(RuntimeError):
    pass


def _safe_name(url: str, idx: int) -> str:
    path = urlparse(url).path.strip("/").replace("/", "_") or "root"
    return f"{idx:02d}_{re.sub(r'[^A-Za-z0-9_.-]', '', path)[:60]}.json"


def run_probe(
    url: str,
    out_dir: Path,
    profile: Path,
    wait: float = 15.0,
    headless: bool = False,
    executable_path: str | None = None,
) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ProbeError(
            'Playwright não instalado. Rode: pip install -e ".[web]" e depois: '
            "python -m playwright install chromium"
        ) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    json_dir = out_dir / "json"
    json_dir.mkdir(exist_ok=True)

    requests: list[dict[str, Any]] = []
    tiles: dict[str, list[str]] = {}
    json_saved: list[dict[str, Any]] = []

    def on_response(resp: Any) -> None:
        try:
            rurl = resp.url
            ctype = (resp.headers or {}).get("content-type", "")
            entry = {"url": rurl, "status": resp.status, "type": ctype,
                     "resource": resp.request.resource_type}  # fmt: skip
            requests.append(entry)
            m = TILE_RE.search(rurl)
            if m and "image" in ctype:
                template = rurl[: m.start()] + "/{z}/{x}/{y}." + m.group(4) + rurl[m.end() :]
                tiles.setdefault(template, []).append(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")
            if "json" in ctype and len(json_saved) < MAX_JSON_FILES:
                body = resp.body()
                if len(body) <= MAX_JSON_BYTES:
                    name = _safe_name(rurl, len(json_saved))
                    (json_dir / name).write_bytes(body)
                    json_saved.append({"url": rurl, "file": f"json/{name}", "bytes": len(body)})
        except Exception as exc:  # noqa: BLE001 - resposta pode sumir (redirect, aborto)
            log.debug("Resposta ignorada: %r", exc)

    log.info("Abrindo %s (perfil %s)...", url, profile)
    with sync_playwright() as pw:
        opts: dict[str, Any] = {"headless": headless, "viewport": {"width": 1600, "height": 900}}
        if executable_path:
            ctx = pw.chromium.launch_persistent_context(
                str(profile), executable_path=executable_path, **opts
            )
        else:
            try:
                ctx = pw.chromium.launch_persistent_context(str(profile), channel="chrome", **opts)
            except Exception:  # noqa: BLE001 - Chrome não instalado: usa o do Playwright
                log.info("Chrome não encontrado; usando o Chromium do Playwright.")
                ctx = pw.chromium.launch_persistent_context(str(profile), **opts)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(wait)
            inspect = page.evaluate(INSPECT_JS)
            links = page.evaluate(LINKS_JS)
            page.screenshot(path=str(out_dir / "pagina.png"))

            origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            robots = page.request.get(urljoin(origin, "/robots.txt"))
            (out_dir / "robots.txt").write_text(
                robots.text() if robots.ok else f"HTTP {robots.status}", encoding="utf-8"
            )

            legal: list[dict[str, Any]] = []
            seen: set[str] = set()
            for link in links:
                href = link["href"]
                if not (LEGAL_RE.search(link["text"]) or LEGAL_RE.search(href)) or href in seen:
                    continue
                seen.add(href)
                if len(legal) >= 4:
                    break
                time.sleep(2.0)  # ritmo humano
                lp = ctx.new_page()
                try:
                    lp.goto(href, wait_until="domcontentloaded", timeout=30_000)
                    text = lp.inner_text("body")
                    fname = f"termos_{len(legal) + 1}.txt"
                    (out_dir / fname).write_text(f"{href}\n\n{text}", encoding="utf-8")
                    legal.append({"text": link["text"], "url": href, "file": fname})
                except Exception as exc:  # noqa: BLE001
                    legal.append({"text": link["text"], "url": href, "error": repr(exc)})
                finally:
                    lp.close()
        finally:
            ctx.close()

    report = {
        "url": url,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "page": inspect,
        "tile_templates": {k: sorted(set(v))[:50] for k, v in tiles.items()},
        "json_responses": json_saved,
        "legal_pages": legal,
        "links": links[:200],
        "requests": requests[:2000],
    }
    path = out_dir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
