"""config.json: defaults, dotted-key get/set, validation."""
from __future__ import annotations

import copy
import json
import os
import time
from typing import Any

from . import paths

DEFAULT_EFFECTS = {
    "beams": 3, "blackhole": 2, "bouncyballs": 1, "burn": 3, "crumble": 2, "decrypt": 3,
    "errorcorrect": 1, "expand": 2, "fireworks": 2, "highlight": 2, "laseretch": 1, "matrix": 3,
    "middleout": 2, "orbittingvolley": 2, "pour": 2, "print": 2, "rain": 2, "randomsequence": 2,
    "rings": 1, "scattered": 2, "slice": 2, "slide": 3, "smoke": 2, "spotlights": 2, "spray": 2,
    "swarm": 1, "sweep": 3, "synthgrid": 1, "thunderstorm": 2, "unstable": 2, "vhstape": 2,
    "waves": 2, "wipe": 3,
    "colorshift": 0, "overflow": 0, "binarypath": 0, "bubbles": 0,
}
DEFAULT_TRANSITIONS = {"fade": 3, "dissolve": 2, "wipe": 2, "melt": 3, "curtain": 1,
                       "glitch": 2, "blocks": 2, "cut": 0}

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "columns": 80,                 # int or "auto"
    "font": "auto",                # auto | vga | terminal
    "wide_pieces": "skip",         # skip | clip
    "order": "shuffle",            # shuffle | ordered | favorites
    "multi_monitor": "independent",  # independent | mirrored
    "hold_seconds": 20,
    "hold_top_seconds": 4,
    "scroll_rows_per_second": 2,
    "slide_max_seconds": 120,
    "caption": True,
    "caption_position": "br",      # br | tr | bl | tl
    "ascii_color": "theme-gradient",  # theme-gradient | theme-foreground | vga-grey
    "include_branding": 0,         # show branding art every N slides (0 = never)
    "reveal": {"ttfx": 70, "baud": 30},
    "ttfx": {"existing_color_handling": "always", "frame_rate_scale": 1.0, "max_seconds": 30,
             "effects": dict(DEFAULT_EFFECTS)},
    "baud": {"rate": "auto", "target_seconds": 20, "max_seconds": 45, "show_cursor": True},
    "transitions": {"fps": 30, "out": dict(DEFAULT_TRANSITIONS)},
    "idle": {"takeover": True, "lead_seconds": 2},
    "sources": [
        {"provider": "github_repo", "id": "gh-sixteencolors", "repo": "sixteencolors/sixteencolors-archive",
         "label": "16colo.rs mirror (GitHub)"},
        {"provider": "http_index", "id": "textfiles", "url": "http://artscene.textfiles.com/",
         "label": "artscene.textfiles.com", "timeout": 5},
    ],
    "github_token": None,
    "removed_bundled": [],
    "track_shown": False,
}

ENUMS = {
    "font": ("auto", "vga", "terminal"),
    "wide_pieces": ("skip", "clip"),
    "order": ("shuffle", "ordered", "favorites"),
    "multi_monitor": ("independent", "mirrored"),
    "caption_position": ("br", "tr", "bl", "tl"),
    "ascii_color": ("theme-gradient", "theme-foreground", "vga-grey"),
    "ttfx.existing_color_handling": ("always", "dynamic"),
    "baud.rate": ("auto", "2400", "9600", "14400", "28800", "57600", 2400, 9600, 14400, 28800, 57600),
}
RANGES = {
    "hold_seconds": (1, 3600), "hold_top_seconds": (0, 600), "scroll_rows_per_second": (0.1, 60),
    "slide_max_seconds": (10, 3600), "include_branding": (0, 1000), "reveal.ttfx": (0, 100),
    "reveal.baud": (0, 100), "ttfx.frame_rate_scale": (0.1, 10), "ttfx.max_seconds": (3, 600),
    "baud.target_seconds": (1, 600), "baud.max_seconds": (1, 600), "transitions.fps": (5, 120),
    "idle.lead_seconds": (1, 60),
}


class ConfigError(ValueError):
    pass


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("sources",):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load() -> dict:
    try:
        with open(paths.CONFIG_FILE, "r", encoding="utf-8") as f:
            user = json.load(f)
        if not isinstance(user, dict):
            user = {}
    except FileNotFoundError:
        user = {}
    except (OSError, ValueError) as e:
        raise ConfigError(f"{paths.CONFIG_FILE}: {e}") from e
    return _merge(DEFAULTS, user)


def save(cfg: dict) -> None:
    paths.ensure_dirs()
    tmp = paths.CONFIG_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, paths.CONFIG_FILE)
    touch_revision()


def touch_revision() -> None:
    paths.ensure_dirs()
    tmp = paths.REVISION.with_suffix(".tmp")
    with open(tmp, "w") as f:
        f.write(f"{time.time_ns()}\n")
    os.replace(tmp, paths.REVISION)


def get(cfg: dict, key: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        low = raw.strip().lower()
        if low in ("true", "yes", "on"):
            return True
        if low in ("false", "no", "off"):
            return False
        return raw


def validate(key: str, value: Any) -> Any:
    if key in ENUMS and value not in ENUMS[key]:
        raise ConfigError(f"{key}: expected one of {sorted(set(map(str, ENUMS[key])))}, got {value!r}")
    if key == "columns":
        if value == "auto":
            return value
        if not isinstance(value, int) or not (20 <= value <= 400):
            raise ConfigError("columns: expected an integer 20..400 or \"auto\"")
    if key in RANGES:
        lo, hi = RANGES[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not (lo <= value <= hi):
            raise ConfigError(f"{key}: expected a number in {lo}..{hi}")
    if key in ("caption", "idle.takeover", "baud.show_cursor", "track_shown") and not isinstance(value, bool):
        raise ConfigError(f"{key}: expected true/false")
    if key.startswith("ttfx.effects.") or key.startswith("transitions.out."):
        if not isinstance(value, (int, float)) or value < 0:
            raise ConfigError(f"{key}: expected a weight >= 0")
    return value


def set_value(cfg: dict, key: str, value: Any) -> dict:
    value = validate(key, value)
    parts = key.split(".")
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value
    return cfg


def effect_weights(cfg: dict) -> dict[str, float]:
    w = dict(DEFAULT_EFFECTS)
    w.update({k: float(v) for k, v in get(cfg, "ttfx.effects", {}).items()})
    return w


def transition_weights(cfg: dict) -> dict[str, float]:
    w = dict(DEFAULT_TRANSITIONS)
    w.update({k: float(v) for k, v in get(cfg, "transitions.out", {}).items()})
    return w
