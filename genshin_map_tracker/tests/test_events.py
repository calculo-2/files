from __future__ import annotations

import numpy as np

from gmt.detect.events import (
    PICKUP_REGION,
    CollectDetector,
    DetectorConfig,
    Region,
    fuzzy_contains,
    normalize,
)


class FakeOcr:
    """Devolve textos diferentes conforme o brilho da região (o teste controla o quadro)."""

    def __init__(self, texts: dict[int, list[str]]) -> None:
        self.texts = texts
        self.calls = 0

    def read(self, image: np.ndarray) -> list[str]:
        self.calls += 1
        return self.texts.get(int(image.mean()), [])


def frame(prompt: int, pickup: int) -> np.ndarray:
    """Quadro 1080p onde as regiões têm brilhos escolhidos (o FakeOcr usa o brilho)."""
    f = np.zeros((1080, 1920, 3), np.uint8)
    cfg = DetectorConfig(
        prompt_region=Region("prompt", 100, 100, 200, 100),
        pickup_region=Region("pickup", 500, 100, 200, 100),
    )
    f[100:200, 100:300] = prompt
    f[100:200, 500:700] = pickup
    return f, cfg  # type: ignore[return-value]


def detector(texts: dict[int, list[str]]) -> tuple[CollectDetector, FakeOcr]:
    _, cfg = frame(0, 0)  # type: ignore[misc]
    ocr = FakeOcr(texts)
    return CollectDetector(ocr, cfg), ocr


def f(prompt: int, pickup: int) -> np.ndarray:
    return frame(prompt, pickup)[0]  # type: ignore[index]


def test_normalize_and_fuzzy() -> None:
    assert normalize("Baú Precioso!") == "bau precioso"
    assert fuzzy_contains("EXP do Aventureiro x50", "exp do aventureiro")
    assert fuzzy_contains("EXP do Aventureirо", "exp do aventureiro")  # "о" cirílico: erro de OCR
    assert fuzzy_contains("Anemocu1us", "anemoculus")
    assert not fuzzy_contains("Flor Doce", "anemoculus")
    assert fuzzy_contains("EXPdo Aventureiro x20", "exp do aventureiro")  # OCR juntou palavras


def test_reward_split_across_boxes() -> None:
    det, _ = detector({80: ["Gema", "Essencial x5"]})
    events = det.update(f(0, 80), 0.0)
    assert [e.kind for e in events] == ["chest"]
    assert events[0].evidence == ("gema essencial",)


def test_chest_with_prompt_is_certain() -> None:
    det, _ = detector({50: ["F  Baú Comum"], 80: ["EXP do Aventureiro x20", "Mora x150"]})
    assert det.update(f(50, 0), 0.0) == []
    events = det.update(f(0, 80), 1.5)
    assert [(e.kind, e.certain) for e in events] == [("chest", True)]


def test_reward_without_prompt_is_uncertain() -> None:
    det, _ = detector({80: ["EXP do Aventureiro x20"]})
    events = det.update(f(0, 80), 0.0)
    assert [(e.kind, e.certain) for e in events] == [("chest", False)]


def test_old_prompt_does_not_count() -> None:
    det, _ = detector({50: ["Baú Precioso"], 80: ["Gema Essencial x5"]})
    det.update(f(50, 0), 0.0)
    events = det.update(f(0, 80), 20.0)
    assert events[0].certain is False


def test_oculus_kinds() -> None:
    det, _ = detector({90: ["Geoculus x1"], 160: ["Hidróculo"]})
    assert [e.kind for e in det.update(f(0, 90), 0.0)] == ["geoculus"]
    assert [e.kind for e in det.update(f(0, 160), 1.0)] == ["hydroculus"]


def test_cooldown_and_ocr_only_on_change() -> None:
    det, ocr = detector({80: ["EXP do Aventureiro"]})
    assert len(det.update(f(0, 80), 0.0)) == 1
    calls = ocr.calls
    # Mesma imagem: não roda OCR de novo.
    assert det.update(f(0, 80), 1.0) == []
    assert ocr.calls == calls
    # Imagem muda e volta: OCR roda, mas o evento repetido cai no intervalo de espera.
    det.update(f(0, 0), 2.0)
    assert det.update(f(0, 80), 3.0) == []
    assert len(det.update(f(0, 0), 8.0) + det.update(f(0, 80), 9.0)) == 1


def test_region_scaling_and_anchor() -> None:
    img = np.zeros((1440, 3440, 3), np.uint8)
    r = Region("r", 1700, 300, 100, 50, anchor="right")
    crop = r.crop(img)
    assert crop.shape[0] == 66 and abs(crop.shape[1] - 133) <= 1  # escala 4/3 pela altura
    cols = np.tile(np.arange(3440), (1440, 1))
    assert int(r.crop(cols)[0, 0]) == int(3440 - (1920 - 1700) * 4 / 3)  # preso à direita
    assert PICKUP_REGION.crop(np.zeros((1080, 1920, 3), np.uint8)).shape[:2] == (520, 560)


def test_rate_limit() -> None:
    det, ocr = detector({80: ["Mora"], 81: ["Mora"]})
    det.update(f(0, 80), 0.0)
    det.update(f(0, 0), 0.1)  # mudou, mas cedo demais
    assert ocr.calls == 2  # 1ª chamada: prompt + pickup


def test_threaded_detector_does_not_block() -> None:
    import time

    from gmt.detect.events import ThreadedDetector

    class SlowOcr(FakeOcr):
        def read(self, image: np.ndarray) -> list[str]:
            time.sleep(0.3)
            return super().read(image)

    _, cfg = frame(0, 0)  # type: ignore[misc]
    td = ThreadedDetector(CollectDetector(SlowOcr({80: ["Geoculus"]}), cfg))
    try:
        t0 = time.perf_counter()
        assert td.update(f(0, 80), 0.0) == []
        assert time.perf_counter() - t0 < 0.05, "update não pode esperar o OCR"
        events = []
        deadline = time.perf_counter() + 3
        while not events and time.perf_counter() < deadline:
            time.sleep(0.05)
            events = td.update(f(0, 80), 0.1)
        assert [e.kind for e in events] == ["geoculus"]
    finally:
        td.close()
