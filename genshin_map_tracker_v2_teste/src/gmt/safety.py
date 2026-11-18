"""Auditoria de segurança anti-ban (arquitetura 100% passiva por captura de tela).

Por que ferramentas de "injetor/extrator" causam banimento no Genshin Impact:
- O anti-cheat de kernel (HoYoProtect) monitora abertura de handle no processo do jogo
  (`OpenProcess`), leitura/escrita de memória (`ReadProcessMemory`/`WriteProcessMemory`),
  injeção de DLL (`CreateRemoteThread`/`LoadLibrary`), hooks gráficos em DirectX/DXGI,
  interceptação de pacotes de rede (WinDivert/Npcap/proxy MITM) e envio de entradas
  sintéticas (`SendInput`, `mouse_event`, `keybd_event`, `PostMessage`).

Este módulo garante — por inspeção estática da árvore de código (AST) e checagem de
módulos carregados em tempo de execução — que o `gmt` jamais importa bibliotecas nem
chama APIs invasivas. Toda leitura vem da imagem da área de trabalho (como OBS/Discord)
e toda automação ocorre exclusivamente no navegador externo.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        # Leitura/injeção de memória e depuração de processos
        "pymem",
        "frida",
        "pywinauto",
        "winappdbg",
        # Captura/interceptação de rede do jogo
        "scapy",
        "pydivert",
        "mitmproxy",
        "pyshark",
        # Automação de input global / simulação de teclado e mouse no sistema
        "pyautogui",
        "pydirectinput",
        "pynput",
        "keyboard",
        "mouse",
    }
)

FORBIDDEN_WIN32_APIS: frozenset[str] = frozenset(
    {
        # Acesso a processo e memória
        "OpenProcess",
        "ReadProcessMemory",
        "WriteProcessMemory",
        "VirtualAllocEx",
        "VirtualProtectEx",
        "CreateRemoteThread",
        "NtReadVirtualMemory",
        "NtWriteVirtualMemory",
        "NtOpenProcess",
        # Hooks globais invasivos e envio de input ao jogo
        "SetWindowsHookExA",
        "SetWindowsHookExW",
        "SetWindowsHookEx",
        "SendInput",
        "mouse_event",
        "keybd_event",
        "PostMessageA",
        "PostMessageW",
        "SendMessageA",
        "SendMessageW",
        # Overlay por cima do jogo
        "WS_EX_TOPMOST",
        "HWND_TOPMOST",
    }
)


@dataclass(frozen=True)
class SafetyReport:
    ok: bool
    checked_files: int
    violations: tuple[str, ...]

    def summary(self) -> str:
        if self.ok:
            return (
                f"Auditoria anti-ban APROVADA ({self.checked_files} módulos verificados): "
                "zero injeção, zero leitura de memória, zero interceptação de rede, "
                "zero input/overlay no jogo."
            )
        joined = "; ".join(self.violations)
        return f"VIOLAÇÃO DE SEGURANÇA DETECTADA: {joined}"


def audit_source_tree(package_dir: Path | None = None) -> SafetyReport:
    """Inspeciona todos os `.py` do pacote `gmt` procurando imports ou APIs proibidas."""
    root = package_dir or Path(__file__).resolve().parent
    this_file = Path(__file__).resolve()
    violations: list[str] = []
    checked = 0

    for py_file in sorted(root.rglob("*.py")):
        if py_file.resolve() == this_file:
            continue
        checked += 1
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        rel = py_file.relative_to(root).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in FORBIDDEN_IMPORTS:
                        violations.append(f"{rel}:{node.lineno} import proibido '{alias.name}'")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in FORBIDDEN_IMPORTS:
                        violations.append(f"{rel}:{node.lineno} import proibido '{node.module}'")
            elif isinstance(node, ast.Attribute):
                if node.attr in FORBIDDEN_WIN32_APIS:
                    violations.append(f"{rel}:{node.lineno} API proibida '{node.attr}'")
            elif isinstance(node, ast.Name) and node.id in FORBIDDEN_WIN32_APIS:
                violations.append(f"{rel}:{node.lineno} símbolo proibido '{node.id}'")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in FORBIDDEN_WIN32_APIS
            ):
                violations.append(f"{rel}:{node.lineno} referência proibida '{node.value}'")

    loaded = sorted(FORBIDDEN_IMPORTS.intersection(k.split(".")[0] for k in sys.modules))
    for mod in loaded:
        violations.append(f"runtime: módulo proibido carregado '{mod}'")

    return SafetyReport(ok=not violations, checked_files=checked, violations=tuple(violations))
