"""Loop principal com mapa sintético, navegador falso e detector falso."""

from __future__ import annotations

import io

import numpy as np
import pytest

from gmt.app import App, AppOptions, CalibrationConverter, StatusConsole, TileConverter, TileLayer
from gmt.config import MinimapConfig
from gmt.data.markers import Marker, MarkerStore
from gmt.detect.events import CollectEvent
from gmt.geo.calibration import Calibration, RefPoint
from gmt.localization.localizer import Localizer
from gmt.localization.mapindex import MapIndex

from .synthetic import make_game_frame, make_map


class FakeBrowser:
    def __init__(self, can_mark: bool = False) -> None:
        self.calls: list[tuple] = []  # type: ignore[type-arg]
        self.can_mark = can_mark

    def follow(self, lat: float, lng: float, force: bool = False) -> bool:
        self.calls.append(("follow", lat, lng))
        return True

    def show_player(self, lat: float, lng: float, confident: bool = True) -> None:
        self.calls.append(("player", lat, lng, confident))

    def highlight(self, lat: float, lng: float, label: str = "", seconds: float = 20.0) -> None:
        self.calls.append(("highlight", lat, lng, label))

    def mark(self, marker_id: str) -> bool:
        self.calls.append(("mark", marker_id))
        return self.can_mark

    def unproject(self, x: float, y: float, zoom: int) -> tuple[float, float]:
        return (-y / 2**zoom, x / 2**zoom)


class FakeDetector:
    def __init__(self, at: dict[int, CollectEvent]) -> None:
        self.at = at
        self.n = 0

    def update(self, frame: np.ndarray, t: float) -> list[CollectEvent]:
        self.n += 1
        e = self.at.get(self.n)
        return [e] if e else []


@pytest.fixture(scope="module")
def world() -> np.ndarray:
    return make_map(2400, seed=0)


@pytest.fixture(scope="module")
def index(world: np.ndarray) -> MapIndex:
    return MapIndex.build("teyvat", world)


def site_of(x: float, y: float) -> tuple[float, float]:
    """Site de exemplo: lng = x/4, lat = -y/4 (estilo Leaflet CRS.Simple)."""
    return x / 4, -y / 4


def converter() -> CalibrationConverter:
    pts = [RefPoint(f"p{i}", (x, y), site_of(x, y)) for i, (x, y) in enumerate(
        [(0, 0), (2400, 0), (0, 2400), (1200, 1300)])]  # fmt: skip
    cal = Calibration("teyvat", pts)
    cal.fit()
    return CalibrationConverter({"teyvat": cal})


def run_path(app: App, world: np.ndarray, n: int = 12) -> list:  # type: ignore[type-arg]
    fixes = []
    for i in range(n):
        x, y = 1000.0 + 6 * i, 1000.0
        fixes.append(app.step(make_game_frame(world, x, y, seed=700 + i), i * 0.2))
    return fixes


def test_follows_and_shows_player(world: np.ndarray, index: MapIndex) -> None:
    browser = FakeBrowser()
    out = io.StringIO()
    app = App(Localizer([index]), converter(), StatusConsole(out), MinimapConfig(169, 125, 100),
              browser=browser)  # fmt: skip
    fixes = run_path(app, world)
    assert sum(f.ok for f in fixes) >= 10
    follows = [c for c in browser.calls if c[0] == "follow"]
    assert follows
    lat, lng = follows[-1][1:]
    assert (lng, lat) == pytest.approx(site_of(1000 + 6 * 11, 1000), abs=1.5)
    assert "posição: teyvat" in out.getvalue()


def test_chest_event_marks_single_candidate(world: np.ndarray, index: MapIndex) -> None:
    store = MarkerStore(":memory:")
    lng, lat = site_of(1060, 1002)
    store.upsert(
        [Marker("bau-1", "chest", "teyvat", lng, lat), Marker("bau-far", "chest", "teyvat", 0, 0)]
    )
    browser = FakeBrowser(can_mark=True)
    det = FakeDetector({11: CollectEvent("chest", True, 0.0, ("EXP do Aventureiro",))})
    console = StatusConsole(io.StringIO())
    app = App(
        Localizer([index]),
        converter(),
        console,
        MinimapConfig(169, 125, 100),
        browser=browser,
        store=store,
        detector=det,
        options=AppOptions(radius=10),
    )
    run_path(app, world)
    assert store.found_ids() == {"bau-1"}
    assert ("mark", "bau-1") in browser.calls
    assert any("bau-1 marcado no site" in line for line in console.lines)


