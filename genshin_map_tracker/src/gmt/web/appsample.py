"""Conhecimento específico do appsample (lido do site em 07/11/2026).

Categorias: cada tipo de marcador tem um id ("o17") que aparece no ícone
(.../gim/markers/o17.png) e no botão de filtro da barra lateral. O app lê esse
mapeamento da própria página ao abrir (por nome do botão); a tabela abaixo é só
a reserva, caso a leitura falhe.
"""

from __future__ import annotations

# tipo interno -> nomes dos botões no site (PT-BR)
KIND_NAMES: dict[str, tuple[str, ...]] = {
    "chest": ("Baú Comum", "Baú Sofisticado", "Baú Precioso", "Baú Luxuoso", "Baú Estranho"),
    "anemoculus": ("Anemoculus",),
    "geoculus": ("Geoculus",),
    "electroculus": ("Electroculus",),
    "dendroculus": ("Dendroculus",),
    "hydroculus": ("Hydroculus",),
    "pyroculus": ("Pyroculus",),
    "cryoculus": ("Cryoculus",),
    "lunoculus": ("Lunoculus",),
}

# Reserva: ids vistos no site em 07/11/2026.
DEFAULT_TYPE_IDS: dict[str, tuple[str, ...]] = {
    "chest": ("o17", "o44", "o45", "o46", "o269"),
    "anemoculus": ("o5",),
    "geoculus": ("o6",),
    "electroculus": ("o194",),
    "dendroculus": ("o403",),
    "hydroculus": ("o508",),
    "pyroculus": ("o626",),
    "cryoculus": ("o833",),
    "lunoculus": ("o694",),
}

# Lê da barra lateral: [{title, type}] a partir de <button title="..."><img src=".../oNN.png">.
CATEGORY_JS = r"""
() => Array.from(document.querySelectorAll('button[title]')).map(b => {
  const img = b.querySelector('img[src*="/markers/"]');
  const m = img && img.src.match(/\/markers\/([a-z]?\d+)\.(?:png|webp)/);
  return m ? {title: b.title, type: m[1]} : null;
}).filter(Boolean)
"""


def type_ids_from_buttons(buttons: list[dict[str, str]]) -> dict[str, tuple[str, ...]]:
    """Monta {tipo interno: ids do site} a partir dos botões lidos da página."""
    by_title = {b["title"].strip().lower(): b["type"] for b in buttons}
    out: dict[str, tuple[str, ...]] = {}
    for kind, names in KIND_NAMES.items():
        ids = tuple(by_title[n.lower()] for n in names if n.lower() in by_title)
        out[kind] = ids or DEFAULT_TYPE_IDS[kind]
    return out
