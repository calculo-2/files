"""Conversão entre pixels do mapa base e coordenadas do site do mapa.

Se o mapa base for montado com os blocos do próprio site, a conversão é exata e
vem do próprio Leaflet (ver gmt.web.browser). Para qualquer outro mapa base, use
uma calibração por pontos de referência: pares (pixel no mapa base, coordenada no
site) medidos em Pontos de Teletransporte. Com 2 pontos dá para ajustar
translação + escala (+ rotação); com 3 ou mais, uma transformação afim completa,
e o erro de cada ponto mostra se algum par foi medido errado.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

Model = Literal["similarity", "affine"]


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class RefPoint:
    name: str
    map_xy: tuple[float, float]  # pixel no mapa base
    site_xy: tuple[float, float]  # coordenada no site (ex.: lng, lat do Leaflet)


@dataclass
class Calibration:
    layer: str
    points: list[RefPoint] = field(default_factory=list)
    model: Model = "similarity"
    matrix: NDArray[np.float64] | None = None  # 2x3: site = M @ [x, y, 1]

    # ------------------------------------------------------------- ajuste

    def fit(self) -> list[float]:
        """Ajusta a transformação e retorna o erro (no site) de cada ponto."""
        n = len(self.points)
        need = 3 if self.model == "affine" else 2
        if n < need:
            raise CalibrationError(f"Modelo {self.model} precisa de {need} pontos (tem {n}).")
        src = np.array([p.map_xy for p in self.points], dtype=np.float64)
        dst = np.array([p.site_xy for p in self.points], dtype=np.float64)
        self.matrix = _fit_affine(src, dst) if self.model == "affine" else _fit_similarity(src, dst)
        return self.residuals()

    def residuals(self) -> list[float]:
        m = self._require()
        out = []
        for p in self.points:
            sx, sy = _apply(m, p.map_xy)
            out.append(math.hypot(sx - p.site_xy[0], sy - p.site_xy[1]))
        return out

    # --------------------------------------------------------- conversão

    def to_site(self, x: float, y: float) -> tuple[float, float]:
        return _apply(self._require(), (x, y))

    def to_map(self, sx: float, sy: float) -> tuple[float, float]:
        m = self._require()
        full = np.vstack([m, [0.0, 0.0, 1.0]])
        inv = np.linalg.inv(full)[:2]
        return _apply(inv, (sx, sy))

    @property
    def scale(self) -> float:
        """Unidades do site por pixel do mapa base (média dos eixos)."""
        m = self._require()
        return float(math.sqrt(abs(np.linalg.det(m[:, :2]))))

    def _require(self) -> NDArray[np.float64]:
        if self.matrix is None:
            raise CalibrationError("Calibração ainda não ajustada (chame fit()).")
        return self.matrix

    # ----------------------------------------------------------- arquivo

    def save(self, path: Path) -> None:
        data = {
            "layer": self.layer,
            "model": self.model,
            "points": [
                {"name": p.name, "map": list(p.map_xy), "site": list(p.site_xy)}
                for p in self.points
            ],
            "matrix": None if self.matrix is None else self.matrix.tolist(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Calibration:
        data = json.loads(path.read_text(encoding="utf-8"))
        cal = cls(
            layer=data["layer"],
            model=data.get("model", "similarity"),
            points=[
                RefPoint(p["name"], tuple(p["map"]), tuple(p["site"]))
                for p in data.get("points", [])
            ],
        )
        if data.get("matrix") is not None:
            cal.matrix = np.array(data["matrix"], dtype=np.float64)
        elif len(cal.points) >= 2:
            cal.fit()
        return cal


def _apply(m: NDArray[np.float64], xy: tuple[float, float]) -> tuple[float, float]:
    v = m @ np.array([xy[0], xy[1], 1.0])
    return float(v[0]), float(v[1])


def _fit_affine(src: NDArray[np.float64], dst: NDArray[np.float64]) -> NDArray[np.float64]:
    a = np.hstack([src, np.ones((len(src), 1))])
    sol, *_ = np.linalg.lstsq(a, dst, rcond=None)
    return np.asarray(sol.T, dtype=np.float64)


def _fit_similarity(src: NDArray[np.float64], dst: NDArray[np.float64]) -> NDArray[np.float64]:
    """Escala uniforme + rotação + translação, com eixos que podem ser espelhados.

    O eixo Y de imagens cresce para baixo e o do Leaflet (lat) cresce para cima, então
    testamos as duas orientações e ficamos com a de menor erro.
    """
    best: tuple[float, NDArray[np.float64]] | None = None
    for flip in (1.0, -1.0):
        s = src * np.array([1.0, flip])
        # Umeyama simplificado via mínimos quadrados: [a -b; b a] * s + t
        rows, rhs = [], []
        for (x, y), (u, v) in zip(s, dst, strict=True):
            rows.append([x, -y, 1, 0])
            rows.append([y, x, 0, 1])
            rhs.extend([u, v])
        (a, b, tx, ty), *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
        m = np.array([[a, -b * flip, tx], [b, a * flip, ty]], dtype=np.float64)
        err = float(
            sum(
                math.hypot(*(np.array(_apply(m, tuple(p))) - q))
                for p, q in zip(src, dst, strict=True)
            )
        )
        if best is None or err < best[0]:
            best = (err, m)
    assert best is not None
    return best[1]
