"""Mapa base de uma camada (Teyvat, subterrâneo etc.) com pontos característicos pré-calculados.

O mapa grande é processado em blocos para não estourar memória. O resultado fica
num arquivo .npz ao lado da imagem e é reaproveitado nas próximas execuções.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

log = logging.getLogger(__name__)

Gray = NDArray[np.uint8]

INDEX_VERSION = 2
TILE = 2048
TILE_OVERLAP = 64


def make_detector(nfeatures: int = 0) -> Any:
    # SIFT: invariante a escala e brilho; o minimapa e o mapa têm a mesma arte.
    return cv2.SIFT_create(nfeatures=nfeatures, contrastThreshold=0.01)  # type: ignore[attr-defined]


def to_gray(img: NDArray[np.uint8]) -> Gray:
    if img.ndim == 2:
        return img
    code = cv2.COLOR_BGRA2GRAY if img.shape[2] == 4 else cv2.COLOR_BGR2GRAY
    return np.asarray(cv2.cvtColor(img, code), np.uint8)


def detect_tiled(
    gray: Gray, tile: int = TILE, overlap: int = TILE_OVERLAP
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Detecta pontos SIFT bloco a bloco. Retorna (pontos Nx2, descritores Nx128)."""
    sift = make_detector()
    h, w = gray.shape
    pts: list[NDArray[np.float32]] = []
    descs: list[NDArray[np.float32]] = []
    for y0 in range(0, h, tile):
        for x0 in range(0, w, tile):
            ya, xa = max(y0 - overlap, 0), max(x0 - overlap, 0)
            yb, xb = min(y0 + tile + overlap, h), min(x0 + tile + overlap, w)
            block = gray[ya:yb, xa:xb]
            if float(block.std()) < 2.0:  # bloco vazio (fora do mapa)
                continue
            kps, d = sift.detectAndCompute(block, None)
            if d is None or not kps:
                continue
            xy = np.array([k.pt for k in kps], dtype=np.float32) + (xa, ya)
            # Guarda só os pontos do miolo do bloco, para não duplicar na sobreposição.
            keep = (
                (xy[:, 0] >= x0)
                & (xy[:, 0] < x0 + tile)
                & (xy[:, 1] >= y0)
                & (xy[:, 1] < y0 + tile)
            )
            pts.append(xy[keep])
            descs.append(d[keep].astype(np.float32))
    if not pts:
        return np.zeros((0, 2), np.float32), np.zeros((0, 128), np.float32)
    return np.concatenate(pts), np.concatenate(descs)


def _file_digest(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class MapIndex:
    """Uma camada do mapa: imagem em tons de cinza + pontos característicos."""

    name: str
    gray: Gray
    points: NDArray[np.float32]  # (N, 2) em pixels do mapa
    descriptors: NDArray[np.float32]  # (N, 128)

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.gray.shape
        return w, h

    @classmethod
    def build(cls, name: str, image: NDArray[np.uint8]) -> MapIndex:
        gray = to_gray(image)
        log.info("Calculando pontos do mapa '%s' (%dx%d)...", name, gray.shape[1], gray.shape[0])
        pts, desc = detect_tiled(gray)
        log.info("Mapa '%s': %d pontos.", name, len(pts))
        return cls(name=name, gray=gray, points=pts, descriptors=desc)

    @classmethod
    def from_file(cls, image_path: Path, name: str | None = None) -> MapIndex:
        """Carrega a imagem e o índice em cache (<imagem>.index.npz), recalculando se preciso."""
        name = name or image_path.stem
        data = np.fromfile(str(image_path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(f"Não foi possível abrir o mapa: {image_path}")
        gray = np.asarray(img, np.uint8)

        cache = image_path.with_suffix(image_path.suffix + ".index.npz")
        digest = _file_digest(image_path)
        if cache.exists():
            with np.load(cache) as z:
                if int(z["version"]) == INDEX_VERSION and str(z["digest"]) == digest:
                    log.info("Índice do mapa '%s' carregado do cache.", name)
                    return cls(name, gray, z["points"], z["descriptors"])
            log.info("Cache do mapa '%s' desatualizado; recalculando.", name)

        index = cls.build(name, gray)
        np.savez_compressed(
            cache,
            version=INDEX_VERSION,
            digest=digest,
            points=index.points,
            descriptors=index.descriptors,
        )
        return index
