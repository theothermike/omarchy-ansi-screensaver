"""`launch`, `stop`, `preview`: spawn fullscreen ghostty windows per monitor."""
from __future__ import annotations

import json
import logging
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from argparse import Namespace

from . import config as C
from . import hypr, library as L, paths, sizing

log = logging.getLogger("ansisaver.launch")


def notify(msg: str) -> None:
    if shutil.which("omarchy-notification-send"):
        subprocess.run(["omarchy-notification-send", "-g", "✋", msg], capture_output=True)
    sys.stderr.write(msg + "\n")


def is_locked() -> bool:
    if not shutil.which("omarchy-shell"):
        return False
    try:
        r = subprocess.run(["omarchy-shell", "lock", "isLocked"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def effective_columns(cfg: dict, pieces: list[dict]) -> int:
    c = cfg.get("columns", 80)
    if c == "auto":
        widest = max((int(m.get("cols") or 0) for m in pieces), default=80)
        return max(80, min(132, widest))
    return int(c)


def build_plan(args, cfg: dict, pieces: list[dict], window_class: str) -> dict:
    font = sizing.choose_font(cfg.get("font", "auto"))
    columns = effective_columns(cfg, pieces)
    mons = hypr.monitors() if hypr.available() else []
    if getattr(args, "monitor", None):
        mons = [m for m in mons if m["name"] == args.monitor]
    plans = [sizing.plan_monitor(m, columns, font) for m in mons]
    conf = paths.RUNTIME_DIR / f"ghostty-{window_class}.conf"
    session = paths.RUNTIME_DIR / f"session-{window_class}.json"
    argvs = []
    for p in plans:
        argv = ["ghostty", f"--class={window_class}", f"--config-file={conf}", f"--font-size={p['font_pt']:g}",
                "-e", str(paths.BIN), "run", "--monitor", p["name"], "--session", str(session), "--window-class", window_class,
                "--font-pt", f"{p['font_pt']:g}", "--font-kind", font["kind"]]
        if getattr(args, "piece", None):
            argv += ["--piece", args.piece]
        if getattr(args, "effect", None):
            argv += ["--effect", args.effect]
        if getattr(args, "once", False):
            argv.append("--once")
        argvs.append(argv)
    return {"window_class": window_class, "columns": columns, "font": {k: v for k, v in font.items() if k != "metrics"},
            "monitors": plans, "config_file": str(conf), "session_file": str(session), "argv": argvs}


def write_runtime_files(plan: dict, cfg: dict, pieces: list[dict], font: dict) -> None:
    paths.ensure_dirs()
    conf = paths.RUNTIME_DIR / os.path.basename(plan["config_file"])
    text = sizing.ghostty_config(font, title="ANSI Screensaver")
    if plan["window_class"] == paths.PREVIEW_CLASS:
        text += "fullscreen = true\n"
    conf.write_text(text, encoding="utf-8")
    seed = random.randrange(1, 2**31)
    playlist = []
    if cfg.get("multi_monitor") == "mirrored" and pieces:
        rng = random.Random(seed)
        ids = [m["id"] for m in pieces]
        for _ in range(200):
            playlist.append({"piece": rng.choice(ids)})
    session = {"started": time.time(), "mode": cfg.get("multi_monitor"), "seed": seed,
               "monitors": [m["name"] for m in plan["monitors"]], "playlist": playlist}
    (paths.RUNTIME_DIR / os.path.basename(plan["session_file"])).write_text(json.dumps(session), encoding="utf-8")


def launch(args, window_class: str | None = None) -> int:
    window_class = window_class or args.window_class
    paths.ensure_dirs()
    from .runner import setup_logging
    setup_logging()
    log.info("launch class=%s force=%s piece=%s hypr=%s path=%s", window_class, getattr(args, "force", False),
             getattr(args, "piece", None), hypr.available(), os.environ.get("PATH", "")[:80])
    if not shutil.which("ttfx"):
        notify("ANSI screensaver needs the ttfx package (it ships with Omarchy)")
        return 1
    if not shutil.which("ghostty"):
        notify("ANSI screensaver needs ghostty")
        return 1
    running = hypr.class_pids(window_class)
    ours = [pid for pid in running if b"ansi-screensaver" in hypr.cmdline(pid)]
    if ours:
        log.info("already running: %s", ours)
        return 0
    # Omarchy's own screensaver got there first (its idle timer won a race,
    # e.g. after our monitor was re-created mid-idle): replace it. Ours is
    # spawned first so the stock idle service never sees zero screensaver
    # windows and its lock timer keeps running.
    stock_scripts, stock_rest = hypr.stock_screensaver_pids() if window_class == paths.SCREENSAVER_CLASS else ([], [])
    stock = stock_scripts or stock_rest
    if stock:
        log.info("stock screensaver running (scripts %s, windows %s); replacing it", stock_scripts, stock_rest)
        # Its loop checks focus every second and its exit trap pkills the
        # whole window class, so the script dies first, without a trap.
        for pid in stock_scripts:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    force = bool(getattr(args, "force", False))
    if not force and paths.SCREENSAVER_OFF_FLAG.exists():
        log.info("screensaver-off toggle set; not launching")
        return 1
    if not force and is_locked():
        log.info("session locked; not launching")
        return 0
    cfg = C.load()
    pieces = [m for m in L.list_pieces() if m.get("enabled", True)]
    if not pieces:
        L.seed()
        pieces = [m for m in L.list_pieces() if m.get("enabled", True)]
    if getattr(args, "piece", None):
        m = L.load_meta(args.piece)
        if m is None:
            notify(f"unknown piece {args.piece}")
            return 1
        pieces = [m]
    if not pieces:
        notify("ANSI screensaver: the library is empty (import some art first)")
        return 1
    try:
        font = sizing.choose_font(cfg.get("font", "auto"))
    except RuntimeError as e:
        notify(str(e))
        return 1
    plan = build_plan(args, cfg, pieces, window_class)
    if getattr(args, "dry_run", False):
        print(json.dumps(plan, indent=2))
        return 0
    if not plan["monitors"]:
        log.error("no monitors (HYPRLAND_INSTANCE_SIGNATURE=%s)", os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
        notify("ANSI screensaver: no monitors found (is Hyprland running?)")
        return 1
    write_runtime_files(plan, cfg, pieces, font)
    if window_class == paths.PREVIEW_CLASS:
        ensure_preview_rule()
    events = hypr.Events()
    focused = hypr.focused_monitor()
    try:
        for p, argv in zip(plan["monitors"], plan["argv"]):
            hypr.focus_monitor(p["name"])
            hypr.exec_cmd(argv)
            addr = events.wait_for_open(window_class, 5.0)
            log.info("monitor %s: window %s", p["name"], addr or "not seen within 5s")
    finally:
        if focused:
            hypr.focus_monitor(focused)
        events.close()
    if stock:
        # ours has mapped, so the stock idle service never sees zero
        # screensaver windows; now drop the orphaned stock window and ttfx
        time.sleep(0.3)
        scripts, rest = hypr.stock_screensaver_pids()
        for pid in scripts + rest:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        log.info("stock screensaver replaced")
    return 0


def ensure_preview_rule() -> None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "none")
    marker = paths.RUNTIME_DIR / f"preview-rule.{sig}"
    if marker.exists():
        return
    if hypr.add_fullscreen_rule(paths.PREVIEW_CLASS):
        marker.touch()


def stop(args) -> int:
    classes = [paths.SCREENSAVER_CLASS] + ([paths.PREVIEW_CLASS] if getattr(args, "previews", False) else [])
    subprocess.run(["pkill", "-x", "ttfx"], capture_output=True)
    n = 0
    for cls in classes:
        for pid in hypr.class_pids(cls):
            try:
                os.kill(pid, signal.SIGTERM)
                n += 1
            except OSError:
                pass
    try:
        hypr.cursor_invisible(False)
    except Exception:  # noqa: BLE001
        pass
    for f in paths.RUNTIME_DIR.glob("slide-*.ans"):
        f.unlink(missing_ok=True)
    print(json.dumps({"stopped": n}) if getattr(args, "json", False) else f"stopped {n} process(es)")
    return 0


def preview(args) -> int:
    if getattr(args, "source", None):
        from .sources.cli import cmd_preview_source
        return cmd_preview_source(args)
    pieces = [m for m in L.list_pieces() if m.get("enabled", True)] or L.list_pieces()
    pid = args.id
    if pid is None or getattr(args, "random", False):
        if not pieces:
            notify("library is empty")
            return 1
        pid = random.choice(pieces)["id"]
    # a running preview is replaced
    for old in hypr.class_pids(paths.PREVIEW_CLASS):
        try:
            os.kill(old, signal.SIGTERM)
        except OSError:
            pass
    time.sleep(0.2)
    ns = Namespace(force=True, piece=pid, effect=getattr(args, "effect", None), once=True,
                   monitor=hypr.focused_monitor() if hypr.available() else None,
                   window_class=paths.PREVIEW_CLASS, dry_run=getattr(args, "dry_run", False), json=False)
    return launch(ns, window_class=paths.PREVIEW_CLASS)
