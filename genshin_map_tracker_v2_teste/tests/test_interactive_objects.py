"""Objetos interativos, resolução em cascata e auditoria anti-ban."""

from __future__ import annotations

import ast
import io
from pathlib import Path

import numpy as np
import pytest

from gmt.app import App, AppOptions, StatusConsole, TileConverter, TileLayer
from gmt.cli import main
from gmt.config import ConfigError, MinimapConfig, load_config
from gmt.data.catalog import ALL_SPECS, PERMANENT_KINDS, RESPAWNABLE_KINDS
from gmt.data.markers import Marker, MarkerStore
from gmt.detect.events import (
    BANNER_REGION,
    CollectDetector,
    CollectEvent,
    DetectorConfig,
    Region,
    chest_prompt_subtype,
)
from gmt.detect.resolver import ResolverConfig, kinds_for_event, resolve
from gmt.localization.localizer import Localizer
from gmt.localization.mapindex import MapIndex
from gmt.safety import audit_source_tree
from gmt.web.appsample import type_ids_from_buttons

from .synthetic import make_game_frame, make_map


class RegionScriptedDetector(CollectDetector):
    """Detector com textos controlados por região (prompt, pickup, obtained, banner)."""

    def __init__(self, include_respawnables: bool = False) -> None:
        super().__init__(
            engine=None,  # type: ignore[arg-type]
            config=DetectorConfig(include_respawnables=include_respawnables),
        )
        self.script: dict[str, list[str] | None] = {}

    def _read(self, name: str, img: np.ndarray, t: float) -> list[str] | None:
        _ = img, t
        return self.script.get(name)


def test_safety_audit_passes_and_catches_violations(tmp_path: Path) -> None:
    rep = audit_source_tree()
    assert rep.ok, rep.violations
    assert rep.checked_files >= 18

    bad_pkg = tmp_path / "bad_gmt"
    bad_pkg.mkdir()
    (bad_pkg / "evil.py").write_text(
        "import pymem\nimport pyautogui\nctypes.windll.kernel32.ReadProcessMemory(1, 2, 3, 4, 5)\n",
        encoding="utf-8",
    )
    bad_rep = audit_source_tree(bad_pkg)
    assert not bad_rep.ok
    assert len(bad_rep.violations) == 3

    pkg_root = Path(__file__).resolve().parent.parent / "src" / "gmt"
    for py in pkg_root.rglob("*.py"):
        ast.parse(py.read_text(encoding="utf-8"))


def test_catalog_completeness_and_appsample_mapping() -> None:
    assert len(ALL_SPECS) >= 120
    assert len(PERMANENT_KINDS) >= 40
    assert len(RESPAWNABLE_KINDS) >= 70

    buttons = [
        {"title": "Baú Comum", "type": "o17"},
        {"title": "Baú Precioso", "type": "o45"},
        {"title": "Baú Estranho", "type": "o269"},
        {"title": "Santuário das Profundezas de Natlan", "type": "o901"},
        {"title": "Ponto de Teleporte", "type": "o3"},
        {"title": "Estação de Transporte de Alta Velocidade", "type": "o950"},
        {"title": "Estátua dos Sete", "type": "o2"},
        {"title": "Domínio", "type": "o47"},
        {"title": "Observatório", "type": "o70"},
        {"title": "Seelie Guia", "type": "o19"},
        {"title": "Monetoo", "type": "o710"},
        {"title": "Desafios Contra o Tempo", "type": "o24"},
        {"title": "Baú Enterrado", "type": "o33"},
        {"title": "Mini Quebra-Cabeças", "type": "o115"},
        {"title": "Espato Lúmen", "type": "o350"},
        {"title": "Calcedônia Carmesim", "type": "o99"},
        {"title": "Carpas Espirituais", "type": "o580"},
        {"title": "Padrão de Chave II", "type": "o312"},
        {"title": "Baú de Mora de Pilha de Pedras", "type": "o410"},
        {"title": "Cristal Rodopiante Radiante", "type": "o320"},
        {"title": "Cor Lapis", "type": "o11"},
        {"title": "Pedaço de Cristal", "type": "o14"},
    ]
    mapped = type_ids_from_buttons(buttons)
    assert set(mapped["chest"]) == {"o17", "o45", "o269", "o901"}
    assert mapped["chest_precious"] == ("o45",)
    assert mapped["remarkable_chest"] == ("o269",)
    assert mapped["shrine"] == ("o901",)
    assert set(mapped["teleport"]) == {"o3", "o950"}
    assert mapped["statue"] == ("o2",)
    assert mapped["domain"] == ("o47",)
    assert mapped["viewpoint"] == ("o70",)
    assert mapped["seelie"] == ("o19",)
    assert mapped["monetoo"] == ("o710",)
    assert mapped["time_trial"] == ("o24",)
    assert mapped["buried_chest"] == ("o33",)
    assert {"o19", "o710", "o24", "o33", "o115"}.issubset(set(mapped["puzzle_chest"]))
    assert mapped["lumenspar"] == ("o350",)
    assert mapped["crimson_agate"] == ("o99",)
    assert mapped["spirit_carp"] == ("o580",)
    assert mapped["key_sigil"] == ("o312",)
    assert mapped["mora_chest"] == ("o410",)
    assert mapped["spincrystal"] == ("o320",)
    assert mapped["specialty_cor_lapis"] == ("o11",)
    assert mapped["mineral_crystal"] == ("o14",)


