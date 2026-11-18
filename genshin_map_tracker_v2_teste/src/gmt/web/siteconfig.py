"""Lê a configuração do mapa (tiles, zoom, limites) direto da página do appsample.

A página (Next.js) traz no próprio HTML um JSON com a lista de mapas. O mapa da
página aberta vem completo: molde de URL dos tiles, tamanho, zoom, limites por
zoom e o endereço da lista de tiles vazios. Assim o gmt acompanha as atualizações
do site sozinho (a versão dos tiles muda a cada versão do jogo).

Medido no site em 07/11/2026: tiles "centered" com y crescendo para cima e índice
Leaflet = índice do site + 2**(zoom-1) em x; y_leaflet = 2**(zoom-1) - 1 - y_site.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any

USER_AGENT = "Mozilla/5.0 (gmt; uso pessoal)"
SITE = "https://genshin-impact-map.appsample.com"
# Chave do mapa -> caminho da página (o Teyvat é a página principal).
MAP_PATHS = {
    "teyvat": "",
    "enkanomiya": "enkanomiya/",
    "chasm": "chasm/",
    "sea-of-bygone-eras": "sea-of-bygone-eras/",
    "ancient_sacred_mountain": "ancient_sacred_mountain/",
    "temple_of_space": "temple_of_space/",
    "frost_moon": "frost_moon/",
}


class SiteConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SiteMap:
    key: str
    url_template: str
    tile_size: int
    min_zoom: int
    max_zoom: int
    tile_bounds: dict[int, tuple[int, int, int, int]]  # zoom -> (min_x, max_x, min_y, max_y)
    black_tiles_url: str | None
    centered: bool  # tiles "centered": y para cima, origem no centro

    def leaflet_offset(self, zoom: int) -> int:
        return 2 ** (zoom - 1) if self.centered else 0


def page_url(key: str, lang: str = "pt") -> str:
    if key not in MAP_PATHS:
        raise SiteConfigError(f"Mapa desconhecido: {key}. Opções: {', '.join(MAP_PATHS)}")
    return f"{SITE}/{lang}/{MAP_PATHS[key]}"


def fetch_text(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data: bytes = resp.read()
    return data.decode("utf-8", errors="replace")


def _payload_texts(html: str) -> list[str]:
    """Conteúdo dos blocos self.__next_f.push([1, "..."]) já desescapado."""
    out = []
    for raw in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S):
        try:
            out.append(json.loads(f'"{raw}"'))
        except json.JSONDecodeError:
            continue
    return out


def _balanced(text: str, start: int) -> str:
    """Trecho JSON começando em `start` ('[' ou '{') até o fechamento correspondente."""
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise SiteConfigError("JSON incompleto na página.")


def _url_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.startswith("http") else None


def _to_site_map(m: dict[str, Any]) -> SiteMap | None:
    tiles = m.get("tiles")
    if not isinstance(tiles, dict) or "urlTemplate" not in tiles:
        return None
    raw_bounds = tiles.get("tileBounds")
    if not isinstance(raw_bounds, dict):  # referência a outro bloco da página: mapa incompleto
        return None
    bounds = {
        int(z): (int(b["minX"]), int(b["maxX"]), int(b["minY"]), int(b["maxY"]))
        for z, b in raw_bounds.items()
        if isinstance(b, dict)
    }
    return SiteMap(
        key=str(m.get("key", "")),
        url_template=str(tiles["urlTemplate"]),
        tile_size=int(tiles.get("tileSize", 256)),
        min_zoom=int(tiles.get("minZoom", 0)),
        max_zoom=int(tiles.get("maxZoom", 0)),
        tile_bounds=bounds,
        black_tiles_url=_url_or_none(tiles.get("blackTilesUrl")),
        centered=tiles.get("type") == "centered",
    )


def parse_site_maps(html: str) -> list[SiteMap]:
    """Mapas com configuração de tiles encontrados na página."""
    found: list[SiteMap] = []
    for text in _payload_texts(html):
        pos = text.find('"maps":[')
        if pos < 0:
            continue
        maps = json.loads(_balanced(text, pos + len('"maps":')))
        for m in maps:
            if isinstance(m, dict) and (sm := _to_site_map(m)) is not None:
                found.append(sm)
    if not found:
        raise SiteConfigError("Configuração do mapa não encontrada na página (o site mudou?).")
    return found