def test_ambiguous_event_only_suggests(world: np.ndarray, index: MapIndex) -> None:
    store = MarkerStore(":memory:")
    a, b = site_of(1060, 1000), site_of(1064, 1000)
    store.upsert([Marker("a", "chest", "teyvat", *a), Marker("b", "chest", "teyvat", *b)])
    browser = FakeBrowser()
    det = FakeDetector({11: CollectEvent("chest", True, 0.0, ("Mora",))})
    console = StatusConsole(io.StringIO())
    app = App(
        Localizer([index]),
        converter(),
        console,
        MinimapConfig(169, 125, 100),
        browser=browser,
        store=store,
        detector=det,
        options=AppOptions(radius=10),
    )
    run_path(app, world)
    assert store.found_ids() == set()
    assert len([c for c in browser.calls if c[0] == "highlight"]) == 2
    assert any("confirme no site" in line for line in console.lines)


def test_uncertain_event_never_auto_marks(world: np.ndarray, index: MapIndex) -> None:
    store = MarkerStore(":memory:")
    store.upsert([Marker("bau-1", "chest", "teyvat", *site_of(1060, 1000))])
    det = FakeDetector({11: CollectEvent("chest", False, 0.0, ("Mora",))})
    app = App(
        Localizer([index]),
        converter(),
        StatusConsole(io.StringIO()),
        MinimapConfig(169, 125, 100),
        browser=FakeBrowser(),
        store=store,
        detector=det,
        options=AppOptions(radius=10),
    )
    run_path(app, world)
    assert store.found_ids() == set()


def test_pause_skips_frames(world: np.ndarray, index: MapIndex) -> None:
    browser = FakeBrowser()
    app = App(Localizer([index]), converter(), StatusConsole(io.StringIO()),
              MinimapConfig(169, 125, 100), browser=browser)  # fmt: skip
    app.toggle_pause()
    assert app.step(make_game_frame(world, 1000, 1000), 0.0) is None
    assert browser.calls == []
    app.toggle_pause()
    assert app.step(make_game_frame(world, 1000, 1000), 1.0) is not None


def test_auto_radius_and_tile_converter() -> None:
    conv = TileConverter(FakeBrowser(), {"teyvat": TileLayer(zoom=2, origin_x=100, origin_y=40)})
    assert conv.to_site("teyvat", 0, 0) == pytest.approx((-10.0, 25.0))
    assert conv.to_site("outra", 0, 0) is None


class FakeSiteBrowser(FakeBrowser):
    """Imita o appsample: marcadores lidos da tabela do site, marcação pela interface."""

    def __init__(self, markers: list[tuple[str, str, float, float, bool]]) -> None:
        super().__init__()
        self.markers = markers  # (id, tipo do site, gx, gy, found)
        self.found: set[str] = set()

    def site_categories(self) -> dict[str, tuple[str, ...]]:
        return {"chest": ("o17",), "geoculus": ("o6",)}

    def nearby_site_markers(self, gx, gy, zoom, radius, types):  # type: ignore[no-untyped-def]
        from gmt.web.browser import SiteMarker

        out = []
        for mid, t, x, y, found in self.markers:
            d = float(np.hypot(x - gx, y - gy))
            if t in types and d <= radius:
                out.append(SiteMarker(mid, t, d, found, x, y))
        return sorted(out, key=lambda m: m.distance)

    def mark_found_ui(self, marker_id: str, expect: tuple[str, ...] = ()) -> str:
        self.calls.append(("mark_ui", marker_id))
        self.found.add(marker_id)
        return "marked"

    def site_marker_found(self, marker_id: str) -> bool:
        return marker_id in self.found


def test_site_markers_path(world: np.ndarray, index: MapIndex) -> None:
    ox, oy = 100_000.0, 200_000.0  # origem do mapa base em pixels globais
    path_end = (1000 + 6 * 11 + ox, 1000 + oy)
    browser = FakeSiteBrowser([
        ("bau-perto", "o17", path_end[0] + 1, path_end[1], False),
        ("bau-achado", "o17", path_end[0] - 1, path_end[1], True),  # já encontrado: ignora
        ("geo", "o6", path_end[0], path_end[1], False),  # tipo errado para baú
    ])  # fmt: skip
    conv = TileConverter(browser, {"teyvat": TileLayer(zoom=14, origin_x=ox, origin_y=oy)})
    store = MarkerStore(":memory:")
    det = FakeDetector({12: CollectEvent("chest", True, 0.0, ("exp do aventureiro",))})
    console = StatusConsole(io.StringIO())
    app = App(
        Localizer([index]),
        conv,
        console,
        MinimapConfig(169, 125, 100),
        browser=browser,
        store=store,
        detector=det,
        options=AppOptions(radius=10),
    )
    run_path(app, world)
    assert ("mark_ui", "bau-perto") in browser.calls
    assert store.found_ids() == {"bau-perto"}
    assert any("bau-perto: marcado no site" in line for line in console.lines)