def test_center_banner_scaling_ultrawide() -> None:
    r16_9 = BANNER_REGION.rect(1920, 1080)
    assert r16_9 == (660, 205, 1260, 300)
    x0, _y0, x1, _y1 = BANNER_REGION.rect(3440, 1440)
    center = (x0 + x1) / 2
    assert center == pytest.approx(1720.0, abs=2.0)
    with pytest.raises(ValueError):
        Region("bad", 0, 0, 10, 10, anchor="diagonal").rect(1920, 1080)


def test_detects_waypoints_statues_domains_viewpoints() -> None:
    det = RegionScriptedDetector()
    f = np.zeros((1080, 1920, 3), np.uint8)

    det.script = {"banner": ["Ponto de Teleporte desbloqueado"]}
    evs = det.update(f, 0.0)
    assert [(e.kind, e.certain) for e in evs] == [("teleport", True)]

    det.script = {"prompt": ["F Ponto de Teletransporte"]}
    evs = det.update(f, 10.0)
    assert [(e.kind, e.certain) for e in evs] == [("teleport", True)]

    det.script = {"prompt": ["Local de Ancoragem do Quebra-mar (Não é possível teleportar)"]}
    assert det.update(f, 20.0) == []

    det.script = {"prompt": ["Estátua dos Sete"]}
    evs = det.update(f, 30.0)
    assert [(e.kind, e.certain) for e in evs] == [("statue", False)]

    det.script = {"banner": ["Domínio desbloqueado"]}
    evs = det.update(f, 45.0)
    assert [(e.kind, e.certain) for e in evs] == [("domain", True)]

    det.script = {"banner": ["Novo Observatório adicionado"]}
    evs = det.update(f, 60.0)
    assert [(e.kind, e.certain) for e in evs] == [("viewpoint", True)]


def test_detects_all_regional_offerings_and_collectables() -> None:
    det = RegionScriptedDetector()
    f = np.zeros((1080, 1920, 3), np.uint8)
    samples = [
        (0.0, "Calcedônia Carmesim x1", "crimson_agate"),
        (10.0, "Espato Lúmen x1", "lumenspar"),
        (20.0, "Carpa Espiritual x1", "spirit_carp"),
        (30.0, "Pluma da Luz Purificadora", "plume_of_light"),
        (40.0, "Selo Sagrado", "sacred_seal"),
        (50.0, "Padrão de Chave III", "key_sigil"),
        (60.0, "Pérola da Lua Antiga x1", "ancient_moon_pearl"),
        (70.0, "Cristal Kresnik x1", "kresnik_kristall"),
        (80.0, "Cristal Rodopiante Radiante 42", "spincrystal"),
        (90.0, "Receita: Tentação de Adeptus", "recipe"),
    ]
    for t, text, expected in samples:
        det.script = {"obtained": ["Obtido", text]}
        evs = det.update(f, t)
        assert [e.kind for e in evs] == [expected], f"Falhou para {text}: {evs}"


