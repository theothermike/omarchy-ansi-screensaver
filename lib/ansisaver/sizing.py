"""Font size per monitor so `columns` fill the width, plus ghostty config."""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

from . import paths

PT_PER_PX = 0.75
CALIBRATION = paths.CACHE_DIR / "calibration.json"

# (advance width em, line height em) — measured for the fonts we know.
METRICS = {"vga": (0.5, 1.0), "jetbrains": (0.6, 1.32), "generic": (0.6, 1.25)}
JETBRAINS_ADJUST = "-9%"  # 1.32em -> 1.2em: exact 1:2 cells like VGA 8x16


def vga_installed() -> bool:
    try:
        r = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=5)
        return any(paths.VGA_FAMILY in line for line in r.stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        return False


def terminal_font_family() -> str:
    """The user's ghostty font-family (first one), or 'monospace'."""
    for p in (paths.HOME / ".config" / "ghostty" / "config", paths.OMARCHY_PATH / "config" / "ghostty" / "config"):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                m = re.match(r"\s*font-family\s*=\s*\"?([^\"#]+?)\"?\s*$", line)
                if m and m.group(1).strip():
                    return m.group(1).strip()
        except OSError:
            continue
    return "monospace"


def choose_font(mode: str) -> dict:
    """Return {kind, families, adjust} for config mode auto|vga|terminal."""
    term_family = terminal_font_family()
    has_vga = vga_installed()
    if mode == "vga" or (mode == "auto" and has_vga):
        if not has_vga:
            raise RuntimeError(f"font '{paths.VGA_FAMILY}' is not installed (run: ansi-screensaver fonts install)")
        return {"kind": "vga", "families": [paths.VGA_FAMILY, term_family], "adjust": None, "metrics": METRICS["vga"]}
    kind = "jetbrains" if "jetbrains" in term_family.lower() else "generic"
    return {"kind": kind, "families": [term_family],
            "adjust": JETBRAINS_ADJUST if kind == "jetbrains" else None,
            "metrics": METRICS[kind] if kind != "jetbrains" else (0.6, 1.2)}


def text_scaling_factor() -> float:
    """GTK text scaling (Omarchy sets it); ghostty applies it to font-size."""
    try:
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "text-scaling-factor"],
                           capture_output=True, text=True, timeout=3)
        v = float(r.stdout.strip())
        if 0.5 <= v <= 4.0:
            return v
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 1.0


def load_calibration() -> dict:
    try:
        import json
        return json.loads(CALIBRATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_calibration(monitor: str, font_kind: str, pt: float, cols: int, rows: int) -> None:
    """Called by the runner once it knows the real terminal size."""
    import json
    if not monitor or pt <= 0 or cols <= 0 or rows <= 0:
        return
    cal = load_calibration()
    cal[f"{monitor}|{font_kind}"] = {"pt": pt, "cols": cols, "rows": rows}
    try:
        paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CALIBRATION.with_suffix(".tmp")
        tmp.write_text(json.dumps(cal, indent=2), encoding="utf-8")
        tmp.replace(CALIBRATION)
    except OSError:
        pass


def plan_monitor(mon: dict, columns: int, font: dict, calibration: dict | None = None,
                 text_scale: float | None = None) -> dict:
    width, height = int(mon["width"]), int(mon["height"])
    scale = float(mon.get("scale") or 1.0)
    if int(mon.get("transform") or 0) in (1, 3, 5, 7):
        width, height = height, width
    logical_w = width / scale
    advance, line = font["metrics"]
    ts = text_scale if text_scale is not None else text_scaling_factor()
    cal = (calibration if calibration is not None else load_calibration()).get(f"{mon['name']}|{font['kind']}")
    if cal and cal.get("cols") and cal.get("pt"):
        # measured: cell width is linear in pt -> device px per pt per column
        cell_w_per_pt = (width / cal["cols"]) / cal["pt"]
        cell_h_per_pt = (height / cal["rows"]) / cal["pt"] if cal.get("rows") else cell_w_per_pt * line / advance
        source = "calibrated"
    else:
        dev_px_per_pt = scale * ts / PT_PER_PX
        cell_w_per_pt = dev_px_per_pt * advance
        cell_h_per_pt = dev_px_per_pt * line
        source = "model"
    pt = math.floor((width / columns) / cell_w_per_pt * 2) / 2

    def predict(pt_: float) -> tuple[int, int]:
        cell_w = max(1.0, round(cell_w_per_pt * pt_))
        cell_h = max(1.0, round(cell_h_per_pt * pt_))
        return int(width // cell_w), int(height // cell_h)

    cols, rows = predict(pt)
    while cols < columns and pt > 4:
        pt -= 0.5
        cols, rows = predict(pt)
    return {"name": mon["name"], "width": width, "height": height, "scale": scale, "text_scale": ts,
            "logical": [round(logical_w), round(height / scale)], "font_pt": pt, "sizing": source,
            "predicted_cols": cols, "predicted_rows": rows}


def ghostty_config(font: dict, title: str = "ANSI Screensaver") -> str:
    base = paths.GHOSTTY_BASE_CONF.read_text(encoding="utf-8") if paths.GHOSTTY_BASE_CONF.is_file() else ""
    lines = [base.rstrip("\n"), "", "# generated", 'font-family = ""']
    for fam in font["families"]:
        lines.append(f'font-family = "{fam}"')
    lines.append(f'font-family-bold = "{font["families"][0]}"')
    if font.get("adjust"):
        lines.append(f"adjust-cell-height = {font['adjust']}")
    lines.append(f"title = {title}")
    return "\n".join(lines) + "\n"
