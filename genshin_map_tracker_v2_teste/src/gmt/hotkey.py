"""Atalho global de pausa (Windows).

Usa RegisterHotKey: o Windows avisa o app quando a combinação é pressionada.
Não é um gancho de teclado (não lê outras teclas) e não envia nada a ninguém.
Fora do Windows, não faz nada.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
NAMED_KEYS = {f"f{i}": 0x6F + i for i in range(1, 13)} | {
    "pause": 0x13,
    "space": 0x20,
    "home": 0x24,
    "end": 0x23,
    "insert": 0x2D,
}


class HotkeyError(ValueError):
    pass


def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+p' -> (modificadores, código virtual da tecla)."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        raise HotkeyError("Atalho vazio.")
    *mods, key = parts
    mod = 0
    for m in mods:
        if m not in MODIFIERS:
            raise HotkeyError(f"Modificador desconhecido: {m}")
        mod |= MODIFIERS[m]
    if key in NAMED_KEYS:
        vk = NAMED_KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise HotkeyError(f"Tecla desconhecida: {key}")
    return mod, vk


class GlobalHotkey:
    """Chama `callback` (noutra thread) a cada vez que o atalho é pressionado."""

    def __init__(self, text: str, callback: Callable[[], None]) -> None:
        self.text = text
        self.mod, self.vk = parse_hotkey(text)
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self.active = False

    def start(self) -> bool:
        if sys.platform != "win32":
            log.info("Atalho global só funciona no Windows.")
            return False
        ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(2.0)
        return self.active

    def _loop(self, ready: threading.Event) -> None:
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        hotkey_id = 0xB0B
        if not user32.RegisterHotKey(None, hotkey_id, self.mod | MOD_NOREPEAT, self.vk):
            log.warning("Não deu para registrar o atalho %s (outro programa usa?).", self.text)
            ready.set()
            return
        self.active = True
        ready.set()
        msg = wintypes.MSG()
        wm_hotkey = 0x0312
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == wm_hotkey and msg.wParam == hotkey_id:
                    try:
                        self.callback()
                    except Exception:  # noqa: BLE001
                        log.exception("Erro no atalho")
        finally:
            user32.UnregisterHotKey(None, hotkey_id)
            self.active = False

    def stop(self) -> None:
        if sys.platform == "win32" and self._thread_id:
            import ctypes

            wm_quit = 0x0012
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, wm_quit, 0, 0)
