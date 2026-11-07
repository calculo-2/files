"""Monta um mapa base a partir dos tiles (blocos de imagem) do site do mapa.

USE SÓ SE os termos de uso do site permitirem. Por padrão:
- mostra a estimativa (quantidade de tiles e tamanho) e só baixa com `confirm=True`;
- baixa devagar (1 tile a cada `delay` segundos), como alguém navegando no mapa;
- guarda cada tile em cache: se parar no meio, continua de onde parou;
- tem um limite máximo de tiles por execução.

Saída: uma imagem PNG e um JSON com o zoom e a origem, para a conversão exata
pixel -> coordenada do site (ver gmt.app.TileConverter).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TileJob:
    template: str  # ex.: https://.../tiles/{z}/{x}/{y}.webp
    zoom: int
    x_min: int
    x_max: int  # inclusivo
    y_min: int
    y_max: int
    tile_size: int = 256
    leaflet_offset: int = 0  # índice Leaflet = índice no site + offset (appsample: 2**(zoom-1))
    # Tiles sabidamente vazios (ex.: black-tile.json do appsample).
    skip: frozenset[tuple[int, int]] = frozenset()
    # True: y cresce para cima (appsample). O Leaflet usa y crescendo para baixo.
    y_up: bool = False

    @property
    def leaflet_origin_y(self) -> int:
        """Pixel global (Leaflet) da borda de cima da imagem montada."""
        if self.y_up:  # índice Leaflet = offset - 1 - y
            return (self.leaflet_offset - 1 - self.y_max) * self.tile_size
        return (self.y_min + self.leaflet_offset) * self.tile_size

    @property
    def count(self) -> int:
        return sum(1 for _ in self.tiles())

    def tiles(self) -> list[tuple[int, int]]:
        return [
            (x, y)
            for y in range(self.y_min, self.y_max + 1)
            for x in range(self.x_min, self.x_max + 1)
            if (x, y) not in self.skip
        ]

    @property
    def pixel_size(self) -> tuple[int, int]:
        return (
            (self.x_max - self.x_min + 1) * self.tile_size,
            (self.y_max - self.y_min + 1) * self.tile_size,
        )

    def url(self, x: int, y: int) -> str:
        return (
            self.template.replace("{z}", str(self.zoom))
            .replace("{x}", str(x))
            .replace("{y}", str(y))
        )


def estimate(job: TileJob) -> str:
    w, h = job.pixel_size
    mb = job.count * 25 / 1024  # ~25 KB por tile
    return f"{job.count} tiles, imagem final {w}x{h}, download ~{mb:.0f} MB"


def download_tiles(
    job: TileJob,
    cache_dir: Path,
    delay: float = 1.0,
    max_tiles: int = 3000,
    confirm: bool = False,
    user_agent: str = "Mozilla/5.0 (gmt; uso pessoal)",
) -> int:
    """Baixa os tiles que faltam no cache. Retorna quantos foram baixados agora."""
    if not confirm:
        raise PermissionError("Confirme depois de ler os termos de uso e a estimativa.")
    if job.count > max_tiles:
        raise ValueError(f"{job.count} tiles passa do limite de {max_tiles}; reduza a área.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for x, y in job.tiles():
        path = cache_dir / f"{job.zoom}_{x}_{y}.img"
        if path.exists():
            continue
        req = urllib.request.Request(job.url(x, y), headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                path.write_bytes(resp.read())
        except Exception as exc:  # noqa: BLE001 - tile inexistente (fora do mapa)
            log.debug("Tile %d,%d falhou: %r", x, y, exc)
            path.write_bytes(b"")  # marca como vazio para não tentar de novo
        fetched += 1
        time.sleep(delay)
    return fetched


def stitch(job: TileJob, cache_dir: Path, out_image: Path, gray: bool = False) -> Path:
    """Junta os tiles do cache numa imagem e grava o JSON de origem ao lado.

    `gray=True` monta direto em tons de cinza (1/3 da memória): é o que a localização usa.
    """
    w, h = job.pixel_size
    canvas = np.zeros((h, w) if gray else (h, w, 3), np.uint8)
    mode = cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR
    ts = job.tile_size
    for y in range(job.y_min, job.y_max + 1):
        for x in range(job.x_min, job.x_max + 1):
            path = cache_dir / f"{job.zoom}_{x}_{y}.img"
            if not path.exists() or path.stat().st_size == 0:
                continue
            tile = cv2.imdecode(np.fromfile(str(path), np.uint8), mode)
            if tile is None:
                continue
            tile = cv2.resize(tile, (ts, ts)) if tile.shape[:2] != (ts, ts) else tile
            row = (job.y_max - y) if job.y_up else (y - job.y_min)
            oy, ox = row * ts, (x - job.x_min) * ts
            canvas[oy : oy + ts, ox : ox + ts] = tile
    out_image.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(out_image.suffix or ".png", canvas)
    if not ok:
        raise OSError(f"Falha ao gravar {out_image}")
    buf.tofile(str(out_image))
    meta = {
        "tile_zoom": job.zoom,
        "tile_origin_x": (job.x_min + job.leaflet_offset) * ts,
        "tile_origin_y": job.leaflet_origin_y,
        "template": job.template,
    }
    meta_path = out_image.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta_path


def parse_black_tiles(data: dict[str, object], zoom: int) -> frozenset[tuple[int, int]]:
    """Lê o black-tile.json do appsample: {"data": {"13": "x_y,x_y,..."}}."""
    raw = data.get("data", data)
    assert isinstance(raw, dict)
    text = str(raw.get(str(zoom), ""))
    out = set()
    for item in text.split(","):
        if "_" in item:
            x, y = item.split("_")  # "-1_-3" -> ("-1", "-3")
            out.add((int(x), int(y)))
    return frozenset(out)
