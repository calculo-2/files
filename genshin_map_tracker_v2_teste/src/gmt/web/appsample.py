"""Conhecimento específico do appsample (PT-BR e Inglês, todas as categorias interativas).

Categorias: cada tipo de marcador tem um id ("o17", "o5", "o3"...) que aparece no
ícone (.../gim/markers/o17.png) e no botão de filtro da barra lateral. O app lê esse
mapeamento da própria página ao abrir (por título/rótulo do botão em PT-BR ou EN);
`DEFAULT_TYPE_IDS` funciona como reserva caso a barra lateral não esteja carregada.
"""

from __future__ import annotations

import re
import unicodedata

from gmt.data.catalog import ALL_SPECS

# tipo interno -> títulos aceitos nos botões e cartões do site (PT-BR + Inglês)
KIND_NAMES: dict[str, tuple[str, ...]] = {
    spec.kind: spec.all_site_titles for spec in ALL_SPECS if spec.all_site_titles
}

# Reserva: ids conhecidos do appsample caso a leitura dinâmica da barra lateral falhe.
DEFAULT_TYPE_IDS: dict[str, tuple[str, ...]] = {
    spec.kind: spec.default_type_ids for spec in ALL_SPECS
}

# Lê da barra lateral todos os botões com ícone de marcador (/markers/oNN.png|.webp),
# extraindo `title`, `aria-label`, `img.alt` ou o texto limpo do botão (sem o contador numérico).
CATEGORY_JS = r"""
() => {
  const seen = new Set();
  const out = [];
  for (const b of document.querySelectorAll('button, [role="button"]')) {
    const img = b.querySelector('img[src*="/markers/"]');
    const m = img && img.src.match(/\/markers\/([a-z]?\d+)\.(?:png|webp)/i);
    if (!m) continue;
    const raw = (
      b.getAttribute('title') ||
      b.getAttribute('aria-label') ||
      (img && img.getAttribute('alt')) ||
      b.innerText ||
      ''
    ).replace(/\d+\s*$/, '').trim();
    if (!raw) continue;
    const key = raw.toLowerCase() + '|' + m[1];
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({title: raw, type: m[1]});
  }
  return out;
}
"""


def _norm_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", text).strip()


def _title_matches(button_title: str, expected: str) -> bool:
    """Casa título exato ou prefixo com fronteira de palavra (ex.: 'Santuário das Profundezas de Liyue',
    'Padrão de Chave II', 'Local de Ancoragem do Quebra-mar (Não é possível teleportar)')."""
    bt = _norm_title(button_title)
    ex = _norm_title(expected)
    if not bt or not ex:
        return False
    if bt == ex:
        return True
    # "Mora" não pode casar com "Morango", mas "Santuário das Profundezas" casa com "... de Mondstadt"
    # e "Padrão de Chave" casa com "Padrão de Chave IV".
    if ex == "mora":
        return False
    return bt.startswith(ex + " ") or bt.startswith(ex + "(")


def type_ids_from_buttons(buttons: list[dict[str, str]]) -> dict[str, tuple[str, ...]]:
    """Monta {tipo interno: ids do site} a partir dos botões lidos da página."""
    entries: list[tuple[str, str]] = [
        (b["title"].strip(), b["type"]) for b in buttons if b.get("title") and b.get("type")
    ]
    out: dict[str, tuple[str, ...]] = {}
    for kind, names in KIND_NAMES.items():
        matched: list[str] = []
        for title, type_id in entries:
            if type_id not in matched and any(_title_matches(title, n) for n in names):
                matched.append(type_id)
        out[kind] = tuple(matched) if matched else DEFAULT_TYPE_IDS.get(kind, ())
    return out
