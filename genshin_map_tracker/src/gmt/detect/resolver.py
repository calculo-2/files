"""Decide qual marcador foi coletado quando o jogo mostra uma coleta.

Regra: pega os marcadores ainda não coletados do tipo certo perto da posição
atual. Marca sozinho só quando há um candidato claro; se houver dois parecidos,
ou a posição estiver com pouca confiança, apenas sugere, para o usuário
confirmar no site. Nunca marca sem nenhum candidato.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from gmt.data.markers import CHEST_KIND, OCULUS_KINDS, Marker, MarkerStore

Decision = Literal["mark", "suggest", "none"]


@dataclass(frozen=True)
class ResolverConfig:
    radius: float  # raio de busca, em unidades do site
    clear_ratio: float = 1.8  # 2º mais perto precisa estar N vezes mais longe que o 1º...
    clear_gap: float = 0.2  # ...e pelo menos essa fração do raio mais longe
    min_confidence: float = 0.5  # confiança mínima da posição para marcar sozinho


@dataclass(frozen=True)
class Resolution:
    decision: Decision
    candidates: list[tuple[Marker, float]]  # (marcador, distância), mais perto primeiro
    reason: str

    @property
    def marker(self) -> Marker | None:
        return self.candidates[0][0] if self.candidates else None


def kinds_for_event(event_kind: str) -> tuple[str, ...]:
    """'chest' -> ('chest',); 'oculus' (tipo desconhecido) -> todos os oculi."""
    if event_kind == "oculus":
        return OCULUS_KINDS
    if event_kind == CHEST_KIND or event_kind in OCULUS_KINDS:
        return (event_kind,)
    raise ValueError(f"Tipo de coleta desconhecido: {event_kind}")


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
) -> Resolution:
    cands = store.nearby(layer, x, y, cfg.radius, kinds=kinds_for_event(event_kind))
    decision, reason = decide([d for _, d in cands], cfg, position_confidence)
    keep = 1 if decision == "mark" else 3
    return Resolution(decision, cands[:keep], reason)
