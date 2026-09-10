"""Install the vendored VGA font for the user."""
from __future__ import annotations

import json
import shutil
import subprocess

from . import paths, sizing


def install() -> dict:
    paths.USER_FONTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = paths.USER_FONTS_DIR / paths.VGA_TTF.name
    changed = False
    if not dst.exists() or dst.stat().st_size != paths.VGA_TTF.stat().st_size:
        shutil.copyfile(paths.VGA_TTF, dst)
        changed = True
    lic = paths.USER_FONTS_DIR / "LICENSE-CC-BY-SA-4.0.txt"
    src_lic = paths.FONTS_DIR / "LICENSE-CC-BY-SA-4.0.txt"
    if src_lic.exists() and not lic.exists():
        shutil.copyfile(src_lic, lic)
    subprocess.run(["fc-cache", "-f", str(paths.USER_FONTS_DIR)], capture_output=True)
    return {"installed": True, "changed": changed, "path": str(dst), "family": paths.VGA_FAMILY,
            "available": sizing.vga_installed()}


def status() -> dict:
    return {"family": paths.VGA_FAMILY, "available": sizing.vga_installed(),
            "vendored": paths.VGA_TTF.exists(), "path": str(paths.USER_FONTS_DIR / paths.VGA_TTF.name)}


def cmd(args) -> int:
    res = install() if args.op == "install" else status()
    if args.json:
        print(json.dumps(res))
    else:
        print(f"{paths.VGA_FAMILY}: {'available' if res['available'] else 'NOT installed'} ({res['path']})")
    return 0 if res["available"] or args.op == "status" else 1
