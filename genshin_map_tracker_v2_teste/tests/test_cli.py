from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from gmt.cli import main
from gmt.vision.regions import Circle

from .conftest import make_frame


def _save(path: Path, img: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))


def test_crop_command(tmp_path: Path) -> None:
    img = tmp_path / "print ção.png"  # acento no nome: precisa funcionar no Windows
    _save(img, make_frame(1920, 1080, Circle(169.0, 125.0, 100)))
    assert main(["crop", str(img)]) == 0
    assert (tmp_path / "print ção_minimap.png").exists()
    assert (tmp_path / "print ção_debug.png").exists()


def test_calibrate_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    img = tmp_path / "shot.png"
    _save(img, make_frame(2560, 1440, Circle(230, 160, 135)))
    assert main(["calibrate", str(img)]) == 0
    out = capsys.readouterr().out
    assert "center_x = 172.5" in out  # 230 / (4/3)
    assert "center_y = 120.0" in out  # 160 / (4/3)
    assert (tmp_path / "shot_calibrate.png").exists()


def test_missing_image_returns_error(tmp_path: Path) -> None:
    assert main(["crop", str(tmp_path / "nada.png")]) == 2


@pytest.mark.skipif(sys.platform == "win32", reason="testa a mensagem fora do Windows")
def test_find_window_off_windows() -> None:
    assert main(["find-window"]) == 2
