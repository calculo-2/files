"""Comandos das Fases 3 a 6: run, import-markers, detect-test, tiles."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from gmt.config import Config

log = logging.getLogger("gmt")


# ------------------------------------------------------------------ run


def cmd_run(args: argparse.Namespace, cfg: Config) -> int:
    from gmt.app import (
        App,
        AppOptions,
        CalibrationConverter,
        ChainConverter,
        StatusConsole,
        TileConverter,
        TileLayer,
    )
    from gmt.capture.backends import CaptureError, create_backend
    from gmt.capture.grabber import CaptureStats, frames
    from gmt.capture.window import UnsupportedPlatformError, find_game_window
    from gmt.data.markers import MarkerStore
    from gmt.geo.calibration import Calibration
    from gmt.hotkey import GlobalHotkey
    from gmt.localization.localizer import Localizer
    from gmt.localization.mapindex import MapIndex

    if not cfg.maps:
        print("Nenhum mapa base configurado. Veja a seção [[maps]] em config.example.toml.")
        return 2

    console = StatusConsole(log_file=cfg.capture.output_dir / "acoes.log")
    console.info("Genshin Map Tracker: só lê a tela; nada é enviado ao jogo.")
    indexes = [MapIndex.from_file(m.image, name=m.layer) for m in cfg.maps]
    calibrations = {
        m.layer: Calibration.load(m.calibration) for m in cfg.maps if m.calibration is not None
    }
    tile_layers = {
        m.layer: TileLayer(m.tile_zoom, m.tile_origin_x, m.tile_origin_y)
        for m in cfg.maps
        if m.tile_zoom is not None
    }

    browser = None
    if cfg.site.follow and not args.no_browser:
        from gmt.web.browser import BrowserConfig, BrowserError, MapBrowser

        s = cfg.site
        browser = MapBrowser(
            BrowserConfig(
                url=s.url,
                profile=s.profile,
                min_interval=s.min_interval,
                min_pan_px=s.min_pan_px,
                zoom=s.zoom,
                mark_js=s.mark_js,
            ),  # fmt: skip
            sink=console,
        )
        try:
            browser.open()
        except BrowserError as exc:
            console.info(f"navegador indisponível: {exc}")
            browser = None

    converters: list[Any] = [CalibrationConverter(calibrations)]
    if browser is not None and tile_layers:
        converters.insert(0, TileConverter(browser, tile_layers))
    converter = ChainConverter(*converters)

    detector = None
    if cfg.detect.enabled:
        from gmt.detect.events import CollectDetector, RapidOcr, ThreadedDetector

        try:
            detector = ThreadedDetector(CollectDetector(RapidOcr()))
        except RuntimeError as exc:
            console.info(f"detecção de coleta desligada: {exc}")

    store = MarkerStore(cfg.database)
    if store.count() == 0:
        console.info("banco de marcadores vazio: a coleta será só avisada, não marcada.")

    app = App(
        Localizer(indexes),
        converter,
        console,
        cfg.minimap,
        browser=browser,
        store=store,
        detector=detector,
        options=AppOptions(
            follow=cfg.site.follow, auto_mark=cfg.detect.auto_mark, radius=cfg.detect.radius
        ),  # fmt: skip
    )
    hotkey = GlobalHotkey(cfg.pause_hotkey, app.toggle_pause)
    if hotkey.start():
        console.info(f"atalho de pausa: {cfg.pause_hotkey}")

    try:
        win = find_game_window()
    except UnsupportedPlatformError as exc:
        log.error("%s", exc)
        return 2
    if win is None:
        print("Jogo NÃO encontrado. Abra o Genshin Impact e tente de novo.")
        return 1
    try:
        backend = create_backend(cfg.capture.backend, win.client)
    except CaptureError as exc:
        log.error("Falha ao iniciar captura: %s", exc)
        return 2

    console.info(f"capturando com {backend.name} a {cfg.capture.fps:g} FPS. Ctrl+C para sair.")
    stats = CaptureStats()
    try:
        app.run(frames(backend, find_game_window, cfg.capture.fps, stats, args.seconds))
    except KeyboardInterrupt:
        console.info("encerrado pelo usuário.")
    finally:
        backend.close()
        hotkey.stop()
        if detector is not None:
            detector.close()
        if browser is not None:
            browser.close()
        store.close()
    console.info(f"CPU média do app: {stats.avg_cpu:.1f}% de um núcleo")
    return 0


# -------------------------------------------------------- import-markers


def cmd_import_markers(args: argparse.Namespace, cfg: Config) -> int:
    from gmt.data.markers import ImportMapping, MarkerStore, parse_markers

    mapping = ImportMapping()
    if args.mapping:
        mapping = ImportMapping(**json.loads(Path(args.mapping).read_text(encoding="utf-8")))
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    markers = parse_markers(data, mapping)
    store = MarkerStore(cfg.database)
    n = store.upsert(markers, source=Path(args.file).name)
    kinds: dict[str, int] = {}
    for m in markers:
        kinds[m.kind] = kinds.get(m.kind, 0) + 1
    print(f"{n} marcadores importados para {cfg.database}: {kinds}")
    store.close()
    return 0


def cmd_progress(args: argparse.Namespace, cfg: Config) -> int:
    from gmt.data.markers import MarkerStore

    store = MarkerStore(cfg.database)
    if args.action == "export":
        print(f"{store.export_progress(Path(args.file))} itens exportados para {args.file}")
    else:
        print(f"{store.import_progress(Path(args.file))} itens importados de {args.file}")
    store.close()
    return 0


# ----------------------------------------------------------- detect-test


def cmd_detect_test(args: argparse.Namespace, _cfg: Config) -> int:
    """OCR na tela inteira de cada print: mostra onde aparece cada texto."""
    from gmt.detect.events import PICKUP_REGION, PROMPT_REGION, RapidOcr

    try:
        ocr = RapidOcr()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    results = []
    for name in args.images:
        img = cv2.imdecode(np.fromfile(name, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print(f"{name}: não abriu")
            continue
        boxes = ocr.read_boxes(np.asarray(img, np.uint8))
        debug = img.copy()
        h, w = img.shape[:2]
        for region, color in ((PROMPT_REGION, (0, 200, 255)), (PICKUP_REGION, (255, 120, 0))):
            x0, y0, x1, y1 = region.rect(w, h)
            cv2.rectangle(debug, (x0, y0), (x1, y1), color, 2)
        print(f"\n{Path(name).name}:")
        for box, text, score in boxes:
            pts = np.array(box, dtype=np.int32)
            cv2.polylines(debug, [pts], True, (0, 255, 0), 1)
            x0, y0b = pts.min(axis=0)
            print(f"  ({x0:4d},{y0b:4d}) {score:.2f}  {text}")
        out = Path(name).with_suffix("").as_posix() + "_ocr.png"
        ok, buf = cv2.imencode(".png", debug)
        if ok:
            buf.tofile(out)
        results.append(
            {"image": name, "boxes": [{"box": b, "text": t, "score": s} for b, t, s in boxes]}
        )
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTextos salvos em {args.out}; imagens *_ocr.png mostram as regiões (laranja/azul).")
    return 0


# ----------------------------------------------------------------- tiles


def cmd_tiles(args: argparse.Namespace, _cfg: Config) -> int:
    from gmt.web.tiles import TileJob, download_tiles, estimate, stitch

    job = TileJob(args.template, args.zoom, args.x_min, args.x_max, args.y_min, args.y_max,
                  args.tile_size)  # fmt: skip
    print(estimate(job))
    if not args.yes:
        print("Nada baixado. Leia os termos de uso do site e rode de novo com --yes.")
        return 0
    cache = Path(args.cache)
    got = download_tiles(job, cache, delay=args.delay, max_tiles=args.max_tiles, confirm=True)
    print(f"{got} tiles baixados agora (o resto já estava em cache).")
    meta = stitch(job, cache, Path(args.out))
    print(f"Mapa salvo em {args.out}; dados de origem em {meta}.")
    return 0


# -------------------------------------------------------------- parsers


def register(sub: Any) -> dict[str, Any]:
    run = sub.add_parser("run", help="app completo: rastreia, segue no site e marca coletas")
    run.add_argument("--seconds", type=float, help="para depois de N segundos")
    run.add_argument("--no-browser", action="store_true", help="não abre o navegador")

    im = sub.add_parser("import-markers", help="importa marcadores de um JSON")
    im.add_argument("file")
    im.add_argument("--mapping", help="JSON com os campos (ver gmt.data.markers.ImportMapping)")

    pg = sub.add_parser("progress", help="exporta/importa o progresso em JSON")
    pg.add_argument("action", choices=["export", "import"])
    pg.add_argument("file")

    dt = sub.add_parser("detect-test", help="OCR em prints para calibrar as regiões de texto")
    dt.add_argument("images", nargs="+")
    dt.add_argument("--out", default="ocr_textos.json")

    tl = sub.add_parser("tiles", help="monta o mapa base com os tiles do site (ver termos!)")
    tl.add_argument("--template", required=True, help="ex.: https://.../{z}/{x}/{y}.webp")
    tl.add_argument("--zoom", type=int, required=True)
    for k in ("x-min", "x-max", "y-min", "y-max"):
        tl.add_argument(f"--{k}", type=int, required=True)
    tl.add_argument("--tile-size", type=int, default=256)
    tl.add_argument("--delay", type=float, default=1.0, help="segundos entre downloads")
    tl.add_argument("--max-tiles", type=int, default=3000)
    tl.add_argument("--cache", default="out/tiles_cache")
    tl.add_argument("--out", default="mapas/teyvat.png")
    tl.add_argument("--yes", action="store_true", help="confirma o download")

    from gmt.diagnostics import cmd_diagnostico

    dg = sub.add_parser("diagnostico", help="teste único: junta tudo num zip para enviar")
    dg.add_argument("--seconds", type=float, default=45.0, help="duração da captura")
    dg.add_argument("--no-site", action="store_true", help="pula o diagnóstico do site")

    return {
        "run": cmd_run,
        "import-markers": cmd_import_markers,
        "progress": cmd_progress,
        "detect-test": cmd_detect_test,
        "tiles": cmd_tiles,
        "diagnostico": cmd_diagnostico,
    }
