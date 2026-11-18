"""`gmt preparar-mapa`: monta o mapa base com os tiles do próprio site.

Uma vez por camada (e de novo quando o site atualizar o mapa). Baixa devagar,
pula os tiles vazios que o próprio site lista, guarda tudo em cache (pode parar
e continuar) e no fim cria o índice da localização e a entrada no config.toml.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gmt.web.siteconfig import SiteConfigError, SiteMap, fetch_text, page_url, parse_site_maps
from gmt.web.tiles import TileJob, download_tiles, estimate, parse_black_tiles, stitch

log = logging.getLogger(__name__)

# Medido com prints reais: o minimapa equivale a ~zoom 15; o 14 é o melhor
# equilíbrio entre acerto da localização e memória para o mapa inteiro.
DEFAULT_ZOOM = 14


@dataclass(frozen=True)
class MapPlan:
    site_map: SiteMap
    job: TileJob
    image: Path

    @property
    def summary(self) -> str:
        return f"{self.site_map.key}, zoom {self.job.zoom}: {estimate(self.job)}"


def plan_map(key: str, zoom: int, out_dir: Path, lang: str = "pt") -> MapPlan:
    html = fetch_text(page_url(key, lang))
    maps = parse_site_maps(html)
    site_map = next((m for m in maps if m.key == key), None)
    if site_map is None:
        raise SiteConfigError(f"A página não trouxe a configuração do mapa '{key}'.")
    zoom = min(zoom, site_map.max_zoom)
    if zoom not in site_map.tile_bounds:
        raise SiteConfigError(f"Zoom {zoom} indisponível; opções: {sorted(site_map.tile_bounds)}")
    x0, x1, y0, y1 = site_map.tile_bounds[zoom]
    black: frozenset[tuple[int, int]] = frozenset()
    if site_map.black_tiles_url:
        black = parse_black_tiles(json.loads(fetch_text(site_map.black_tiles_url)), zoom)
    job = TileJob(
        site_map.url_template,
        zoom,
        x0,
        x1,
        y0,
        y1,
        site_map.tile_size,
        leaflet_offset=site_map.leaflet_offset(zoom),
        skip=black,
        y_up=site_map.centered,
    )
    return MapPlan(site_map, job, out_dir / f"{key}_z{zoom}.png")


def build_map(
    plan: MapPlan,
    cache_dir: Path,
    delay: float = 0.3,
    max_tiles: int = 9000,
    progress: Callable[[str], None] = print,
) -> Path:
    """Baixa (o que faltar), monta a imagem em tons de cinza e cria o índice."""
    from gmt.localization.mapindex import MapIndex

    progress(f"Baixando {plan.summary} (pode parar e rodar de novo: continua de onde parou)")
    got = download_tiles(plan.job, cache_dir, delay=delay, max_tiles=max_tiles, confirm=True)
    progress(f"{got} tiles baixados agora. Montando a imagem...")
    meta = stitch(plan.job, cache_dir, plan.image, gray=True)
    progress("Criando o índice da localização (alguns minutos)...")
    index = MapIndex.from_file(plan.image, name=plan.site_map.key)
    progress(f"Pronto: {plan.image} ({len(index.points)} pontos).")
    return meta


def config_entry(key: str, image: Path, meta_path: Path) -> str:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return (
        "\n[[maps]]\n"
        f'layer = "{key}"\n'
        f'image = "{image.as_posix()}"\n'
        f"tile_zoom = {meta['tile_zoom']}\n"
        f"tile_origin_x = {meta['tile_origin_x']}\n"
        f"tile_origin_y = {meta['tile_origin_y']}\n"
    )


def add_to_config(config: Path, key: str, image: Path, meta_path: Path) -> bool:
    """Acrescenta a camada ao config.toml (ou troca a que já existir). True se mudou."""
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    entry = config_entry(key, image, meta_path)
    out: list[str] = []
    skipping = False
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "[[maps]]":
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            skipping = nxt == f'layer = "{key}"'  # remove a entrada antiga desta camada
            if skipping:
                continue
        elif skipping and line.startswith("["):
            skipping = False  # outra seção: a entrada antiga acabou
        if not skipping:
            out.append(line)
    new = "\n".join(out).rstrip("\n") + "\n" + entry
    if new == text:
        return False
    config.write_text(new, encoding="utf-8")
    return True
