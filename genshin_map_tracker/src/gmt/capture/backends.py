"""Backends de captura de tela.

Ambos leem a imagem já composta pelo sistema (como OBS ou compartilhamento de
tela do Discord). Nenhum deles se anexa ao processo do jogo nem hooka DirectX.

- dxcam: Desktop Duplication API do Windows. Rápido, baixo uso de CPU.
- mss: captura de tela via GDI. Reserva; pode sair preto em tela cheia exclusiva.
"""

from __future__ import annotations

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
    def _open_output(dxcam: Any, target: Rect) -> tuple[Any, tuple[int, int]]:
        """Abre a saída de vídeo (monitor) que contém o centro da janela."""
        cx = target.left + target.width // 2
        cy = target.top + target.height // 2
        for idx in range(8):
            try:
                cam = dxcam.create(output_idx=idx, output_color="BGR")
            except Exception:  # noqa: BLE001 - dxcam levanta tipos variados ao acabar as saídas
                break
            if cam is None:
                break
            try:
                coords = cam._output.desc.DesktopCoordinates  # API interna do dxcam
                left, top, right, bottom = coords.left, coords.top, coords.right, coords.bottom
            except AttributeError:
                log.warning("dxcam: não deu para ler a posição do monitor; usando o primário.")
                return cam, (0, 0)
            if left <= cx < right and top <= cy < bottom:
                log.info("dxcam: usando monitor %d (%d,%d)-(%d,%d)", idx, left, top, right, bottom)
                return cam, (left, top)
            cam.release()
        raise CaptureError("dxcam: nenhum monitor contém a janela do jogo.")

    def grab(self, rect: Rect) -> Frame | None:
        ox, oy = self._origin
        region = (rect.left - ox, rect.top - oy, rect.right - ox, rect.bottom - oy)
        frame = self._camera.grab(region=region)
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
