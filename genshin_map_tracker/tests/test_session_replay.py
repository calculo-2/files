"""Reproduz o texto lido pelo OCR numa sessão real (07/11/2026, jogo em PT-BR).

Só os textos, na ordem em que apareceram. Na sessão houve um baú comum aberto às
16:13:34 ("Bat Comum" é como o OCR leu "Baú Comum") seguido de "EXP do Aventureiro".
"""

from __future__ import annotations

import numpy as np

from gmt.detect.events import CollectDetector, DetectorConfig, is_chest_prompt

# (segundos desde 16:12:00, região, linhas lidas)
SESSION = [
    (25, "pickup", ["Xil", "Benne"]),
    (40, "prompt", ["NiicleoOuimerico", "Nucleo Quimerico", "Simbiotico"]),
    (41, "pickup", ["Xil", "Niicleo Ouimerico", "NucleoQuimerico", "Simbiotico", "Benne"]),
    (48, "pickup", ["Desconhecido"]),
    (69, "prompt", ["nvestigar"]),
    (69, "pickup", ["Xil", "nvestigar", "Ber", "Plataforma de Lancamento"]),
    (73, "prompt", ["Curtir"]),
    (80, "prompt", ["Culinaria", "5272"]),
    (82, "prompt", ["Nv.100", "Culinaria", "Fundir"]),
    (88, "prompt", ["Acrecao", "Massa de Acrecao", "Granizo Etéreo", "Fragmento de", "③Acrecao"]),
    (
        88,
        "pickup",
        [
            "Xil",
            "Amplificacao de",
            "Acrecao",
            "Massa de Acrecao",
            "Benne",
            "Granizo Etereo",
            "Fragmento de",
            "Acrecao",
        ],
    ),  # fmt: skip
    (91, "prompt", ["GranizoEtereo", "Fragmento de", "3Acrecao", "Massa de Acrecao"]),
    (94, "prompt", ["Bat Comum"]),
    (94, "pickup", ["Xil", "Bat Comum", "Benne"]),
    (95, "prompt", ["EXP do Aventureiro", "Rosa do Aventureiro"]),
    (96, "pickup", ["Xil", "EXP do Aventureiro", "Benne", "Rosa do Aventureiro"]),
    (96, "pickup", ["Xil", "Benne"]),
    (105, "pickup", ["De"]),
    (114, "pickup", ["Xil", "Benne"]),
]


class Scripted(CollectDetector):
    """Detector que recebe as linhas prontas em vez de rodar OCR."""

    def __init__(self) -> None:
        super().__init__(engine=None, config=DetectorConfig())  # type: ignore[arg-type]
        self.script: dict[str, list[str] | None] = {}

    def _read(self, name: str, img: np.ndarray, t: float) -> list[str] | None:
        return self.script.get(name)


def test_replay_finds_the_real_chest() -> None:
    det = Scripted()
    frame = np.zeros((1080, 1920, 3), np.uint8)
    events = []
    for t, region, lines in SESSION:
        det.script = {"prompt": None, "pickup": None, region: lines}
        events += [(t, e.kind, e.certain) for e in det.update(frame, float(t))]
    assert events == [(95, "chest", True)]


def test_chest_prompt_variants() -> None:
    for text in ["Bat Comum", "Baú Comum", "Bau Sofisticado", "Ba Precioso", "Baú Luxuoso",
                 "Baú Estranho", "F Baú Comum"]:  # fmt: skip
        assert is_chest_prompt(text), text
    for text in ["Banco Comum", "Culinaria", "Rosa do Aventureiro", "Massa de Acrecao", "Xil"]:
        assert not is_chest_prompt(text), text
