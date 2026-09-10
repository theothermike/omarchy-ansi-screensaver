"""Omarchy's own idle timeouts (idle.screensaver / idle.lock in shell.json).

Writes go through Omarchy's `omarchy-shell-config` helper (the same jq
`commit` the stock scripts use) so the file stays well-formed and the running
shell reloads it."""
from __future__ import annotations

import json
import subprocess

from . import paths

DEFAULTS = {"screensaver": 150, "lock": 300}
MIN_SECONDS = 10
MAX_SECONDS = 30 * 86400  # ext-idle-notify takes a uint32 of milliseconds; 30 days is safely below


def read() -> dict:
    values = dict(DEFAULTS)
    try:
        j = json.loads(paths.SHELL_JSON.read_text(encoding="utf-8"))
        idle = j.get("idle") if isinstance(j, dict) else None
        if isinstance(idle, dict):
            for k in DEFAULTS:
                v = idle.get(k)
                if isinstance(v, (int, float)) and v >= 0:
                    values[k] = int(v)
    except (OSError, ValueError):
        pass
    return {"screensaver": values["screensaver"], "lock": values["lock"], "defaults": dict(DEFAULTS),
            "file": str(paths.SHELL_JSON)}


def write(screensaver: int | None = None, lock: int | None = None) -> dict:
    cur = read()
    s = cur["screensaver"] if screensaver is None else int(screensaver)
    l = cur["lock"] if lock is None else int(lock)
    for name, v in (("screensaver", s), ("lock", l)):
        if not (MIN_SECONDS <= v <= MAX_SECONDS):
            raise ValueError(f"{name}: expected {MIN_SECONDS}..{MAX_SECONDS} seconds, got {v}")
    helper = paths.OMARCHY_PATH / "bin" / "omarchy-shell-config"
    if not helper.is_file():
        raise RuntimeError(f"{helper} not found")
    script = 'source "$1"; commit ".idle.screensaver = \\$s | .idle.lock = \\$l" --argjson s "$2" --argjson l "$3"'
    r = subprocess.run(["bash", "-c", script, "_", str(helper), str(s), str(l)], capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "omarchy-shell-config commit failed")
    out = read()
    out["warning"] = "lock fires before the screensaver" if out["lock"] <= out["screensaver"] else None
    return out


def cmd_idle(args) -> int:
    from .cli import emit, fail
    if args.op == "get":
        v = read()
        emit(args, v, f"screensaver {v['screensaver']} s · lock {v['lock']} s  ({v['file']})")
        return 0
    if args.screensaver is None and args.lock is None:
        return fail(args, "idle set needs --screensaver and/or --lock (seconds)", 2)
    try:
        v = write(args.screensaver, args.lock)
    except (ValueError, RuntimeError) as e:
        return fail(args, str(e))
    emit(args, v, f"screensaver {v['screensaver']} s · lock {v['lock']} s" + (f"  (note: {v['warning']})" if v.get("warning") else ""))
    return 0
