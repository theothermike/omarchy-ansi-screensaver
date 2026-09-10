"""Filesystem locations. Everything mutable lives OUTSIDE the plugin dir."""
from __future__ import annotations

import os
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[2]
LIB_DIR = PLUGIN_DIR / "lib"
BIN = PLUGIN_DIR / "bin" / "ansi-screensaver"
ART_DIR = PLUGIN_DIR / "art"
FONTS_DIR = PLUGIN_DIR / "fonts"
VGA_TTF = FONTS_DIR / "Px437_IBM_VGA_8x16.ttf"
VGA_FAMILY = "Px437 IBM VGA 8x16"
GHOSTTY_BASE_CONF = PLUGIN_DIR / "ghostty" / "screensaver.conf"
CATALOG = PLUGIN_DIR / "catalog.json"

HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "omarchy" / "ansi-screensaver"
CONFIG_FILE = CONFIG_DIR / "config.json"
REVISION = CONFIG_DIR / "revision"
LIBRARY_DIR = CONFIG_DIR / "library"
LIBRARY_INDEX = LIBRARY_DIR / "index.json"

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "ansi-screensaver"
SOURCES_CACHE = CACHE_DIR / "sources"
PREVIEWS_CACHE = CACHE_DIR / "previews"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local" / "state")) / "ansi-screensaver"
LOG_FILE = STATE_DIR / "runner.log"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "ansi-screensaver"
USER_FONTS_DIR = HOME / ".local" / "share" / "fonts" / "ansi-screensaver"
LOCAL_BIN = HOME / ".local" / "bin" / "ansi-screensaver"

OMARCHY_PATH = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy"))
OMARCHY_STATE = HOME / ".local" / "state" / "omarchy"
THEME_COLORS = OMARCHY_STATE / "current" / "theme" / "colors.toml"
TOGGLES_DIR = OMARCHY_STATE / "toggles"
SCREENSAVER_OFF_FLAG = TOGGLES_DIR / "screensaver-off"
INDICATORS_DIR = OMARCHY_STATE / "indicators"
STAY_AWAKE_FLAG = INDICATORS_DIR / "stay-awake"
SHELL_JSON = HOME / ".config" / "omarchy" / "shell.json"
BRANDING_ART = HOME / ".config" / "omarchy" / "branding" / "screensaver.txt"

SCREENSAVER_CLASS = "org.omarchy.screensaver"
PREVIEW_CLASS = "org.omarchy.ansi-preview"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, LIBRARY_DIR, CACHE_DIR, SOURCES_CACHE, PREVIEWS_CACHE, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
