"""Comandos das Fases 3 a 6 e novos utilitários de categorias e segurança anti-ban."""

from __future__ import annotations

import argparse
import json
import logging
import time
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
    from gmt.capture.grabber import CaptureStats, frames_with_idle
    from gmt.capture.window import UnsupportedPlatformError, find_game_window
    from gmt.data.markers import MarkerStore
    from gmt.geo.calibration import Calibration
    from gmt.hotkey import GlobalHotkey
    from gmt.localization.localizer import Localizer, LocalizerConfig
    from gmt.localization.mapindex import MapIndex
    from gmt.safety import audit_source_tree

    safety = audit_source_tree()
    if not safety.ok:
        log.error("%s", safety.summary())
        return 2

    if not cfg.maps:
        print("Nenhum mapa base configurado. Veja a seção [[maps]] em config.example.toml.")
        return 2

    _reset_session_files(cfg.capture.output_dir)
    _debug_log(cfg.capture.output_dir / "localizacao.log")
    console = StatusConsole(log_file=cfg.capture.output_dir / "acoes.log")
    console.info("Genshin Map Tracker: só lê a tela; nada é enviado ao jogo.")
    console.info(safety.summary())

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
                compact=s.compact,
                window=s.window,
                controls=s.controls,
                fail_dir=cfg.capture.output_dir / "falhas",
            ),
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

    include_respawn = bool(cfg.detect.include_respawnables or getattr(args, "respawnables", False))
    detector = None
    if cfg.detect.enabled:
        from gmt.detect.events import CollectDetector, DetectorConfig, RapidOcr, ThreadedDetector

        try:
            det_cfg = DetectorConfig(
                include_respawnables=include_respawn,
                enabled_groups=cfg.detect.categories,
            )
            detector = ThreadedDetector(
                CollectDetector(
                    RapidOcr(), config=det_cfg, record_dir=cfg.capture.output_dir / "ocr"
                )
            )
            mode_txt = (
                "permanentes + farmáveis" if include_respawn else "todos os objetos permanentes"
            )
            console.info(f"detector ativo: {mode_txt}")
        except RuntimeError as exc:
            console.info(f"detecção de coleta desligada: {exc}")

    store = MarkerStore(cfg.database)
    if store.count() == 0 and browser is None:
        console.info("banco de marcadores vazio: a coleta será só avisada, não marcada.")

    app = App(
        Localizer(indexes, LocalizerConfig(contours=cfg.localization.contours)),
        converter,
        console,
        cfg.minimap,
        browser=browser,
        store=store,
        detector=detector,
        options=AppOptions(
            follow=cfg.site.follow,
            auto_mark=cfg.detect.auto_mark,
            radius=cfg.detect.radius,
            lost_dir=cfg.capture.output_dir / "perdido",
            uncertain_log=cfg.capture.output_dir / "incertos.log",
            puzzle_fallback=cfg.detect.puzzle_fallback,
            only_visible_on_site=cfg.detect.only_visible_on_site,
            auto_mark_experimental=cfg.detect.auto_mark_experimental,
        ),
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
    if win.is_minimized or not win.is_foreground:
        console.info("volte para o jogo (Alt+Tab): a captura começa quando ele estiver em foco")
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            time.sleep(0.5)
            now = find_game_window()
            if now is not None and not now.is_minimized and now.is_foreground:
                time.sleep(1.5)
                win = find_game_window() or now
                break
    try:
        backend = create_backend(cfg.capture.backend, win.client)
    except CaptureError as exc:
        log.error("Falha ao iniciar captura: %s", exc)
        return 2

    console.info(f"capturando com {backend.name} a {cfg.capture.fps:g} FPS. Ctrl+C para sair.")
    stats = CaptureStats()
    try:
        app.run(frames_with_idle(backend, find_game_window, cfg.capture.fps, stats, args.seconds))
    except KeyboardInterrupt:
        console.info("encerrado pelo usuário.")
    except Exception:
        import traceback

        err = cfg.capture.output_dir / "erro.log"
        err.write_text(traceback.format_exc(), encoding="utf-8")
        console.info(f"ERRO inesperado; detalhes em {err}")
        log.exception("Erro inesperado")
    finally:
        import contextlib

        for close in (
            backend.close,
            hotkey.stop,
            store.close,
            detector.close if detector is not None else None,
            browser.close if browser is not None else None,
        ):
            if close is not None:
                with contextlib.suppress(Exception):
                    close()
    console.info(f"CPU média do app: {stats.avg_cpu:.1f}% de um núcleo")
    cmd_package(args, cfg)
    return 0


SESSION_FILES = (
    "acoes.log",
    "incertos.log",
    "localizacao.log",
    "erro.log",
    "ocr",
    "perdido",
    "falhas",
)


def _debug_log(path: Path) -> None:
    root = logging.getLogger()
    for h in root.handlers:
        if h.level == logging.NOTSET:
            h.setLevel(root.level)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    for name in ("gmt.localization.localizer", "gmt.app"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.DEBUG)
        lg.addHandler(handler)


def _reset_session_files(out: Path) -> None:
    import shutil

    for name in SESSION_FILES:
        path = out / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()


def cmd_package(_args: argparse.Namespace, cfg: Config) -> int:
    import zipfile

    out = cfg.capture.output_dir
    zip_path = out / f"sessao_{time.strftime('%Y%m%d-%H%M%S')}.zip"
    files = [out / n for n in SESSION_FILES] + [Path("config.toml")]
    count = 0
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            items = sorted(f.rglob("*")) if f.is_dir() else [f]
            for item in items:
                if item.is_file():
                    zf.write(item, item.relative_to(f.parent))
                    count += 1
    print(f"\nPacote da sessão ({count} arquivos): {zip_path.resolve()}")
    print("Mande esse arquivo .zip.")
    from gmt.diagnostics import _show_in_explorer

    _show_in_explorer(zip_path)
    return 0


# -------------------------------------------------------- import-markers / progress


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
    elif args.action == "stats":
        stats = store.summary_by_kind()
        if not stats:
            print("Nenhum marcador cadastrado no banco local.")
        for kind, (done, total) in stats.items():
            pct = (done / total * 100.0) if total else 0.0
            print(f"  {kind:28s} {done:4d}/{total:<4d} ({pct:5.1f}%)")
    else:
        print(f"{store.import_progress(Path(args.file))} itens importados de {args.file}")
    store.close()
    return 0


# ----------------------------------------------------------- detect-test


def cmd_detect_test(args: argparse.Namespace, cfg: Config) -> int:
    """OCR na tela inteira de cada print: mostra onde aparece cada texto e o que seria detectado."""
    from gmt.detect.events import (
        BANNER_REGION,
        OBTAINED_REGION,
        PICKUP_REGION,
        PROMPT_REGION,
        CollectDetector,
        DetectorConfig,
        RapidOcr,
    )

    try:
        ocr = RapidOcr()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2

    det = CollectDetector(
        ocr,
        DetectorConfig(
            include_respawnables=True,
            min_interval=0.0,
            cooldown=0.0,
            chest_cooldown=0.0,
        ),
    )
    results = []
    for idx, name in enumerate(args.images):
        img = cv2.imdecode(np.fromfile(name, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print(f"{name}: não abriu")
            continue
        frame = np.asarray(img, np.uint8)
        boxes = ocr.read_boxes(frame)
        events = det.update(frame, float(idx * 2.0))
        debug = frame.copy()
        h, w = frame.shape[:2]
        regions = (
            (PROMPT_REGION, (0, 200, 255)),
            (PICKUP_REGION, (255, 120, 0)),
            (OBTAINED_REGION, (0, 255, 120)),
            (BANNER_REGION, (255, 0, 200)),
        )
        for region, color in regions:
            x0, y0, x1, y1 = region.rect(w, h)
            cv2.rectangle(debug, (x0, y0), (x1, y1), color, 2)
        print(f"\n{Path(name).name}:")
        for box, text, score in boxes:
            pts = np.array(box, dtype=np.int32)
            cv2.polylines(debug, [pts], True, (0, 255, 0), 1)
            x0, y0b = pts.min(axis=0)
            print(f"  ({x0:4d},{y0b:4d}) {score:.2f}  {text}")
        for ev in events:
            print(
                f"  -> DETECTADO: kind={ev.kind} subtype={ev.subtype} "
                f"context={ev.context} certain={ev.certain} evidence={ev.evidence}"
            )
        out = Path(name).with_suffix("").as_posix() + "_ocr.png"
        ok, buf = cv2.imencode(".png", debug)
        if ok:
            buf.tofile(out)
        results.append(
            {
                "image": name,
                "boxes": [{"box": b, "text": t, "score": s} for b, t, s in boxes],
                "events": [
                    {
                        "kind": e.kind,
                        "subtype": e.subtype,
                        "context": e.context,
                        "certain": e.certain,
                        "evidence": list(e.evidence),
                    }
                    for e in events
                ],
            }
        )
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    _ = cfg
    print(f"\nTextos salvos em {args.out}; imagens *_ocr.png mostram as 4 regiões monitoradas.")
    return 0


# ----------------------------------------------------- categorias & seguranca


def cmd_categories(args: argparse.Namespace, _cfg: Config) -> int:
    """Lista todas as categorias interativas suportadas ou testa frases simuladas de OCR."""
    from gmt.data.catalog import ALL_SPECS, PERMANENT_KINDS, RESPAWNABLE_KINDS, label_for_kind
    from gmt.detect.events import CollectDetector, DetectorConfig

    if args.testar:

        class _StaticOcr:
            def __init__(self, lines: list[str]) -> None:
                self._lines = lines

            def read(self, _img: Any) -> list[str]:
                return self._lines

        det = CollectDetector(
            _StaticOcr([]),
            DetectorConfig(
                include_respawnables=True, min_interval=0.0, cooldown=0.0, chest_cooldown=0.0
            ),
        )
        dummy = np.full((1080, 1920, 3), 50, np.uint8)
        for i, phrase in enumerate(args.testar):
            det.engine = _StaticOcr([phrase])
            dummy[:] = (50 + 40 * (i + 1)) % 250
            evs = det.update(dummy, float(i * 2.0))
            if not evs:
                print(f"'{phrase}' -> contexto registrado ou sem coleta direta")
            for e in evs:
                lbl = label_for_kind(e.kind, e.subtype)
                print(
                    f"'{phrase}' -> {lbl} (kind={e.kind}, subtype={e.subtype}, "
                    f"context={e.context}, certain={e.certain})"
                )
        return 0

    by_group: dict[str, list[str]] = {}
    for spec in ALL_SPECS:
        tag = "permanente" if spec.permanent else "respawnável"
        by_group.setdefault(spec.group, []).append(f"{spec.kind} ({spec.label_pt}) [{tag}]")

    print(
        f"Catálogo Genshin Map Tracker: {len(ALL_SPECS)} definições "
        f"({len(PERMANENT_KINDS)} permanentes + {len(RESPAWNABLE_KINDS)} respawnáveis)\n"
    )
    for grp, items in by_group.items():
        print(f"[{grp.upper()}] ({len(items)})")
        preview = items if args.all else items[:12]
        for it in preview:
            print(f"  - {it}")
        if not args.all and len(items) > 12:
            print(f"  ... e mais {len(items) - 12} (use --all para listar todos)")
    return 0


def cmd_safety(_args: argparse.Namespace, _cfg: Config) -> int:
    """Executa auditoria estática e em tempo de execução das garantias anti-ban."""
    from gmt.safety import audit_source_tree

    rep = audit_source_tree()
    print(rep.summary())
    if not rep.ok:
        for v in rep.violations:
            print(f"  ! {v}")
        return 1
    print("  - Captura: somente imagem da área de trabalho (dxcam / mss, igual ao OBS).")
    print(
        "  - Memória/DLL/Rede: zero handle aberto no processo do jogo, zero injeção, zero sniffer."
    )
    print("  - Entrada/Overlay: zero tecla/clique enviado ao jogo, zero janela sobreposta.")
    print("  - Automação: restrita ao navegador Chrome isolado no mapa web externo.")
    return 0


# ----------------------------------------------------------------- tiles


def cmd_tiles(args: argparse.Namespace, _cfg: Config) -> int:
    from gmt.web.tiles import TileJob, download_tiles, estimate, stitch

    job = TileJob(
        args.template,
        args.zoom,
        args.x_min,
        args.x_max,
        args.y_min,
        args.y_max,
        args.tile_size,
    )
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


# --------------------------------------------------------- preparar-mapa


def cmd_prepare_map(args: argparse.Namespace, _cfg: Config) -> int:
    from gmt.web.prepare import add_to_config, build_map, plan_map
    from gmt.web.siteconfig import SiteConfigError

    try:
        plan = plan_map(args.mapa, args.zoom, Path(args.out))
    except (SiteConfigError, OSError) as exc:
        log.error("Não deu para ler o site do mapa: %s", exc)
        return 2
    minutes = plan.job.count * (args.delay + 0.5) / 60
    print(f"Mapa: {plan.summary}")
    print(f"Tempo estimado: ~{minutes:.0f} min (ritmo calmo, como navegar no mapa).")
    print("Os tiles ficam só no seu PC, para uso pessoal.")
    if not args.yes and input("Continuar? [s/N] ").strip().lower() not in ("s", "sim", "y"):
        print("Cancelado.")
        return 0
    meta = build_map(plan, Path(args.cache), delay=args.delay)
    config = Path(args.config) if args.config else Path("config.toml")
    if add_to_config(config, plan.site_map.key, plan.image, meta):
        print(f"Camada '{plan.site_map.key}' adicionada em {config}.")
    return 0


# -------------------------------------------------------------- parsers


def register(sub: Any) -> dict[str, Any]:
    run = sub.add_parser("run", help="app completo: rastreia, segue no site e marca coletas")
    run.add_argument("--seconds", type=float, help="para depois de N segundos")
    run.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    run.add_argument(
        "--respawnables",
        action="store_true",
        help="ativa também Especialidades Locais, Minérios e Pontos de Pesca",
    )

    im = sub.add_parser("import-markers", help="importa marcadores de um JSON")
    im.add_argument("file")
    im.add_argument("--mapping", help="JSON com os campos (ver gmt.data.markers.ImportMapping)")

    pg = sub.add_parser("progress", help="exporta/importa/resume o progresso")
    pg.add_argument("action", choices=["export", "import", "stats"])
    pg.add_argument("file", nargs="?", default="progresso.json")

    dt = sub.add_parser("detect-test", help="OCR em prints para calibrar as regiões de texto")
    dt.add_argument("images", nargs="+")
    dt.add_argument("--out", default="ocr_textos.json")

    cats = sub.add_parser("categorias", help="lista objetos interativos suportados ou testa textos")
    cats.add_argument(
        "--all", action="store_true", help="mostra todas as especialidades e minérios"
    )
    cats.add_argument("--testar", nargs="+", help="testa classificação de frases simuladas de OCR")

    sub.add_parser("seguranca", help="executa auditoria anti-ban (zero injeção/memória/input)")

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

    sub.add_parser("pacote", help="junta os registros da última sessão num zip")
    from gmt.web.siteconfig import MAP_PATHS

    pm = sub.add_parser("preparar-mapa", help="monta o mapa base com os tiles do site (uma vez)")
    pm.add_argument("--mapa", default="teyvat", choices=sorted(MAP_PATHS))
    pm.add_argument("--zoom", type=int, default=14)
    pm.add_argument("--delay", type=float, default=0.3, help="segundos entre downloads")
    pm.add_argument("--out", default="mapas")
    pm.add_argument("--cache", default="out/tiles_cache")
    pm.add_argument("--yes", action="store_true", help="não pergunta antes de baixar")

    dg = sub.add_parser("diagnostico", help="teste único: junta tudo num zip para enviar")
    dg.add_argument("--seconds", type=float, default=45.0, help="duração da captura")
    dg.add_argument("--no-site", action="store_true", help="pula o diagnóstico do site")

    return {
        "run": cmd_run,
        "import-markers": cmd_import_markers,
        "progress": cmd_progress,
        "detect-test": cmd_detect_test,
        "categorias": cmd_categories,
        "seguranca": cmd_safety,
        "tiles": cmd_tiles,
        "diagnostico": cmd_diagnostico,
        "preparar-mapa": cmd_prepare_map,
        "pacote": cmd_package,
    }
