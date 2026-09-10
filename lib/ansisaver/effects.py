"""ttfx effect table and argv construction."""
from __future__ import annotations

import random

from .theme import Theme

# name -> (fps, color mode, theme-fed args as list of (flag, [theme keys or literal hex]))
TABLE: dict[str, tuple[int, str, list]] = {
    "beams": (60, "always", [("--beam-gradient-stops", ["accent", "bright_foreground", "ffffff"])]),
    "blackhole": (120, "always", [("--blackhole-color", ["accent"]), ("--star-colors", ["foreground", "cyan", "yellow"])]),
    "bouncyballs": (240, "always", [("--ball-colors", ["red", "yellow", "blue", "accent"])]),
    "burn": (120, "dynamic", [("--starting-color", ["202020"]), ("--burn-colors", ["5a1a00", "a83200", "e06000", "accent", "ffffff"])]),
    "crumble": (90, "always", []),
    "decrypt": (240, "dynamic", [("--ciphertext-colors", ["green", "dark_foreground", "muted"])]),
    "errorcorrect": (180, "always", [("--error-color", ["red"]), ("--correct-color", ["green"])]),
    "expand": (60, "always", []),
    "fireworks": (150, "always", [("--firework-colors", ["red", "yellow", "orange", "accent", "cyan"])]),
    "highlight": (45, "always", []),
    "laseretch": (240, "dynamic", []),
    "matrix": (180, "dynamic", [("--rain-color-gradient", ["green", "bright_green"]), ("--highlight-color", ["ffffff"])]),
    "middleout": (60, "always", [("--starting-color", ["accent"])]),
    "orbittingvolley": (120, "always", []),
    "pour": (240, "always", [("--starting-color", ["accent"])]),
    "print": (240, "always", []),
    "rain": (150, "dynamic", [("--rain-colors", ["blue", "cyan", "foreground"])]),
    "randomsequence": (60, "always", []),
    "rings": (150, "always", [("--ring-colors", ["accent", "cyan", "magenta"])]),
    "scattered": (60, "always", []),
    "slice": (60, "always", []),
    "slide": (60, "always", []),
    "smoke": (60, "dynamic", [("--smoke-gradient-stops", ["202020", "muted", "light_foreground"])]),
    "spotlights": (90, "always", []),
    "spray": (60, "always", []),
    "swarm": (240, "always", [("--base-color", ["muted"]), ("--flash-color", ["accent"])]),
    "sweep": (60, "always", []),
    "synthgrid": (60, "always", [("--grid-gradient-stops", ["muted", "accent"])]),
    "thunderstorm": (120, "dynamic", [("--lightning-color", ["ffffff"]), ("--glowing-text-color", ["accent"]), ("--spark-glow-color", ["yellow"])]),
    "unstable": (60, "always", [("--unstable-color", ["red"])]),
    "vhstape": (90, "dynamic", [("--glitch-line-colors", ["red", "cyan", "ffffff"]), ("--noise-colors", ["303030", "808080", "c0c0c0"])]),
    "waves": (60, "always", [("--wave-gradient-stops", ["accent", "foreground"])]),
    "wipe": (45, "always", []),
    "colorshift": (60, "always", []),
    "overflow": (60, "always", []),
    "binarypath": (120, "always", []),
    "bubbles": (240, "always", []),
}
ALL_EFFECTS = sorted(TABLE)
GRADIENT_DIRECTIONS = ["vertical", "horizontal", "diagonal", "radial"]


def _color(theme: Theme, key: str) -> str:
    if len(key) == 6 and all(c in "0123456789abcdefABCDEF" for c in key):
        return key.lower()
    return theme.hex(key)


def pick(weights: dict[str, float], rng: random.Random) -> str:
    items = [(k, w) for k, w in weights.items() if k in TABLE and w > 0]
    if not items:
        return "wipe"
    names, ws = zip(*items)
    return rng.choices(names, weights=ws, k=1)[0]


def build_argv(effect: str, input_path: str, cols: int, rows: int, *, theme: Theme, seed: int,
               color_mode: str = "always", fps_scale: float = 1.0, rng: random.Random | None = None) -> list[str]:
    if effect not in TABLE:
        raise KeyError(effect)
    fps, mode, extra = TABLE[effect]
    if color_mode == "always":
        mode = "always"
    rng = rng or random.Random(seed)
    argv = ["ttfx", "-i", input_path,
            "--existing-color-handling", mode,
            "--canvas-width", str(cols), "--canvas-height", str(rows),
            "--anchor-canvas", "nw", "--anchor-text", "nw",
            "--frame-rate", str(max(10, int(fps * fps_scale))),
            "--seed", str(seed), "--no-eol", "--no-restore-cursor",
            effect]
    for flag, keys in extra:
        argv.append(flag)
        argv.extend(_color(theme, k) for k in keys)
    argv += ["--final-gradient-stops", *theme.gradient_stops(),
             "--final-gradient-direction", rng.choice(GRADIENT_DIRECTIONS)]
    return argv
