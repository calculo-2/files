"""Localização do jogador no mapa a partir do minimapa.

Duas etapas:
- Busca global: pontos SIFT do minimapa comparados com o mapa inteiro (FLANN +
  RANSAC com transformação de similaridade). Usada no início, quando a posição
  se perde e depois de teleportes.
- Busca local: correlação do minimapa (na escala do mapa) numa janela em volta da
  posição prevista. Rápida e precisa enquanto o jogador anda.

O minimapa do Genshin fica sempre com o norte para cima, então a rotação esperada
é zero; a escala (pixels do mapa por pixel do minimapa) é aprendida nas buscas
globais e depois fica fixa.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from gmt.localization.mapindex import MapIndex, make_detector, to_gray
from gmt.localization.tracking import KalmanFilter2D
from gmt.vision.minimap import Minimap

log = logging.getLogger(__name__)

FixMethod = Literal["global", "local", "predicted", "lost"]


@dataclass(frozen=True)
class LocalizerConfig:
    ratio: float = 0.85  # teste de razão de Lowe (tolerante: a correlação confirma depois)
    min_inliers: int = 6  # pontos coerentes mínimos (com rotação ~0 e escala coerente)
    upsample: float = 2.0  # amplia o minimapa antes do SIFT: imagem pequena gera poucos pontos
    max_rotation_deg: float = 8.0  # minimapa é norte-para-cima; rotação maior = erro
    first_fix_min_inliers: int = 6  # enquanto a escala não foi aprendida
    scale: float | None = None  # px do mapa por px do minimapa; None = aprender
    min_scale: float = 0.2  # limites plausíveis da escala
    max_scale: float = 20.0
    scale_tolerance: float = 0.2  # desvio aceito em relação à escala aprendida
    local_min_score: float = 0.5  # correlação mínima da busca local
    local_template_radius: float = 80.0  # raio do minimapa (px) usado na correlação
    base_margin: float = 0.25  # folga da janela local, em raios do minimapa
    max_speed: float = 1.0  # deslocamento máximo, em raios do minimapa por segundo
    max_dt: float = 2.0  # acima disso (s), trata como sem rastreio recente
    teleport_confirmations: int = 2  # buscas globais seguidas no novo lugar para aceitar salto
    lost_after: int = 5  # falhas seguidas até declarar "posição perdida"
    wide_margin: float = 4.0  # busca ampla em volta da última posição, em raios do minimapa
    recall_time: float = 120.0  # s: por quanto tempo a última posição ajuda a reencontrar
    global_interval: float = 0.5  # s: intervalo mínimo entre buscas no mapa inteiro (CPU)


@dataclass(frozen=True)
class Fix:
    """Resultado de um quadro. Coordenadas em pixels do mapa da camada `layer`."""

    method: FixMethod
    confidence: float  # 0 a 1
    x: float | None = None  # posição suavizada
    y: float | None = None
    raw: tuple[float, float] | None = None  # medição deste quadro, antes da suavização
    layer: str | None = None
    scale: float | None = None

    @property
    def ok(self) -> bool:
        return self.method != "lost" and self.x is not None


@dataclass
class _Match:
    layer: str
    x: float
    y: float
    scale: float
    confidence: float
    inliers: int = 0


@dataclass
class _State:
    layer: str | None = None
    misses: int = 0
    pending: list[_Match] = field(default_factory=list)
    last_t: float | None = None
    last_known: tuple[str, float, float, float] | None = None  # camada, x, y, instante
    last_global_t: float = -1e9


class Localizer:
    def __init__(self, maps: Sequence[MapIndex], config: LocalizerConfig | None = None) -> None:
        if not maps:
            raise ValueError("Informe ao menos um mapa.")
        self.config = config or LocalizerConfig()
        self.maps = {m.name: m for m in maps}
        self._sift = make_detector(nfeatures=1000)
        self._matchers: dict[str, cv2.FlannBasedMatcher] = {}
        self._scales: deque[float] = deque(maxlen=25)
        self._kf = KalmanFilter2D()
        self._state = _State()

    # ------------------------------------------------------------------ API

    @property
    def scale(self) -> float | None:
        if self.config.scale is not None:
            return self.config.scale
        return float(np.median(self._scales)) if self._scales else None

    def reset(self) -> None:
        """Esquece a posição (ex.: depois de pausar). A escala aprendida é mantida."""
        self._kf = KalmanFilter2D()
        self._state = _State()

    def update(self, minimap: Minimap, t: float) -> Fix:
        gray = to_gray(minimap.image)
        st = self._state
        tracking = self._is_tracking(t)

        if tracking:
            local = self._match_local(gray, minimap, t)
            if local is not None:
                return self._accept(local, t, "local")

        # Antes do mapa inteiro: busca ampla em volta da última posição conhecida.
        # Resolve a maioria das falhas curtas (minimapa coberto ou borrado por um instante).
        near = self._match_near_last(gray, minimap, t)
        if near is not None:
            return self._accept(near, t, "local", reset=not tracking)

        if t - st.last_global_t < self.config.global_interval:
            return self._miss(t)
        st.last_global_t = t
        found = self._match_global(gray, minimap)
        if found is not None:
            radius_map = minimap.circle.r * (self.scale or found.scale)
            if not tracking:
                return self._accept(found, t, "global", reset=True)
            if found.layer == st.layer and self._within_gate(found, t, radius_map):
                return self._accept(found, t, "global")
            if self._confirm_jump(found, radius_map):
                log.info("Salto confirmado para %s (%.0f, %.0f).", found.layer, found.x, found.y)
                return self._accept(found, t, "global", reset=True)
            log.debug("Salto improvável descartado: %s", found)

        return self._miss(t)

    # ------------------------------------------------------------ internals

    def _is_tracking(self, t: float) -> bool:
        st = self._state
        return (
            st.layer is not None
            and self._kf.initialized
            and st.last_t is not None
            and t - st.last_t <= self.config.max_dt
            and self.scale is not None
        )

    def _footprint(self, minimap: Minimap) -> float:
        """Raio do minimapa em pixels do mapa."""
        scale = self.scale
        assert scale is not None
        return minimap.circle.r * scale

    def _allowed_distance(self, radius_map: float, t: float) -> float:
        st = self._state
        dt = 0.0 if st.last_t is None else min(max(t - st.last_t, 0.0), self.config.max_dt)
        return radius_map * (self.config.base_margin + self.config.max_speed * dt)

    def _within_gate(self, m: _Match, t: float, radius_map: float) -> bool:
        px, py = self._kf.predict(t)
        return math.hypot(m.x - px, m.y - py) <= self._allowed_distance(radius_map, t)

    def _confirm_jump(self, m: _Match, radius_map: float) -> bool:
        """Aceita um salto (teleporte, troca de camada) só se ele se repetir."""
        st = self._state
        tol = radius_map * 0.5
        if st.pending and st.pending[-1].layer == m.layer:
            last = st.pending[-1]
            if math.hypot(m.x - last.x, m.y - last.y) <= tol:
                st.pending.append(m)
            else:
                st.pending = [m]
        else:
            st.pending = [m]
        return len(st.pending) >= self.config.teleport_confirmations

    def _accept(self, m: _Match, t: float, method: FixMethod, reset: bool = False) -> Fix:
        st = self._state
        if reset or st.layer != m.layer:
            self._kf = KalmanFilter2D()
        x, y = self._kf.update(m.x, m.y, t, m.confidence)
        st.layer, st.misses, st.pending, st.last_t = m.layer, 0, [], t
        st.last_known = (m.layer, x, y, t)
        if method == "global" and self.config.scale is None:
            self._scales.append(m.scale)
        return Fix(method, m.confidence, x, y, (m.x, m.y), m.layer, self.scale)

    def _miss(self, t: float) -> Fix:
        st = self._state
        st.misses += 1
        if self._kf.initialized and st.misses < self.config.lost_after and st.layer is not None:
            x, y = self._kf.predict(t)
            conf = max(0.0, 0.5 - 0.1 * st.misses)
            return Fix("predicted", conf, x, y, None, st.layer, self.scale)
        if st.misses == self.config.lost_after:
            log.info("Posição perdida.")
        self._kf = KalmanFilter2D()
        st.last_t = None
        return Fix("lost", 0.0, layer=st.layer, scale=self.scale)

    # ---- busca local

    def _match_near_last(
        self, gray: NDArray[np.uint8], minimap: Minimap, t: float
    ) -> _Match | None:
        st, scale = self._state, self.scale
        if st.last_known is None or scale is None:
            return None
        layer, x, y, when = st.last_known
        if t - when > self.config.recall_time:
            return None
        if self._kf.initialized:
            x, y = self._kf.predict(t)
        radius_map = minimap.circle.r * scale
        # Só até onde dá para ter andado desde a última posição: saltos maiores
        # (teleporte) continuam passando pela confirmação da busca global.
        reach = radius_map * (self.config.base_margin + self.config.max_speed * (t - when))
        margin = min(radius_map * self.config.wide_margin, reach)
        return self._correlate(gray, minimap, layer, x, y, scale, margin)

    def _match_local(self, gray: NDArray[np.uint8], minimap: Minimap, t: float) -> _Match | None:
        st = self._state
        scale = self.scale
        assert st.layer is not None and scale is not None
        px, py = self._kf.predict(t)
        radius_map = minimap.circle.r * scale
        margin = self._allowed_distance(radius_map, t)
        return self._correlate(gray, minimap, st.layer, px, py, scale, margin)

    def _correlate(
        self,
        gray: NDArray[np.uint8],
        minimap: Minimap,
        layer: str,
        cx: float,
        cy: float,
        scale: float,
        margin: float,
    ) -> _Match | None:
        """Procura o minimapa (na escala do mapa) numa janela de ±margin em volta de (cx, cy)."""
        index = self.maps[layer]
        radius_map = minimap.circle.r * scale
        if radius_map <= 0:
            return None

        # Trabalha numa resolução reduzida: raio do modelo ~ local_template_radius.
        f = min(1.0, self.config.local_template_radius / radius_map)
        half = radius_map + margin
        w, h = index.size
        x0, y0 = max(int(cx - half), 0), max(int(cy - half), 0)
        x1, y1 = min(int(cx + half) + 1, w), min(int(cy + half) + 1, h)
        if x1 <= x0 or y1 <= y0:
            return None
        window = index.gray[y0:y1, x0:x1]
        win_s = cv2.resize(window, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)

        size = max(3, int(round(gray.shape[1] * scale * f)))
        templ = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
        mask = cv2.resize(minimap.mask, (size, size), interpolation=cv2.INTER_NEAREST)
        if win_s.shape[0] < size or win_s.shape[1] < size or cv2.countNonZero(mask) < 10:
            return None

        raw = cv2.matchTemplate(win_s, templ, cv2.TM_CCOEFF_NORMED, mask=mask)
        res: NDArray[np.float32] = np.nan_to_num(raw, nan=-1.0, posinf=-1.0, neginf=-1.0).astype(
            np.float32
        )
        _, score, _, (bx, by) = cv2.minMaxLoc(res)
        if score < self.config.local_min_score:
            log.debug("Correlação fraca: %.2f", score)
            return None
        sx, sy = _subpixel(res, bx, by)
        center = (size - 1) / 2.0
        # Converte centro de pixel da janela reduzida para o mapa: (i + 0.5) / f - 0.5.
        mx = x0 + (sx + center + 0.5) / f - 0.5
        my = y0 + (sy + center + 0.5) / f - 0.5
        return _Match(layer, mx, my, scale, float(min(1.0, score)))

    # ---- busca global

    def _matcher(self, index: MapIndex) -> cv2.FlannBasedMatcher:
        m = self._matchers.get(index.name)
        if m is None:
            m = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 4}, {"checks": 64})
            m.add([index.descriptors])
            m.train()
            self._matchers[index.name] = m
        return m

    def _match_global(self, gray: NDArray[np.uint8], minimap: Minimap) -> _Match | None:
        cfg = self.config
        up = cfg.upsample
        big = cv2.resize(gray, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
        big_mask = cv2.resize(
            minimap.mask, (big.shape[1], big.shape[0]), interpolation=cv2.INTER_NEAREST
        )
        kps, desc = self._sift.detectAndCompute(big, big_mask)
        if desc is None or len(kps) < cfg.min_inliers:
            return None
        src_all = np.array([k.pt for k in kps], dtype=np.float32) / up
        center = np.array([minimap.circle.cx, minimap.circle.cy, 1.0])

        order = sorted(self.maps, key=lambda n: n != self._state.layer)
        best: _Match | None = None
        for name in order:
            index = self.maps[name]
            if len(index.descriptors) < 2:
                continue
            pairs = self._matcher(index).knnMatch(desc.astype(np.float32), k=2)
            good = [
                p[0] for p in pairs if len(p) == 2 and p[0].distance < cfg.ratio * p[1].distance
            ]
            if len(good) < cfg.min_inliers:
                continue
            src = src_all[[g.queryIdx for g in good]]
            dst = index.points[[g.trainIdx for g in good]]
            m, inl = cv2.estimateAffinePartial2D(
                src, dst, method=cv2.RANSAC, ransacReprojThreshold=6.0, maxIters=2000
            )
            if m is None or inl is None:
                continue
            inl_mask = inl.ravel().astype(bool)
            # Conta pontos distintos dos dois lados: vários pontos do minimapa caindo
            # no mesmo ponto do mapa é sinal de transformação degenerada.
            n_inl = min(
                len(np.unique(np.round(src[inl_mask]), axis=0)),
                len(np.unique(np.round(dst[inl_mask]), axis=0)),
            )
            scale = float(math.hypot(m[0, 0], m[1, 0]))
            rot = math.degrees(math.atan2(m[1, 0], m[0, 0]))
            known = self.scale
            needed = cfg.min_inliers if known is not None else cfg.first_fix_min_inliers
            if n_inl < needed or abs(rot) > cfg.max_rotation_deg:
                continue
            if not cfg.min_scale <= scale <= cfg.max_scale:
                continue
            if known is not None and abs(scale / known - 1.0) > cfg.scale_tolerance:
                continue
            x, y = (m @ center).tolist()
            # Confirma com uma correlação independente na posição encontrada; ela também
            # refina a posição. Evita aceitar coincidências de pontos característicos.
            radius_map = minimap.circle.r * scale
            check = self._correlate(gray, minimap, name, x, y, scale, 0.1 * radius_map + 4)
            if check is None:
                log.debug("Busca global em %s não confirmada pela correlação.", name)
                continue
            conf = min(1.0, n_inl / (3.0 * cfg.min_inliers)) * math.sqrt(n_inl / len(good))
            conf = min(conf, check.confidence)
            cand = _Match(name, check.x, check.y, scale, float(conf), n_inl)
            if best is None or cand.inliers > best.inliers:
                best = cand
        return best


def _subpixel(res: NDArray[np.float32], x: int, y: int) -> tuple[float, float]:
    """Refina o pico da correlação com uma parábola em cada eixo."""

    def refine(a: float, b: float, c: float) -> float:
        d = a - 2 * b + c
        return 0.0 if abs(d) < 1e-9 else float(np.clip(0.5 * (a - c) / d, -0.5, 0.5))

    h, w = res.shape
    dx = refine(res[y, x - 1], res[y, x], res[y, x + 1]) if 0 < x < w - 1 else 0.0
    dy = refine(res[y - 1, x], res[y, x], res[y + 1, x]) if 0 < y < h - 1 else 0.0
    return x + dx, y + dy
