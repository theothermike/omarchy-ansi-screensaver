"""Omarchy theme colours (colors.toml) for effect gradients and captions."""
from __future__ import annotations

import tomllib

from . import paths
from .palette import parse_hex

_FALLBACK = {
    "accent": "#faa968", "foreground": "#f6dcac", "light_foreground": "#a7c9c6",
    "dark_foreground": "#3f8f8a", "bright_foreground": "#f6dcac", "muted": "#2a6b78",
    "background": "#000000", "red": "#f85525", "yellow": "#e97b3c", "orange": "#faa968",
    "green": "#028391", "cyan": "#8cbfb8", "blue": "#3f8f8a", "magenta": "#3f8f8a",
    "bright_green": "#55ff55", "bright_red": "#ff5555", "bright_yellow": "#ffff55",
    "bright_cyan": "#55ffff", "bright_blue": "#5555ff", "bright_magenta": "#ff55ff",
}


class Theme:
    def __init__(self, values: dict[str, str]):
        self.values = dict(_FALLBACK)
        for k, v in values.items():
            if isinstance(v, str) and v.startswith("#"):
                self.values[k] = v

    def rgb(self, key: str) -> int:
        return parse_hex(self.values.get(key, _FALLBACK.get(key, "#aaaaaa")))

    def hex(self, key: str) -> str:
        return f"{self.rgb(key):06x}"

    def gradient_stops(self) -> list[str]:
        return [self.hex("accent"), self.hex("foreground"), self.hex("light_foreground")]


def load() -> Theme:
    try:
        with open(paths.THEME_COLORS, "rb") as f:
            return Theme(tomllib.load(f))
    except (OSError, ValueError):
        return Theme({})
