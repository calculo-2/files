"""OCR de verdade (RapidOCR) em textos PT-BR desenhados na região da interface."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

pytest.importorskip("rapidocr_onnxruntime")
PIL = pytest.importorskip("PIL")
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
if not FONT.exists():
    pytest.skip("fonte de teste ausente", allow_module_level=True)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from gmt.detect.events import PICKUP_REGION, PROMPT_REGION, CollectDetector, RapidOcr  # noqa: E402


@pytest.fixture(scope="module")
def ocr() -> RapidOcr:
    return RapidOcr()


def frame_with(texts: dict[str, list[str]]) -> np.ndarray:
    img = Image.new("RGB", (1920, 1080), (35, 50, 80))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT), 24)
    for name, region in (("prompt", PROMPT_REGION), ("pickup", PICKUP_REGION)):
        x0, y0, _, _ = region.rect(1920, 1080)
        for i, line in enumerate(texts.get(name, [])):
            d.rectangle((x0 + 30, y0 + 40 + 50 * i, x0 + 400, y0 + 80 + 50 * i), fill=(20, 20, 30))
            d.text((x0 + 40, y0 + 45 + 50 * i), line, font=font, fill=(240, 240, 240))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def test_chest_and_oculus_with_real_ocr(ocr: RapidOcr) -> None:
    det = CollectDetector(ocr)
    assert det.update(frame_with({"prompt": ["F   Baú Precioso"]}), 0.0) == []
    events = det.update(frame_with({"pickup": ["EXP de Aventura ×20", "Gema Essencial ×5"]}), 1.0)
    assert [(e.kind, e.certain) for e in events] == [("chest", True)]
    events = det.update(frame_with({"pickup": ["Electroculus"]}), 10.0)
    assert [e.kind for e in events] == ["electroculus"]


def test_unrelated_text_is_ignored(ocr: RapidOcr) -> None:
    det = CollectDetector(ocr)
    assert det.update(frame_with({"pickup": ["Flor Doce ×2", "Cogumelo ×1"]}), 0.0) == []