def test_uncertain_case_marks_after_timeout(world, index, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Sem confirmação no prazo, marca o mais provável e registra como incerto."""
    ox, oy = 100_000.0, 200_000.0
    end = (1000 + 6 * 11 + ox, 1000 + oy)
    browser = FakeSiteBrowser([
        ("perto", "o17", end[0] + 1, end[1], False),
        ("vizinho", "o17", end[0] + 3, end[1], False),
    ])  # fmt: skip
    conv = TileConverter(browser, {"teyvat": TileLayer(zoom=14, origin_x=ox, origin_y=oy)})
    det = FakeDetector({12: CollectEvent("chest", True, 0.0, ("exp do aventureiro",))})
    log = tmp_path / "incertos.log"
    opts = AppOptions(radius=10, confirm_timeout=0.0, uncertain_log=log)
    app = App(
        Localizer([index]),
        conv,
        StatusConsole(io.StringIO()),
        MinimapConfig(169, 125, 100),
        browser=browser,
        store=MarkerStore(":memory:"),
        detector=det,
        options=opts,
    )
    run_path(app, world)
    assert ("mark_ui", "perto") in browser.calls
    text = log.read_text(encoding="utf-8")
    assert "marcado sem confirmação" in text and "perto" in text


def test_pauses_when_minimap_hidden(world: np.ndarray, index: MapIndex) -> None:
    """Mapa grande ou menu aberto: sem a seta no centro do minimapa, não localiza."""
    browser = FakeBrowser()
    console = StatusConsole(io.StringIO())
    app = App(Localizer([index]), converter(), console, MinimapConfig(169, 125, 100),
              browser=browser)  # fmt: skip
    frame = make_game_frame(world, 1000, 1000)
    hidden = frame.copy()
    hidden[95:156, 139:200] = 120  # cobre a seta do centro (como quando o mapa grande abre)
    assert app.step(hidden, 0.0) is None
    assert browser.calls == []
    assert any("minimapa oculto" in line for line in console.lines)
    assert app.step(frame, 1.0) is not None
    assert any("minimapa de volta" in line for line in console.lines)


def test_pending_is_resolved_while_game_unfocused(world, index, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Com dúvida, a pessoa vai olhar o mapa no outro monitor (jogo sem foco): o prazo
    tem que correr e o baú ser marcado mesmo sem quadros do jogo."""
    ox, oy = 100_000.0, 200_000.0
    end = (1000 + 6 * 11 + ox, 1000 + oy)
    browser = FakeSiteBrowser([
        ("perto", "o17", end[0] + 1, end[1], False),
        ("vizinho", "o17", end[0] + 1.5, end[1], False),  # quase no mesmo lugar: dúvida
    ])  # fmt: skip
    conv = TileConverter(browser, {"teyvat": TileLayer(zoom=14, origin_x=ox, origin_y=oy)})
    det = FakeDetector({12: CollectEvent("chest", True, 0.0, ("exp do heroi",))})
    log = tmp_path / "incertos.log"
    opts = AppOptions(radius=10, confirm_timeout=0.2, uncertain_log=log)
    app = App(
        Localizer([index]),
        conv,
        StatusConsole(io.StringIO()),
        MinimapConfig(169, 125, 100),
        browser=browser,
        store=MarkerStore(":memory:"),
        detector=det,
        options=opts,
    )
    run_path(app, world)  # jogando: o baú é detectado e fica em dúvida
    assert not any(c[0] == "mark_ui" for c in browser.calls)

    def unfocused():  # type: ignore[no-untyped-def]
        import time as _t

        for _ in range(5):  # jogo fora de foco: só "ticks" vazios
            _t.sleep(0.1)
            yield None, None

    app.run(unfocused())
    assert ("mark_ui", "perto") in browser.calls
    assert "marcado sem confirmação" in log.read_text(encoding="utf-8")


def test_grabber_idle_ticks() -> None:
    from gmt.capture.grabber import CaptureStats, frames_with_idle

    from .test_grabber import FakeBackend, _window

    stats = CaptureStats()
    got = list(frames_with_idle(FakeBackend(), lambda: _window(foreground=False), 20, stats, 1.2))
    assert got and all(f is None for f, _ in got)
    assert 1 <= len(got) <= 2  # no máximo 1 por segundo
