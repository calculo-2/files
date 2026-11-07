"""`gmt diagnostico`: um teste só, que junta tudo o que é preciso num zip.

Pensado para quem tem pouco tempo: roda cada etapa, segue mesmo se uma falhar e
no fim diz onde está o zip para enviar. Etapas:
1. informações do PC e das bibliotecas;
2. janela do jogo e método de captura (inclui o erro do dxcam, se houver);
3. captura: mede CPU e salva minimapas e alguns quadros inteiros (JPEG);
4. OCR nos quadros salvos (se o RapidOCR estiver instalado);
5. diagnóstico do site do mapa (se o Playwright estiver instalado).
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import logging
import platform
import sys
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from gmt.config import Config

log = logging.getLogger("gmt")

PACKAGES = ("numpy", "opencv-python", "mss", "psutil", "dxcam", "playwright",
            "rapidocr-onnxruntime", "onnxruntime")  # fmt: skip


class Report:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.data: dict[str, Any] = {}
        self.lines: list[str] = []

    def say(self, text: str) -> None:
        print(text, flush=True)
        self.lines.append(text)

    def step(self, name: str, fn: Any) -> Any:
        self.say(f"\n== {name}")
        try:
            result = fn()
            self.data[name] = result
            return result
        except Exception as exc:  # noqa: BLE001 - o diagnóstico nunca para no meio
            self.say(f"   FALHOU: {exc!r}")
            self.data[name] = {"erro": repr(exc), "trace": traceback.format_exc()}
            return None


def _versions() -> dict[str, Any]:
    out: dict[str, Any] = {
        "python": sys.version,
        "sistema": platform.platform(),
        "processador": platform.processor(),
    }
    for pkg in PACKAGES:
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = None
    return out


def cmd_diagnostico(args: argparse.Namespace, cfg: Config) -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = cfg.capture.output_dir / f"diagnostico_{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    rep = Report(folder)
    rep.say("Diagnóstico do Genshin Map Tracker. Leva uns 2 minutos.")
    rep.say("Suas capturas não saem do PC: tudo fica num zip, e você decide se manda.")

    v = rep.step("versoes", _versions)
    if v:
        for k, val in v.items():
            rep.say(f"   {k}: {val}")

    win_info = rep.step("janela", lambda: _window(rep))
    if win_info and win_info.get("encontrada"):
        rep.say(f"\nVolte para o jogo agora. A captura começa em 10 s e dura {args.seconds:.0f} s.")
        rep.say(
            "Durante a captura: ande, gire a câmera e, se puder, abra um baú ou pegue um oculus."
        )
        time.sleep(10)
        rep.step("captura", lambda: _capture(rep, cfg, args.seconds))
        rep.step("ocr", lambda: _ocr(rep))
    else:
        rep.say("   Jogo não encontrado: pulando captura. (Abra o jogo e rode de novo.)")

    if not args.no_site:
        rep.step("site", lambda: _site(rep, cfg))

    (folder / "relatorio.json").write_text(
        json.dumps(rep.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (folder / "relatorio.txt").write_text("\n".join(rep.lines), encoding="utf-8")
    zip_path = folder.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in folder.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(folder.parent))
    size = zip_path.stat().st_size / 1e6
    rep.say("\n" + "=" * 70)
    rep.say(f"PRONTO. Mande este arquivo ({size:.1f} MB):")
    rep.say(f"   {zip_path.resolve()}")
    rep.say("A pasta vai abrir com o arquivo já selecionado.")
    rep.say("=" * 70)
    _show_in_explorer(zip_path)
    return 0


def _show_in_explorer(path: Path) -> None:
    """Abre o Explorador do Windows com o arquivo selecionado."""
    if sys.platform != "win32":
        return
    import subprocess

    try:
        subprocess.Popen(["explorer", "/select,", str(path.resolve())])
    except OSError as exc:
        log.debug("Não abriu o Explorador: %r", exc)


def _window(rep: Report) -> dict[str, Any]:
    from gmt.capture.backends import CaptureError, DxcamBackend, MssBackend
    from gmt.capture.window import find_game_window

    win = find_game_window()
    if win is None:
        rep.say("   Jogo NÃO encontrado.")
        return {"encontrada": False}
    c = win.client
    rep.say(f"   Jogo: {c.width}x{c.height} em ({c.left},{c.top}); em foco: {win.is_foreground}")
    info: dict[str, Any] = {"encontrada": True, "rect": [c.left, c.top, c.width, c.height]}
    try:
        cam = DxcamBackend(c)
        frame = cam.grab(c)
        cam.close()
        info["dxcam"] = "ok" if frame is not None else "sem quadro"
    except CaptureError as exc:
        info["dxcam"] = f"falhou: {exc}"
    rep.say(f"   dxcam: {info['dxcam']}")
    mss = MssBackend()
    frame = mss.grab(c)
    mss.close()
    info["mss"] = "ok" if frame is not None else "sem quadro"
    rep.say(f"   mss: {info['mss']}")
    return info


def _capture(rep: Report, cfg: Config, seconds: float) -> dict[str, Any]:
    from gmt.capture.backends import create_backend
    from gmt.capture.grabber import CaptureStats, frames
    from gmt.capture.window import find_game_window
    from gmt.vision.minimap import calibrate_center, crop_minimap
    from gmt.vision.regions import minimap_circle

    win = find_game_window()
    assert win is not None
    backend = create_backend(cfg.capture.backend, win.client)
    mm_dir, fr_dir = rep.folder / "minimapas", rep.folder / "quadros"
    mm_dir.mkdir(exist_ok=True)
    fr_dir.mkdir(exist_ok=True)

    # 1ª parte sem salvar nada: mede a CPU real da captura.
    quiet = CaptureStats()
    for _ in frames(backend, find_game_window, cfg.capture.fps, quiet, min(15.0, seconds / 3)):
        pass
    rep.say(f"   CPU só capturando: {quiet.avg_cpu:.1f}% de um núcleo, {quiet.real_fps:.1f} FPS")

    stats = CaptureStats()
    saved, last_full = 0, -1e9
    sample: list[Any] = []
    for frame, rect in frames(backend, find_game_window, cfg.capture.fps, stats, seconds):
        mm = crop_minimap(frame, minimap_circle(rect.width, rect.height, cfg.minimap))
        cv2.imencode(".png", mm.with_alpha())[1].tofile(str(mm_dir / f"{stats.frames:05d}.png"))
        now = time.perf_counter()
        if now - last_full >= 1.0:  # um quadro inteiro por segundo, em JPEG
            last_full = now
            cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(
                str(fr_dir / f"{stats.frames:05d}.jpg")
            )
            saved += 1
            if len(sample) < 8:
                sample.append(frame)
    backend.close()
    out = {
        "metodo": backend.name,
        "cpu_so_captura": quiet.avg_cpu,
        "fps": stats.real_fps,
        "quadros": stats.frames,
        "pretos": stats.black_frames,
        "fora_de_foco": stats.skipped_not_focused,
        "quadros_inteiros": saved,
    }
    if sample:
        h, w = sample[0].shape[:2]
        cal = calibrate_center(sample, minimap_circle(w, h, cfg.minimap))
        if cal:
            out["centro_minimapa"] = [cal[0].cx, cal[0].cy]
    rep.say(f"   {stats.frames} quadros com {backend.name}; {saved} quadros inteiros salvos")
    return out


def _ocr(rep: Report) -> dict[str, Any]:
    from gmt.detect.events import RapidOcr

    try:
        ocr = RapidOcr()
    except RuntimeError as exc:
        rep.say(f"   OCR não instalado: {exc}")
        return {"instalado": False}
    found = []
    t0 = time.perf_counter()
    files = sorted((rep.folder / "quadros").glob("*.jpg"))[:30]
    for f in files:
        img = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        for box, text, score in ocr.read_boxes(np.asarray(img, np.uint8)):
            found.append({"arquivo": f.name, "box": box, "texto": text, "score": score})
    ms = (time.perf_counter() - t0) * 1000 / max(len(files), 1)
    rep.say(f"   {len(found)} textos em {len(files)} quadros (~{ms:.0f} ms por quadro inteiro)")
    (rep.folder / "ocr.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), "utf-8")
    return {"instalado": True, "textos": len(found), "ms_por_quadro": ms}


def _site(rep: Report, cfg: Config) -> dict[str, Any]:
    from gmt.web.probe import ProbeError, run_probe

    rep.say("   Abrindo o site do mapa num Chrome separado (fecha sozinho).")
    try:
        path = run_probe(cfg.site.url, rep.folder / "site", cfg.site.profile, wait=15.0)
    except ProbeError as exc:
        rep.say(f"   {exc}")
        return {"ok": False, "erro": str(exc)}
    report = json.loads(path.read_text(encoding="utf-8"))
    libs = report["page"].get("libs")
    tiles, jsons = len(report["tile_templates"]), len(report["json_responses"])
    legal = len(report["legal_pages"])
    rep.say(f"   bibliotecas: {libs}; tiles: {tiles}; JSON: {jsons}; termos: {legal}")
    return {"ok": True, "libs": libs}
