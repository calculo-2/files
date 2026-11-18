"""Servidor HTTP local e navegador de teste para os testes da parte web."""

from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

CHROMIUM = os.environ.get("GMT_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
ASSETS = Path(__file__).parent / "assets"


def require_browser() -> None:
    pytest.importorskip("playwright")
    if not Path(CHROMIUM).exists():
        pytest.skip("Chromium para testes não encontrado")


@contextmanager
def serve(root: Path) -> Iterator[str]:
    """Serve `root` em http://127.0.0.1:<porta>/ (com o Leaflet em /leaflet.js)."""
    shutil.copy(ASSETS / "leaflet" / "leaflet.js", root / "leaflet.js")
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
