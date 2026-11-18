"""Localiza a janela do Genshin Impact.

Usa apenas consultas públicas de janela do Windows (título, classe, posição).
NÃO abre o processo do jogo, não lê memória e não envia nenhuma entrada.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

GAME_TITLES: tuple[str, ...] = ("Genshin Impact", "原神")
GAME_CLASS = "UnityWndClass"


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str
    client: Rect  # área útil (sem borda/título) em coordenadas de tela
    is_foreground: bool
    is_minimized: bool


class UnsupportedPlatformError(RuntimeError):
    """A detecção de janela só existe no Windows."""


_dpi_set = False


def enable_dpi_awareness() -> None:
    """Faz o Windows reportar pixels reais, mesmo com escala de 125%/150%."""
    global _dpi_set
    if _dpi_set or sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            log.warning("Não foi possível ativar DPI awareness; recortes podem sair deslocados.")
    _dpi_set = True


def find_game_window() -> GameWindow | None:
    """Retorna a janela do jogo, ou None se não estiver aberta."""
    if sys.platform != "win32":
        raise UnsupportedPlatformError("Detecção de janela disponível apenas no Windows.")

    import ctypes
    from ctypes import wintypes

    enable_dpi_awareness()
    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []

    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        if title_buf.value in GAME_TITLES and class_buf.value == GAME_CLASS:
            found.append((int(hwnd), title_buf.value))
            return False
        return True

    user32.EnumWindows(enum_proc_type(_callback), 0)
    if not found:
        return None

    hwnd, title = found[0]
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))

    client = Rect(origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top)
    return GameWindow(
        hwnd=hwnd,
        title=title,
        client=client,
        is_foreground=int(user32.GetForegroundWindow() or 0) == hwnd,
        is_minimized=bool(user32.IsIconic(hwnd)),
    )