def test_chest_subtypes_blueprints_and_puzzle_contexts() -> None:
    assert chest_prompt_subtype("Bat Precioso") == "chest_precious"
    assert chest_prompt_subtype("Baú Estranho") == "remarkable_chest"
    assert chest_prompt_subtype("Santuário das Profundezas") == "shrine"

    det = RegionScriptedDetector()
    f = np.zeros((1080, 1920, 3), np.uint8)

    det.script = {"prompt": ["Escavar"]}
    assert det.update(f, 0.0) == []
    det.script = {"prompt": ["Baú Precioso"]}
    assert det.update(f, 2.0) == []
    det.script = {"obtained": ["Gema Essencial x10", "EXP do Aventureiro x30"]}
    evs = det.update(f, 3.0)
    assert len(evs) == 1
    assert (evs[0].kind, evs[0].certain, evs[0].subtype, evs[0].context) == (
        "chest",
        True,
        "chest_precious",
        "buried_chest",
    )

    det.script = {"obtained": ["Diagrama: Lanterna de Pinheiro"]}
    evs = det.update(f, 25.0)
    assert len(evs) == 1
    assert (evs[0].kind, evs[0].certain, evs[0].subtype) == ("chest", True, "remarkable_chest")


def test_mora_rewards_from_real_sessions_are_not_mora_chests() -> None:
    """Textos reais (sessões de 07 e 16/11): Mora alta depois de "Investigar" e "Selo Cryo"
    nas recompensas de baú. Nenhum era Caixa de Mora; a versão anterior marcaria errado."""
    det = RegionScriptedDetector()
    f = np.zeros((1080, 1920, 3), np.uint8)
    det.script = {"prompt": ["Investigar", "Ativar"]}
    assert det.update(f, 0.0) == []
    det.script = {"obtained": ["Obtido", "Recurso de Gelo Puro x5", "Morax15000"]}
    assert det.update(f, 3.0) == []
    det.script = {"obtained": ["Obtido", "Mora x 300", "seloCryox3"]}
    assert det.update(f, 20.0) == []
    det.script = {"obtained": ["Obtido", "Mora x10000"]}
    assert det.update(f, 40.0) == []


def test_buried_mora_is_only_a_suggestion() -> None:
    det = RegionScriptedDetector()
    f = np.zeros((1080, 1920, 3), np.uint8)
    det.script = {"prompt": ["Escavar"]}
    assert det.update(f, 0.0) == []
    det.script = {"pickup": ["Mora x2.000"]}
    evs = det.update(f, 2.0)
    assert [(e.kind, e.certain) for e in evs] == [("mora_chest", False)]


def test_recipe_inside_chest_rewards_is_not_a_map_collectable() -> None:
    """Real (07/11): "Receita: Pão de Centeio Glupov" veio na lista de um baú."""
    det = RegionScriptedDetector()
    f = np.zeros((1080, 1920, 3), np.uint8)
    det.script = {
        "obtained": [
            "Obtido", "Gema Essencial x 5", "Mora x300", "Selo Cryo x 2",
            "Receita: Pao de Centeio Glupov x 1",
        ]
    }  # fmt: skip
    assert [e.kind for e in det.update(f, 0.0)] == ["chest"]


def test_sigil_counts_as_chest_drop_after_prompt() -> None:
    det = RegionScriptedDetector()
    f = np.zeros((1080, 1920, 3), np.uint8)
    det.script = {"prompt": ["Bau Comum"]}
    assert det.update(f, 0.0) == []
    det.script = {"obtained": ["Selo Cryo x1"]}
    evs = det.update(f, 1.0)
    assert [(e.kind, e.certain) for e in evs] == [("chest", True)]


def test_respawnables_toggle_specialties_minerals_fishing() -> None:
    f = np.zeros((1080, 1920, 3), np.uint8)
    det_off = RegionScriptedDetector(include_respawnables=False)
    det_off.script = {"pickup": ["Cor Lapis x1", "Pedaço de Cristal x1"]}
    assert det_off.update(f, 0.0) == []

    det_on = RegionScriptedDetector(include_respawnables=True)
    det_on.script = {"pickup": ["Cor Lapis x1"]}
    assert [e.kind for e in det_on.update(f, 0.0)] == ["specialty_cor_lapis"]

    det_on.script = {"pickup": ["Pedaço de Cristal x1"]}
    assert [e.kind for e in det_on.update(f, 5.0)] == ["mineral_crystal"]

    det_on.script = {"prompt": ["Pescar"]}
    assert [e.kind for e in det_on.update(f, 10.0)] == ["fishing_spot"]


