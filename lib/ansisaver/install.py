"""`install`: symlink the CLI into ~/.local/bin, optionally fonts + seed."""
from __future__ import annotations

import json
import os

from . import paths


def install(args) -> int:
    paths.ensure_dirs()
    link = paths.LOCAL_BIN
    link.parent.mkdir(parents=True, exist_ok=True)
    result = {"symlink": str(link), "target": str(paths.BIN)}
    if link.is_symlink() or link.exists():
        if link.is_symlink() and os.readlink(link) == str(paths.BIN):
            result["symlink_status"] = "ok"
        else:
            link.unlink()
            link.symlink_to(paths.BIN)
            result["symlink_status"] = "replaced"
    else:
        link.symlink_to(paths.BIN)
        result["symlink_status"] = "created"
    if getattr(args, "fonts", False):
        from .fonts import install as finstall
        result["fonts"] = finstall()
    if getattr(args, "seed", False):
        from .library import seed
        result["seed"] = seed()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{link} -> {paths.BIN} ({result['symlink_status']})")
        if "fonts" in result:
            print(f"font {result['fonts']['family']}: {'available' if result['fonts']['available'] else 'missing'}")
        if "seed" in result:
            s = result["seed"]
            print(f"seeded {len(s['seeded'])}, skipped {len(s['skipped'])}, failed {len(s['failed'])}")
    return 0
