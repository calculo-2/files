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


def test_reward_in_left_obtained_list() -> None:
    """A recompensa pode aparecer na lista "Obtido" da esquerda (quadro real 1080p)."""
    det = Scripted()
    frame = np.zeros((1080, 1920, 3), np.uint8)
    det.script = {"prompt": ["Bau Sofisticado"], "pickup": ["Bau Sofisticado", "Be"]}
    assert det.update(frame, 0.0) == []
    det.script = {"obtained": ["Obtido", "EXPdoAventureirox100", "Mora x1.250"]}
    events = det.update(frame, 1.5)
    assert [(e.kind, e.certain) for e in events] == [("chest", True)]
    # "EXP do Personagem" (de livros/experiência) não é baú.
    det2 = Scripted()
    det2.script = {"obtained": ["Obtido", "EXPdoPersonagemx60"]}
    assert det2.update(frame, 0.0) == []


def test_obtained_region_matches_real_frame() -> None:
    from gmt.detect.events import OBTAINED_REGION

    x0, y0, x1, y1 = OBTAINED_REGION.rect(1920, 1080)
    # Caixas lidas num quadro real: "Obtido" (165,508) até "...x60" (450,724).
    assert x0 <= 158 and x1 >= 464 and y0 <= 508 and y1 >= 724


# Segunda sessão real (Baú Sofisticado), em segundos desde 16:33:00. Baús abertos às
# 16:33:39 e 16:36:03 ("EXP do Herói" logo após o aviso). "Beterraba Vermelha" (planta)
# 6 s depois de um aviso e materiais de Acreção 22 s depois não podem virar baú.
SESSION2 = [
    (13, "prompt", ["gmento de", "recao", "Amplificacao de", "Acrecao"]),
    (18, "prompt", ["Bau Sofisticado"]),
    (24, "prompt", ["Beterraba Vermelha", "Beterraba Vermelha", "Beterraba Vermelha"]),
    (29, "prompt", ["Bau Sofisticado"]),
    (34, "prompt", ["Bau Sofisticado"]),
    (39, "prompt", ["EXPdoHeroi", "Pena de Cauda de", "Aventureiro", "Flor Verde do", "Sortudo"]),
    (61, "prompt", ["Beterraba Vermelha"]),
    (127, "prompt", ["Bau Sofisticado"]),
    (153, "pickup", ["Bau Sofisticado", "Ber"]),
    (162, "prompt", ["22214"]),
    (175, "prompt", ["Cristal Etéreo", "Fragmento de", "3Acrecao", "Massa de Acrecao"]),
    (178, "prompt", ["Massa de Acrecao", "Amplificagaao de", "Acrecao"]),
    (181, "prompt", ["Bau Sofisticado"]),
    (183, "prompt", ["EXP do Heroi"]),
    (206, "prompt", ["Bau Sofisticado"]),
]


def test_replay_second_session() -> None:
    det = Scripted()
    frame = np.zeros((1080, 1920, 3), np.uint8)
    events = []
    for t, region, lines in SESSION2:
        det.script = {region: lines}
        events += [(t, e.kind, e.certain) for e in det.update(frame, float(t))]
    assert events == [(39, "chest", True), (183, "chest", True)]


def test_mora_alone_is_not_a_chest() -> None:
    det = Scripted()
    frame = np.zeros((1080, 1920, 3), np.uint8)
    det.script = {"obtained": ["Obtido", "Mora x300"]}
    assert det.update(frame, 0.0) == []


# Terceira sessão real: baú marcado no site e Cryoculus marcado no site. A lista "Obtido"
# repetiu as recompensas do baú 6 s depois (não pode virar um segundo baú).
SESSION3 = [
    (36, "prompt", ["Bau Sofisticado"]),
    (45, "prompt", ["Bau Sofisticado"]),
    (
        48,
        "prompt",
        ["Relogio de Bolso de", "Instrutor", "Bandana de", "Aventureiro", "EXP do Heroi"],
    ),
    (54, "obtained", ["Gema Essencial x 5", "ExP-do:Heroi x 1"]),
    (55, "obtained", ["EXP do Heroix1"]),
    (65, "obtained", ["Obtido", "Cryoculus x1", "Mora x 600"]),
    (74, "obtained", ["Obtido", "Beterraba Vermelha-x1", "Beterraba Vermelhax1"]),
    (92, "obtained", ["Obtido", "Pedaco de Ferro x1"]),
]


def test_replay_third_session() -> None:
    det = Scripted()
    frame = np.zeros((1080, 1920, 3), np.uint8)
    events = []
    for t, region, lines in SESSION3:
        det.script = {region: lines}
        events += [(t, e.kind, e.certain) for e in det.update(frame, float(t))]
    assert events == [(48, "chest", True), (65, "cryoculus", True)]


def test_artifact_name_is_not_adventure_exp() -> None:
    from gmt.detect.events import CHEST_REWARD_WORDS, reward_hits

    assert reward_hits("Bandana de Aventureiro EXP do Heroi", CHEST_REWARD_WORDS) == ()
    assert reward_hits("Gema Essencial x 5", CHEST_REWARD_WORDS) == ("gema essencial",)


def test_all_oculi_with_ocr_noise() -> None:
    from gmt.detect.events import OCULUS_WORDS, best_kind

    noisy = {
        "anemoculus": "Anemocu1us", "geoculus": "Geocu|us", "electroculus": "Eletroculus",
        "dendroculus": "Dendrocuius", "hydroculus": "Hydrocu1us", "pyroculus": "Pyrocuius",
        "cryoculus": "Cryocu1us", "lunoculus": "Lunoculusx1",
    }  # fmt: skip
    for kind, text in noisy.items():
        assert best_kind(text, OCULUS_WORDS) == kind, text


def test_shrine_counts_as_chest() -> None:
    assert is_chest_prompt("Santuario das Profundezas")
    from gmt.web.appsample import type_ids_from_buttons

    ids = type_ids_from_buttons([
        {"title": "Baú Comum", "type": "o17"},
        {"title": "Santuário das Profundezas de Mondstadt", "type": "o8"},
        {"title": "Santuário das Profundezas de Liyue", "type": "o9"},
    ])  # fmt: skip
    assert set(ids["chest"]) == {"o17", "o8", "o9"}