def test_cascading_resolver_rarity_and_puzzle_fallback() -> None:
    store = MarkerStore(":memory:")
    store.upsert(
        [
            Marker("c-comum", "chest_common", "teyvat", 100.0, 100.0),
            Marker("c-precioso", "chest_precious", "teyvat", 101.0, 100.0),
            Marker("p-enigma", "mini_puzzle", "teyvat", 500.0, 500.0),
        ]
    )
    cfg = ResolverConfig(radius=20.0)

    r = resolve(store, cfg, "chest", "teyvat", 100.2, 100.0, 0.9, subtype="chest_precious")
    assert r.decision == "mark" and r.marker is not None and r.marker.id == "c-precioso"

    r_puz = resolve(store, cfg, "chest", "teyvat", 501.0, 500.0, 0.9)
    assert r_puz.decision == "mark" and r_puz.marker is not None and r_puz.marker.id == "p-enigma"

    assert "lumenspar" in kinds_for_event("offering")
    assert "teleport" in kinds_for_event("waypoint")


@pytest.fixture(scope="module")
def world() -> np.ndarray:
    return make_map(2400, seed=0)


@pytest.fixture(scope="module")
def index(world: np.ndarray) -> MapIndex:
    return MapIndex.build("teyvat", world)


class MultiCategorySiteBrowser:
    def __init__(self, markers: list[tuple[str, str, float, float, bool]]) -> None:
        self.markers = markers
        self.marked: list[tuple[str, tuple[str, ...]]] = []
        self.last_events: list[str] = []

    def follow(self, lat: float, lng: float, force: bool = False) -> bool:
        _ = lat, lng, force
        return True

    def show_player(self, lat: float, lng: float, confident: bool = True) -> None:
        _ = lat, lng, confident

    def highlight(self, lat: float, lng: float, label: str = "", seconds: float = 20.0) -> None:
        _ = lat, lng, label, seconds

    def mark(self, marker_id: str) -> bool:
        _ = marker_id
        return False

    def set_last_event(self, text: str) -> None:
        self.last_events.append(text)

    def unproject(self, x: float, y: float, zoom: int) -> tuple[float, float]:
        return (-y / 2**zoom, x / 2**zoom)

    def site_categories(self) -> dict[str, tuple[str, ...]]:
        return {
            "chest": ("o17", "o45"),
            "chest_common": ("o17",),
            "chest_precious": ("o45",),
            "time_trial": ("o24",),
            "puzzle_chest": ("o24", "o115"),
            "teleport": ("o3",),
        }

    def nearby_site_markers(
        self,
        gx: float,
        gy: float,
        zoom: int,
        radius: float,
        types: list[str],
        only_visible: bool = False,
    ) -> list:  # type: ignore[type-arg]
        from gmt.web.browser import SiteMarker

        _ = zoom, only_visible
        out = []
        for mid, t, x, y, found in self.markers:
            is_done = found or any(m == mid for m, _ in self.marked)
            d = float(np.hypot(x - gx, y - gy))
            if t in types and d <= radius:
                out.append(SiteMarker(mid, t, d, is_done, x, y))
        return sorted(out, key=lambda m: m.distance)

    def mark_found_ui(self, marker_id: str, expect: tuple[str, ...] = ()) -> str:
        self.marked.append((marker_id, expect))
        return "marked"


class StepEvents:
    def __init__(self, schedule: dict[int, list[CollectEvent]]) -> None:
        self.schedule = schedule
        self.step = 0

    def update(self, _frame: np.ndarray, _t: float) -> list[CollectEvent]:
        self.step += 1
        return self.schedule.get(self.step, [])


