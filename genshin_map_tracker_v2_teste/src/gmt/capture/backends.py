"""Backends de captura de tela.

Ambos leem a imagem já composta pelo sistema (como OBS ou compartilhamento de
tela do Discord). Nenhum deles se anexa ao processo do jogo nem hooka DirectX.

- dxcam: Desktop Duplication API do Windows. Rápido, baixo uso de CPU.
- mss: captura de tela via GDI. Reserva; pode sair preto em tela cheia exclusiva.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from gmt.capture.window import Rect

log = logging.getLogger(__name__)

Frame = NDArray[np.uint8]  # imagem BGR, shape (altura, largura, 3)


class CaptureError(RuntimeError):
    pass


class CaptureBackend(Protocol):
    name: str

    def grab(self, rect: Rect) -> Frame | None:
        """Captura `rect` (coordenadas de tela). None se não houver quadro."""
        ...

    def close(self) -> None: ...


class MssBackend:
    name = "mss"

    def __init__(self) -> None:
        import mss

        self._sct = mss.mss()

    def grab(self, rect: Rect) -> Frame | None:
        shot = self._sct.grab(
            {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        )
        bgra = np.asarray(shot, dtype=np.uint8)
        return np.ascontiguousarray(bgra[:, :, :3])

    def close(self) -> None:
        self._sct.close()


class DxcamBackend:
    name = "dxcam"

    def __init__(self, target: Rect) -> None:
        if sys.platform != "win32":
            raise CaptureError("dxcam só funciona no Windows.")
        try:
            import dxcam
        except ImportError as exc:
            raise CaptureError("dxcam não instalado.") from exc

        self._camera: Any
        self._origin: tuple[int, int]
        self._camera, self._origin = self._open_output(dxcam, target)
        self._last: Frame | None = None

    @staticmethod
    def _find_output(dxcam: Any, target: Rect) -> tuple[int, int, tuple[int, int]] | None:
        """Acha (placa, saída, origem) do monitor que contém o centro da janela.

        Lê a lista de monitores do dxcam sem abrir câmeras (API interna; pode mudar).
        """
        factory = getattr(dxcam, "__factory", None)
        outputs = getattr(factory, "outputs", None)
        if not outputs:
            return None
        cx = target.left + target.width // 2
        cy = target.top + target.height // 2
        for d_idx, device_outputs in enumerate(outputs):
            for o_idx, output in enumerate(device_outputs):
                try:
                    output.update_desc()
                    c = output.desc.DesktopCoordinates
                except Exception as exc:  # noqa: BLE001 - erros COM variados
                    log.debug("dxcam: placa %d saída %d ilegível: %r", d_idx, o_idx, exc)
                    continue
                log.debug(
                    "dxcam: placa %d saída %d em (%d,%d)-(%d,%d)",
                    d_idx, o_idx, c.left, c.top, c.right, c.bottom,
                )  # fmt: skip
                if c.left <= cx < c.right and c.top <= cy < c.bottom:
                    return d_idx, o_idx, (c.left, c.top)
        return None

    @classmethod
    def _open_output(cls, dxcam: Any, target: Rect) -> tuple[Any, tuple[int, int]]:
        """Abre a câmera no monitor do jogo. Sem achar, tenta o monitor primário."""
        try:
            found = cls._find_output(dxcam, target)
        except Exception as exc:  # noqa: BLE001
            log.debug("dxcam: falha ao listar monitores: %r", exc)
            found = None

        try:
            if found is not None:
                d_idx, o_idx, origin = found
                cam = dxcam.create(device_idx=d_idx, output_idx=o_idx, output_color="BGR")
                log.info("dxcam: placa %d, monitor %d, origem %s", d_idx, o_idx, origin)
                return cam, origin
            log.info("dxcam: monitor do jogo não identificado; usando o primário.")
            cam = dxcam.create(output_color="BGR")
        except Exception as exc:  # noqa: BLE001 - dxcam levanta tipos variados
            raise CaptureError(f"dxcam não abriu a captura: {exc!r}") from exc

        # No primário a origem é (0,0); confere se a janela cabe nele.
        fits = target.left >= 0 and target.top >= 0
        fits = fits and target.right <= cam.width and target.bottom <= cam.height
        if not fits:
            size = f"{cam.width}x{cam.height}"
            cam.release()
            outputs = ""
            with contextlib.suppress(Exception):
                outputs = " | saídas: " + dxcam.output_info().replace("\n", "; ")
            raise CaptureError(
                f"dxcam: janela do jogo em {target} não cabe no monitor primário ({size}){outputs}"
            )
        return cam, (0, 0)

    def grab(self, rect: Rect) -> Frame | None:
        ox, oy = self._origin
        region = (rect.left - ox, rect.top - oy, rect.right - ox, rect.bottom - oy)
        try:
            frame = self._camera.grab(region=region)
        except ValueError as exc:  # região fora do monitor (janela mudou de lugar)
            log.warning("dxcam: %s", exc)
            return None
        if frame is not None:
            self._last = np.ascontiguousarray(frame, dtype=np.uint8)
        # dxcam devolve None quando a tela não mudou; reaproveita o último quadro.
        return self._last

    def close(self) -> None:
        self._camera.release()


def create_backend(kind: str, target: Rect) -> CaptureBackend:
    """Cria o backend pedido. "auto" tenta dxcam e cai para mss."""
    if kind in ("auto", "dxcam"):
        try:
            return DxcamBackend(target)
        except CaptureError as exc:
            if kind == "dxcam":
                raise
            log.warning("dxcam indisponível (%s); usando mss.", exc)
    return MssBackend()
