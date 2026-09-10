"""Colour tables. Cells carry 24-bit ints (0xRRGGBB); bg None = default black."""
from __future__ import annotations

# Classic VGA text-mode palette, ANSI order (0-7 normal, 8-15 bright).
VGA16 = [
    0x000000, 0xAA0000, 0x00AA00, 0xAA5500, 0x0000AA, 0xAA00AA, 0x00AAAA, 0xAAAAAA,
    0x555555, 0xFF5555, 0x55FF55, 0xFFFF55, 0x5555FF, 0xFF55FF, 0x55FFFF, 0xFFFFFF,
]
DEFAULT_FG = VGA16[7]
BLACK = 0x000000

_CUBE = (0, 95, 135, 175, 215, 255)


def xterm256(n: int) -> int:
    n = max(0, min(255, int(n)))
    if n < 16:
        return VGA16[n]
    if n < 232:
        n -= 16
        r, g, b = _CUBE[n // 36], _CUBE[(n // 6) % 6], _CUBE[n % 6]
        return (r << 16) | (g << 8) | b
    v = 8 + 10 * (n - 232)
    return (v << 16) | (v << 8) | v


def rgb(r: int, g: int, b: int) -> int:
    return ((max(0, min(255, r))) << 16) | ((max(0, min(255, g))) << 8) | max(0, min(255, b))


def split(c: int) -> tuple[int, int, int]:
    return (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF


def hexstr(c: int) -> str:
    """ttfx-style bare hex, e.g. 'faa968'."""
    return f"{c & 0xFFFFFF:06x}"


def parse_hex(s: str) -> int:
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    return int(s[:6], 16)


def scale(c: int, f: float) -> int:
    r, g, b = split(c)
    return rgb(int(r * f), int(g * f), int(b * f))


def mix(a: int, b: int, t: float) -> int:
    ar, ag, ab = split(a)
    br, bg, bb = split(b)
    return rgb(int(ar + (br - ar) * t), int(ag + (bg - ag) * t), int(ab + (bb - ab) * t))