def test_app_marks_teleport_precious_chest_and_prevents_challenge_double_mark(
    world: np.ndarray, index: MapIndex
) -> None:
    ox, oy = 50_000.0, 80_000.0
    # Passo 8 -> i=7 (x=1042); Passo 11 -> i=10 (x=1060); Passo 12 -> i=11 (x=1066)
    browser = MultiCategorySiteBrowser(
        [
            ("tp-1", "o3", 1042 + ox, 1000 + oy, False),
            # Em x=1060 há um Baú Comum (o17) e um Baú Precioso (o45) juntos (ambos no raio=5):
            # pela raridade lida ("chest_precious"), o app desempata e marca só o Precioso!
            ("bau-comum-vizinho", "o17", 1059 + ox, 1000 + oy, False),
            ("bau-precioso-alvo", "o45", 1061 + ox, 1000 + oy, False),
            # Em x=1060 o banner "Desafio Concluído" marca tt-1;
            # em x=1066 (fora do raio=5 de bau-comum-vizinho, mas perto de puz-longe),
            # abrir o baú do desafio 0.4s depois NÃO pode marcar puz-longe por engano!
            ("tt-1", "o24", 1060 + ox, 1000 + oy, False),
            ("puz-longe", "o115", 1067 + ox, 1000 + oy, False),
        ]
    )
    conv = TileConverter(browser, {"teyvat": TileLayer(zoom=14, origin_x=ox, origin_y=oy)})
    events = StepEvents(
        {
            8: [CollectEvent("teleport", True, 1.4, ("Ponto de Teleporte desbloqueado",))],
            11: [
                CollectEvent("chest", True, 2.0, ("Gema Essencial",), subtype="chest_precious"),
                CollectEvent("time_trial", True, 2.0, ("Desafio Concluído",)),
            ],
            12: [CollectEvent("chest", True, 2.2, ("EXP do Aventureiro",))],
        }
    )

    console = StatusConsole(io.StringIO())
    app = App(
        Localizer([index]),
        conv,
        console,
        MinimapConfig(169, 125, 100),
        browser=browser,
        store=MarkerStore(":memory:"),
        detector=events,
        options=AppOptions(radius=5, auto_mark_experimental=True),
    )
    for i in range(12):
        app.step(make_game_frame(world, 1000.0 + 6 * i, 1000.0, seed=700 + i), i * 0.2)

    marked_ids = [m for m, _ in browser.marked]
    assert "tp-1" in marked_ids
    assert "bau-precioso-alvo" in marked_ids
    assert "bau-comum-vizinho" not in marked_ids, "desempatou pela raridade lida no OCR!"
    assert "tt-1" in marked_ids
    assert "puz-longe" not in marked_ids, "proteção contra dupla marcação logo após desafio!"
    assert any("ignorando duplicata" in ln for ln in console.lines)
    assert browser.last_events


def test_cli_categories_safety_and_config_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["seguranca"]) == 0
    assert "APROVADA" in capsys.readouterr().out

    assert (
        main(["categorias", "--testar", "Ponto de Teleporte desbloqueado", "Espato Lúmen x1"]) == 0
    )
    out = capsys.readouterr().out
    assert "teleport" in out and "lumenspar" in out

    assert main(["categorias"]) == 0
    assert "Catálogo Genshin Map Tracker" in capsys.readouterr().out

    bad_cfg = tmp_path / "bad.toml"
    bad_cfg.write_text('[detect]\ncategories = ["categoria_inexistente"]\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad_cfg)


def test_experimental_categories_are_only_suggested_by_default(
    world: np.ndarray, index: MapIndex, tmp_path: Path
) -> None:
    """Padrão: teleporte/desafio (não conferidos em sessão real) só são destacados e
    registrados; baú continua sendo marcado sozinho."""
    ox, oy = 50_000.0, 80_000.0
    browser = MultiCategorySiteBrowser(
        [
            ("tp-1", "o3", 1042 + ox, 1000 + oy, False),
            ("bau-precioso-alvo", "o45", 1061 + ox, 1000 + oy, False),
        ]
    )
    conv = TileConverter(browser, {"teyvat": TileLayer(zoom=14, origin_x=ox, origin_y=oy)})
    events = StepEvents(
        {
            8: [CollectEvent("teleport", True, 1.4, ("Ponto de Teleporte desbloqueado",))],
            11: [CollectEvent("chest", True, 2.0, ("Gema Essencial",), subtype="chest_precious")],
        }
    )
    log = tmp_path / "incertos.log"
    app = App(
        Localizer([index]),
        conv,
        StatusConsole(io.StringIO()),
        MinimapConfig(169, 125, 100),
        browser=browser,
        store=MarkerStore(":memory:"),
        detector=events,
        options=AppOptions(radius=5, uncertain_log=log),
    )
    for i in range(12):
        app.step(make_game_frame(world, 1000.0 + 6 * i, 1000.0, seed=700 + i), i * 0.2)
    marked_ids = [m for m, _ in browser.marked]
    assert marked_ids == ["bau-precioso-alvo"]
    assert "tp-1" in log.read_text(encoding="utf-8")
    assert "categoria em teste" in log.read_text(encoding="utf-8")
