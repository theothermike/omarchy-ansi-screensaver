"""Environment checks."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from . import config as C
from . import hypr, library as L, paths, sizing


def _check(name, ok, detail, fix=None, critical=True) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "fix": fix, "critical": critical}


def run_checks(network: bool = False) -> list[dict]:
    out = []
    ttfx = shutil.which("ttfx")
    ver = ""
    if ttfx:
        try:
            ver = subprocess.run([ttfx, "--version"], capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    out.append(_check("ttfx", ttfx, ver or "not found", "pacman -S ttfx"))
    out.append(_check("ghostty", shutil.which("ghostty"), shutil.which("ghostty") or "not found", "install ghostty"))
    out.append(_check("hyprland", hypr.available(), "HYPRLAND_INSTANCE_SIGNATURE set" if hypr.available() else "not running under Hyprland"))
    out.append(_check("hyprland events", hypr.socket2_path() is not None, str(hypr.socket2_path() or "socket2 missing"), critical=False))
    vga = sizing.vga_installed()
    out.append(_check("vga font", vga, f"{paths.VGA_FAMILY} {'installed' if vga else 'not installed'}", "ansi-screensaver fonts install", critical=False))
    try:
        import PIL  # noqa: F401
        out.append(_check("pillow", True, "available (thumbnails)", critical=False))
    except ImportError:
        out.append(_check("pillow", False, "missing: no thumbnails", "pacman -S python-pillow", critical=False))
    try:
        cfg = C.load()
        out.append(_check("config", True, str(paths.CONFIG_FILE)))
    except C.ConfigError as e:
        cfg = C.DEFAULTS
        out.append(_check("config", False, str(e), "fix or delete config.json"))
    pieces = L.list_pieces()
    enabled = [m for m in pieces if m.get("enabled", True)]
    out.append(_check("library", bool(enabled), f"{len(pieces)} pieces, {len(enabled)} enabled", "ansi-screensaver seed"))
    out.append(_check("screensaver-off toggle", not paths.SCREENSAVER_OFF_FLAG.exists(),
                      "set (screensaver disabled)" if paths.SCREENSAVER_OFF_FLAG.exists() else "not set", "omarchy-toggle-screensaver", critical=False))
    out.append(_check("stay-awake", not paths.STAY_AWAKE_FLAG.exists(),
                      "on (idle disabled)" if paths.STAY_AWAKE_FLAG.exists() else "off", critical=False))
    try:
        shell = json.loads(paths.SHELL_JSON.read_text(encoding="utf-8"))
        idle = shell.get("idle") or {}
        out.append(_check("omarchy idle", True, f"screensaver={idle.get('screensaver', 150)}s lock={idle.get('lock', 300)}s", critical=False))
    except (OSError, ValueError):
        out.append(_check("omarchy idle", True, "shell.json unreadable (defaults 150/300)", critical=False))
    out.append(_check("runtime dir", os.access(paths.RUNTIME_DIR.parent, os.W_OK), str(paths.RUNTIME_DIR)))
    if hypr.available():
        try:
            font = sizing.choose_font(cfg.get("font", "auto"))
            from .launch import effective_columns
            cols = effective_columns(cfg, enabled or pieces)
            for m in hypr.monitors():
                p = sizing.plan_monitor(m, cols, font)
                out.append(_check(f"monitor {m['name']}", True,
                                  f"{p['width']}x{p['height']}@{p['scale']} -> {p['font_pt']}pt {font['kind']} ~{p['predicted_cols']}x{p['predicted_rows']}", critical=False))
        except Exception as e:  # noqa: BLE001
            out.append(_check("sizing", False, str(e), critical=False))
    if network:
        try:
            from .sources import registry
            for src in registry.instances(cfg):
                ok, detail = src.ping()
                out.append(_check(f"source {src.id}", ok, detail, critical=False))
        except Exception as e:  # noqa: BLE001
            out.append(_check("sources", False, str(e), critical=False))
    return out
