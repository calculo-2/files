"""Linha de comando: `gmt <comando>`.

Comandos da Fase 1:
  find-window   mostra se o jogo foi encontrado e a área de captura
  capture       captura o jogo, salva quadros e minimapas, mede FPS e CPU
  crop          recorta o minimapa de um print salvo (sem o jogo aberto)
  calibrate     sugere a posição exata do minimapa a partir de um print
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from gmt import __version__
from gmt.config import Config, ConfigError, load_config
from gmt.logging_setup import setup_logging
from gmt.vision.minimap import Image, calibrate_center, crop_minimap, draw_debug
from gmt.vision.regions import minimap_circle, to_reference

log = logging.getLogger("gmt")


def _imread(path: Path) -> Image:
    # cv2.imread falha com acentos no caminho no Windows; lê por bytes.

    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Não foi possível abrir a imagem: {path}")
    return np.asarray(img, np.uint8)


def _imwrite(path: Path, img: Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        raise OSError(f"Falha ao codificar {path}")
    buf.tofile(str(path))


def cmd_find_window(_args: argparse.Namespace, cfg: Config) -> int:
    from gmt.capture.window import UnsupportedPlatformError, find_game_window

    try:
        win = find_game_window()
    except UnsupportedPlatformError as exc:
        log.error("%s", exc)
        return 2
    if win is None:
        print("Jogo NÃO encontrado. Abra o Genshin Impact e tente de novo.")
        return 1
    c = win.client
    print(f"Jogo encontrado: '{win.title}'")
    print(f"  Área de captura: {c.width}x{c.height} em ({c.left}, {c.top})")
    print(f"  Em foco: {'sim' if win.is_foreground else 'não'}")
    print(f"  Minimizado: {'sim' if win.is_minimized else 'não'}")

    from gmt.capture.backends import create_backend

    backend = create_backend(cfg.capture.backend, win.client)
    print(f"  Método de captura: {backend.name}")
    backend.close()
    return 0


def cmd_capture(args: argparse.Namespace, cfg: Config) -> int:
    from gmt.capture.backends import CaptureError, create_backend
    from gmt.capture.grabber import CaptureStats, frames
    from gmt.capture.window import UnsupportedPlatformError, find_game_window

    try:
        win = find_game_window()
    except UnsupportedPlatformError as exc:
        log.error("%s", exc)
        return 2
    if win is None:
        print("Jogo NÃO encontrado. Abra o Genshin Impact e tente de novo.")
        return 1

    backend_kind = args.backend or cfg.capture.backend
    fps = args.fps or cfg.capture.fps
    out_dir = Path(args.out) if args.out else cfg.capture.output_dir
    run_dir = out_dir / time.strftime("%Y%m%d-%H%M%S")

    try:
        backend = create_backend(backend_kind, win.client)
    except CaptureError as exc:
        log.error("Falha ao iniciar captura: %s", exc)
        return 2

    if args.delay > 0:
        print(f"Volte para o jogo. Captura começa em {args.delay:.0f}s...")
        time.sleep(args.delay)

    print(f"Capturando {args.seconds:.0f}s a {fps:g} FPS com {backend.name}. Saída: {run_dir}")
    stats = CaptureStats()
    try:
        for frame, rect in frames(backend, find_game_window, fps, stats, args.seconds):
            if args.no_save:
                continue
            n = stats.frames
            circle = minimap_circle(rect.width, rect.height, cfg.minimap)
            mm = crop_minimap(frame, circle)
            _imwrite(run_dir / "minimap" / f"{n:05d}.png", mm.with_alpha())
            if n == 1 or n % args.frame_every == 0:
                _imwrite(run_dir / "frames" / f"{n:05d}.png", frame)
                _imwrite(run_dir / "debug" / f"{n:05d}.png", draw_debug(frame, circle))
    except KeyboardInterrupt:
        print("Interrompido.")
    finally:
        backend.close()

    print("\nResumo")
    print(f"  Quadros capturados: {stats.frames}")
    print(f"  FPS real: {stats.real_fps:.1f} (alvo {fps:g})")
    print(f"  CPU média do app: {stats.avg_cpu:.1f}% de um núcleo")
    print(f"  Quadros pretos: {stats.black_frames}")
    print(f"  Pulados (jogo fora de foco/minimizado): {stats.skipped_not_focused}")
    if stats.frames and stats.black_frames == stats.frames:
        print("  ATENÇÃO: todos os quadros pretos. Tente --backend dxcam ou modo janela sem borda.")
    if not args.no_save:
        print("  Obs.: salvar PNG aumenta a CPU; meça com --no-save para o valor real.")
    return 0


def cmd_crop(args: argparse.Namespace, cfg: Config) -> int:
    img = _imread(Path(args.image))
    h, w = img.shape[:2]
    circle = minimap_circle(w, h, cfg.minimap)
    mm = crop_minimap(img, circle)
    out = Path(args.out) if args.out else Path(args.image).with_suffix("")
    _imwrite(out.with_name(out.name + "_minimap.png"), mm.with_alpha())
    _imwrite(out.with_name(out.name + "_debug.png"), draw_debug(img, circle))
    print(f"Resolução {w}x{h}. Minimapa em ({circle.cx:.0f}, {circle.cy:.0f}) r={circle.r:.0f}")
    print(f"Salvo: {out.name}_minimap.png e {out.name}_debug.png")
    return 0


def cmd_calibrate(args: argparse.Namespace, cfg: Config) -> int:
    paths = [Path(p) for p in args.images]
    imgs = [_imread(p) for p in paths]
    sizes = {img.shape[:2] for img in imgs}
    if len(sizes) > 1:
        print("Use prints da mesma resolução.")
        return 2
    h, w = imgs[0].shape[:2]
    approx = minimap_circle(w, h, cfg.minimap)
    result = calibrate_center(imgs, approx)
    if result is None:
        print("Não achei a seta do jogador em nenhum print. Mantendo os valores atuais.")
        return 1
    found, blobs = result
    print(f"Seta encontrada em {len(blobs)} de {len(imgs)} prints ({w}x{h}):")
    for b in blobs:
        print(f"  ({b.x:.1f}, {b.y:.1f})  {b.area} px")
    ref = to_reference(found, w, h)
    out = paths[0].with_suffix("")
    _imwrite(out.with_name(out.name + "_calibrate.png"), draw_debug(imgs[0], found))
    shift = ((found.cx - approx.cx) ** 2 + (found.cy - approx.cy) ** 2) ** 0.5
    print(f"Centro (mediana): ({found.cx:.1f}, {found.cy:.1f}); {shift:.1f} px do atual.")
    print("Confira o _calibrate.png. Se o círculo verde bater, cole no config.toml:\n")
    print("[minimap]")
    print(f"center_x = {ref.center_x:.1f}")
    print(f"center_y = {ref.center_y:.1f}")
    print(f"radius = {ref.radius:.1f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gmt", description="Genshin Map Tracker")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="logs detalhados")
    p.add_argument(
        "-c", "--config", type=Path, help="arquivo de configuração (padrão: config.toml)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("find-window", help="procura a janela do jogo")

    cap = sub.add_parser("capture", help="captura o jogo e salva minimapas")
    cap.add_argument("--seconds", type=float, default=10.0)
    cap.add_argument("--fps", type=float, help="sobrescreve capture.fps")
    cap.add_argument("--backend", choices=["auto", "dxcam", "mss"])
    cap.add_argument("--out", help="pasta de saída (padrão: capture.output_dir)")
    cap.add_argument("--delay", type=float, default=5.0, help="espera antes de começar (s)")
    cap.add_argument("--frame-every", type=int, default=10, help="salva quadro inteiro a cada N")
    cap.add_argument("--no-save", action="store_true", help="só mede FPS/CPU, sem salvar")

    crop = sub.add_parser("crop", help="recorta o minimapa de um print")
    crop.add_argument("image")
    crop.add_argument("--out", help="prefixo dos arquivos de saída")

    cal = sub.add_parser("calibrate", help="acha o centro do minimapa pela seta do jogador")
    cal.add_argument(
        "images", nargs="+", help="um ou mais prints, de preferência virado para lados diferentes"
    )
    return p


COMMANDS = {
    "find-window": cmd_find_window,
    "capture": cmd_capture,
    "crop": cmd_crop,
    "calibrate": cmd_calibrate,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(verbose=args.verbose)
    try:
        cfg = load_config(args.config)
        return COMMANDS[args.command](args, cfg)
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
