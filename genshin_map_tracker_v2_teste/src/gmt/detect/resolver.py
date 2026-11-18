"""Decide qual marcador foi coletado ou ativado quando o jogo mostra uma interação/coleta.

Regras:
1. Procura os marcadores ainda não coletados do tipo (ou cadeia de prioridade) perto
   da posição atual, ajustando o raio conforme o tipo de objeto.
2. Em cascata:
   - Se um contexto específico antecedeu o baú (ex.: "Escavar" -> `buried_chest`,
     "Desafio Concluído" -> `time_trial`, "Seelie" -> `seelie`, "Monetoo" -> `monetoo`),
     prioriza primeiro esse tipo de marcador;
   - Se a raridade exata do baú foi lida no aviso ("Baú Precioso" -> `chest_precious`,
     "Baú Estranho" -> `remarkable_chest`, "Santuário" -> `shrine`), prioriza esse
     subtipo para desempatar marcadores vizinhos antes de cair para `chest` geral;
   - Se o evento é `chest` e não há marcador `chest` pendente no raio, faz fallback
     automático para marcadores de `Baú de Enigma` (`puzzle_chest`), pois no appsample
     mais da metade dos baús do jogo ficam cadastrados apenas na categoria do enigma.
3. Marca sozinho apenas quando há um candidato claro e posição confiável; caso contrário,
   destaca/sugere no site para confirmação.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from gmt.data.catalog import CATALOG, GROUP_KINDS, PUZZLE_KINDS
from gmt.data.markers import CHEST_KIND, OCULUS_KINDS, Marker, MarkerStore

Decision = Literal["mark", "suggest", "none"]


@dataclass(frozen=True)
class ResolverConfig:
    radius: float  # raio de busca, em unidades do site
    clear_ratio: float = 1.8  # 2º mais perto precisa estar N vezes mais longe que o 1º...
    clear_gap: float = 0.2  # ...e pelo menos essa fração do raio mais longe
    min_confidence: float = 0.5  # confiança mínima da posição para marcar sozinho
    puzzle_fallback: bool = True  # tenta Baú de Enigma quando não há Baú comum no raio


@dataclass(frozen=True)
class Resolution:
    decision: Decision
    candidates: list[tuple[Marker, float]]  # (marcador, distância), mais perto primeiro
    reason: str
    matched_tier: str = ""

    @property
    def marker(self) -> Marker | None:
        return self.candidates[0][0] if self.candidates else None


def kinds_for_event(event_kind: str) -> tuple[str, ...]:
    """Traduz o tipo de evento ou grupo para a tupla de `kind`s correspondentes."""
    if event_kind == CHEST_KIND:
        return (CHEST_KIND,)
    if event_kind in GROUP_KINDS:
        return GROUP_KINDS[event_kind]
    if event_kind in OCULUS_KINDS or event_kind in CATALOG:
        return (event_kind,)
    raise ValueError(f"Tipo de coleta desconhecido: {event_kind}")


def priority_tiers_for_event(
    event_kind: str,
    subtype: str | None = None,
    context: str | None = None,
    puzzle_fallback: bool = True,
) -> list[tuple[str, ...]]:
    """Lista ordenada de grupos de tipos a procurar em cascata."""
    if event_kind != CHEST_KIND:
        base = kinds_for_event(event_kind)
        if event_kind in ("time_trial", "warrior_challenge", "seelie", "electro_seelie", "monetoo"):
            return [base, ("puzzle_chest",)]
        return [base]

    tiers: list[tuple[str, ...]] = []
    if context and context in CATALOG:
        tiers.append((context,))
    if subtype and subtype in CATALOG and subtype != CHEST_KIND:
        tiers.append((subtype,))
    tiers.append((CHEST_KIND,))
    if puzzle_fallback:
        tiers.append(PUZZLE_KINDS)
    return tiers


def decide(
    distances: list[float], cfg: ResolverConfig, position_confidence: float
) -> tuple[Decision, str]:
    """Regra comum: marcar só com candidato claro e posição confiável."""
    if not distances:
        return "none", "nenhum marcador pendente desse tipo por perto"
    if position_confidence < cfg.min_confidence:
        return "suggest", f"posição incerta ({position_confidence:.2f})"
    if len(distances) == 1:
        return "mark", "único candidato no raio"
    d1, d2 = distances[0], distances[1]
    if d2 >= d1 * cfg.clear_ratio and d2 - d1 >= cfg.clear_gap * cfg.radius:
        return "mark", f"mais perto com folga ({d1:.1f} vs {d2:.1f})"
    return "suggest", f"candidatos parecidos ({d1:.1f} vs {d2:.1f})"


def resolve(
    store: MarkerStore,
    cfg: ResolverConfig,
    event_kind: str,
    layer: str,
    x: float,
    y: float,
    position_confidence: float,
    *,
    subtype: str | None = None,
    context: str | None = None,
) -> Resolution:
    tiers = priority_tiers_for_event(
        event_kind, subtype=subtype, context=context, puzzle_fallback=cfg.puzzle_fallback
    )
    last_reason = "nenhum marcador pendente desse tipo por perto"
    for tier in tiers:
        cands = store.nearby(layer, x, y, cfg.radius, kinds=tier)
        if not cands:
            continue
        decision, reason = decide([d for _, d in cands], cfg, position_confidence)
        last_reason = reason
        # Se o subtipo específico achou candidato único/claro, ou se chegamos ao tier principal:
        keep = 1 if decision == "mark" else 3
        return Resolution(decision, cands[:keep], reason, matched_tier=tier[0])
    return Resolution("none", [], last_reason)
