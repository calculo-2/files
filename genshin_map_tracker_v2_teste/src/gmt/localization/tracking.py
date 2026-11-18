"""Suavização da posição: filtro de Kalman 2D de velocidade constante."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


@dataclass
class KalmanFilter2D:
    """Estado [x, y, vx, vy]. Ruído de medição menor quando a confiança é alta."""

    process_noise: float = 15.0  # aceleração esperada (px/s²)
    base_measurement_noise: float = 4.0  # px, com confiança 1.0
    x: NDArray[np.float64] = field(default_factory=lambda: np.zeros(4))
    p: NDArray[np.float64] = field(default_factory=lambda: np.eye(4) * 1e6)
    t: float | None = None

    @property
    def initialized(self) -> bool:
        return self.t is not None

    def reset(self, x: float, y: float, t: float) -> None:
        self.x = np.array([x, y, 0.0, 0.0])
        self.p = np.diag([25.0, 25.0, 1e4, 1e4])
        self.t = t

    def predict(self, t: float) -> tuple[float, float]:
        """Posição prevista em `t`, sem alterar o estado."""
        if self.t is None:
            raise RuntimeError("Filtro não inicializado.")
        dt = max(t - self.t, 0.0)
        return float(self.x[0] + self.x[2] * dt), float(self.x[1] + self.x[3] * dt)

    def update(self, x: float, y: float, t: float, confidence: float = 1.0) -> tuple[float, float]:
        if self.t is None:
            self.reset(x, y, t)
            return x, y
        dt = max(t - self.t, 1e-3)
        f = np.eye(4)
        f[0, 2] = f[1, 3] = dt
        q = self.process_noise**2
        g = np.array([[dt**2 / 2, 0], [0, dt**2 / 2], [dt, 0], [0, dt]])
        self.x = f @ self.x
        self.p = f @ self.p @ f.T + g @ g.T * q

        h = np.zeros((2, 4))
        h[0, 0] = h[1, 1] = 1.0
        sigma = self.base_measurement_noise / max(confidence, 0.05)
        r = np.eye(2) * sigma**2
        innovation = np.array([x, y]) - h @ self.x
        s = h @ self.p @ h.T + r
        k = self.p @ h.T @ np.linalg.inv(s)
        self.x = self.x + k @ innovation
        self.p = (np.eye(4) - k @ h) @ self.p
        self.t = t
        return float(self.x[0]), float(self.x[1])
