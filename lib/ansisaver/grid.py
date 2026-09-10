"""Cell grids and their serialisation to SGR-only text (what ttfx accepts)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ansi import BLANK, Cell, Interpreter
from .palette import DEFAULT_FG, split

_BAD = re.compile("[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f-\x9f\ud800-\udfff]")


@dataclass
class Grid:
    cols: int
    rows: list[list[Cell]] = field(default_factory=list)

    @property
    def height(self) -> int:
        return len(self.rows)

    def painted_width(self, r: int) -> int:
        row = self.rows[r]
        for i in range(len(row) - 1, -1, -1):
            ch, _fg, bg = row[i]
            if ch != " " or bg is not None:
                return i + 1
        return 0

    @property
    def painted_cols(self) -> int:
        return max((self.painted_width(r) for r in range(len(self.rows))), default=0)

    def cell(self, x: int, y: int) -> Cell:
        if 0 <= y < len(self.rows):
            row = self.rows[y]
            if 0 <= x < len(row):
                return row[x]
        return BLANK

    def is_colored(self) -> bool:
        for row in self.rows:
            for ch, fg, bg in row:
                if bg is not None or (ch != " " and fg != DEFAULT_FG):
                    return True
        return False


def _sgr_bg(bg: int | None) -> str:
    if bg is None:
        return "\x1b[49m"
    r, g, b = split(bg)
    return f"\x1b[48;2;{r};{g};{b}m"


def _sgr_fg(fg: int) -> str:
    r, g, b = split(fg)
    return f"\x1b[38;2;{r};{g};{b}m"


def row_to_sgr(row: list[Cell], upto: int | None = None, pad: int = 0) -> str:
    """Serialise one row as self-contained SGR text (starts from the reset
    state, ends with reset). Never emits bold/blink/reverse; fg only for
    visible glyphs. `pad` prefixes that many plain spaces."""
    if upto is None:
        upto = len(row)
        while upto > 0 and row[upto - 1][0] == " " and row[upto - 1][2] is None:
            upto -= 1
    if upto <= 0 and pad <= 0:
        return ""
    out: list[str] = []
    if pad > 0:
        out.append(" " * pad)
    fg: int | None = None
    bg: int | None = None
    for i in range(min(upto, len(row))):
        ch, cfg, cbg = row[i]
        if cbg != bg:
            out.append(_sgr_bg(cbg))
            bg = cbg
        if ch != " " and cfg != fg:
            out.append(_sgr_fg(cfg))
            fg = cfg
        out.append(ch)
    out.append("\x1b[0m")
    return "".join(out)


def sanitize(text: str) -> str:
    return _BAD.sub(" ", text)


def grid_to_flat(grid: Grid) -> str:
    lines = [sanitize(row_to_sgr(row, upto=grid.painted_width(r))) for r, row in enumerate(grid.rows)]
    return "\n".join(lines) + "\n"


def write_flat(grid: Grid, path) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(grid_to_flat(grid))


def read_flat(text: str) -> Grid:
    it = Interpreter(cols=0, ice=False)
    it.feed(text)
    return it.grid()


def slice_rows(grid: Grid, top: int, count: int) -> Grid:
    return Grid(cols=grid.cols, rows=[list(r) for r in grid.rows[top:top + count]])


def compose(grid: Grid, cols: int, rows: int, x_off: int = 0, y_off: int = 0, top: int = 0):
    """Return a full-screen frame (rows x cols cells) with the grid placed at
    (x_off, y_off), showing grid rows starting at `top`."""
    frame: list[list[Cell]] = [[BLANK] * cols for _ in range(rows)]
    for r in range(rows):
        gy = r - y_off + top
        if gy < top or gy >= len(grid.rows):
            continue
        src = grid.rows[gy]
        dst = frame[r]
        for x in range(len(src)):
            fx = x + x_off
            if 0 <= fx < cols:
                dst[fx] = src[x]
    return frame


def recolor(grid: Grid, color_for_row) -> Grid:
    """Copy of grid where cells still carrying the default foreground get a
    colour from color_for_row(row_index, row_count)."""
    n = max(1, len(grid.rows))
    out = []
    for r, row in enumerate(grid.rows):
        c = color_for_row(r, n)
        out.append([(ch, c if fg == DEFAULT_FG else fg, bg) for ch, fg, bg in row])
    return Grid(cols=grid.cols, rows=out)
