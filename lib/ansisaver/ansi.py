"""ANSI art interpreter: decodes CP437/Latin-1/UTF-8 and executes the CSI
subset real .ans files use, producing a cell grid. Also drives the baud
player incrementally (feed() may be called one character at a time)."""
from __future__ import annotations

from typing import Callable

from .palette import DEFAULT_FG, VGA16, rgb, xterm256

Cell = tuple[str, int, int | None]  # (char, fg rgb, bg rgb or None = default black)
BLANK: Cell = (" ", DEFAULT_FG, None)

# IBM code page 437 glyphs for the control range (as displayed by DOS/ansilove).
_C0_GLYPHS = "\x00☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"
_KEEP_CONTROLS = {0x09, 0x0A, 0x0D, 0x1A, 0x1B}
_CP437_FIX = {i: _C0_GLYPHS[i] for i in range(1, 32) if i not in _KEEP_CONTROLS}
_CP437_FIX[0] = " "
_CP437_FIX[0x7F] = "⌂"
_OTHER_FIX = {i: " " for i in range(0, 32) if i not in _KEEP_CONTROLS}
_OTHER_FIX[0x7F] = " "
_OTHER_FIX.update({i: " " for i in range(0x80, 0xA0)})

ENCODINGS = ("cp437", "latin1", "utf8")


def decode(data: bytes, encoding: str) -> str:
    if encoding == "cp437":
        return data.decode("cp437", "replace").translate(_CP437_FIX)
    if encoding == "latin1":
        return data.decode("latin-1").translate(_OTHER_FIX)
    if encoding == "utf8":
        return data.decode("utf-8", "replace").translate(_OTHER_FIX)
    raise ValueError(f"unknown encoding {encoding!r}")


def detect_encoding(body: bytes, sauce=None, hint: str | None = None) -> str:
    if hint in ENCODINGS:
        return hint
    if sauce is not None and sauce.is_amiga:
        return "latin1"
    if any(b >= 0x80 for b in body):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return "cp437"
        return "utf8"
    return "cp437"


class Interpreter:
    """Executes decoded text into a grid of cells.

    cols=0 means unlimited width (no wrapping). wrap='immediate' follows
    ansilove/PabloDraw: the cursor wraps as soon as the last column is
    written; 'pending' wraps only when the next glyph arrives."""

    def __init__(self, cols: int = 80, ice: bool = False, wrap: str = "immediate",
                 max_rows: int = 10000, sink: Callable[[int, int, Cell], None] | None = None):
        self.cols = max(0, int(cols))
        self.ice = bool(ice)
        self.wrap = wrap
        self.max_rows = max_rows
        self.sink = sink
        self.rows: list[list[Cell]] = []
        self.x = 0
        self.y = 0
        self.saved = (0, 0)
        self.stopped = False
        self.stats = {"unknown_csi": 0, "cursor_moves": 0, "clears": 0, "overwrites": 0,
                      "max_x": 0, "colored": False, "wrapped": 0}
        self._state = 0  # 0 text, 1 esc, 2 csi
        self._csi = ""
        self.reset_attrs()

    # -- attributes -------------------------------------------------------
    def reset_attrs(self) -> None:
        self.fg_idx = 7
        self.bg_idx = 0
        self.bold = False
        self.blink = False
        self.reverse = False
        self.fg_ext: int | None = None
        self.bg_ext: int | None = None

    def current_colors(self) -> tuple[int, int | None]:
        fg = self.fg_ext if self.fg_ext is not None else VGA16[self.fg_idx + (8 if self.bold else 0)]
        if self.bg_ext is not None:
            bg: int | None = self.bg_ext
        elif self.bg_idx == 0 and not (self.blink and self.ice):
            bg = None
        else:
            bg = VGA16[self.bg_idx + (8 if (self.blink and self.ice) else 0)]
        if self.reverse:
            fg, bg = (bg if bg is not None else 0x000000), fg
        return fg, bg

    # -- grid -------------------------------------------------------------
    def _row(self, y: int) -> list[Cell]:
        rows = self.rows
        while len(rows) <= y:
            rows.append([])
        return rows[y]

    def _set(self, x: int, y: int, cell: Cell) -> None:
        if y >= self.max_rows:
            self.stopped = True
            return
        row = self._row(y)
        n = len(row)
        if x < n:
            if row[x] != BLANK:
                self.stats["overwrites"] += 1
            row[x] = cell
        else:
            if x > n:
                row.extend([BLANK] * (x - n))
            row.append(cell)
        if x > self.stats["max_x"]:
            self.stats["max_x"] = x
        if self.sink is not None:
            self.sink(x, y, cell)

    def put(self, ch: str) -> None:
        if self.cols and self.wrap == "pending" and self.x >= self.cols:
            self.x = 0
            self.y += 1
            self.stats["wrapped"] += 1
        fg, bg = self.current_colors()
        self._set(self.x, self.y, (ch, fg, bg))
        self.x += 1
        if self.cols and self.wrap != "pending" and self.x >= self.cols:
            self.x = 0
            self.y += 1
            self.stats["wrapped"] += 1

    def fill(self, x0: int, x1: int, y: int) -> None:
        """Erase cells [x0, x1) on row y with the current background (BCE)."""
        fg, bg = self.current_colors()
        cell: Cell = (" ", fg, bg)
        for x in range(x0, x1):
            self._set(x, y, cell)

    def grid(self):
        from .grid import Grid
        rows = [list(r) for r in self.rows]
        # trim trailing rows that were never painted
        while rows and not any(c != BLANK for c in rows[-1]):
            rows.pop()
        width = self.cols or (max((len(r) for r in rows), default=0))
        return Grid(cols=max(width, 1), rows=rows)

    # -- parsing ----------------------------------------------------------
    def feed(self, text: str) -> None:
        if self.stopped:
            return
        for ch in text:
            st = self._state
            if st == 0:
                if ch == "\x1b":
                    self._state = 1
                elif ch == "\n":
                    self.y += 1
                    self.x = 0
                elif ch == "\r":
                    self.x = 0
                elif ch == "\t":
                    nx = (self.x // 8 + 1) * 8
                    if self.cols:
                        nx = min(nx, self.cols - 1)
                    self.x = nx
                elif ch == "\x1a":
                    self.stopped = True
                    return
                elif ch < " ":
                    continue
                else:
                    self.put(ch)
            elif st == 1:
                if ch == "[":
                    self._state = 2
                    self._csi = ""
                elif ch == "7":
                    self.saved = (self.x, self.y)
                    self._state = 0
                elif ch == "8":
                    self.x, self.y = self.saved
                    self._state = 0
                else:
                    self._state = 0
                    if ch == "\x1b":
                        self._state = 1
            else:  # csi
                o = ord(ch)
                if 0x30 <= o <= 0x3F or 0x20 <= o <= 0x2F:
                    if len(self._csi) < 64:
                        self._csi += ch
                elif 0x40 <= o <= 0x7E:
                    self._state = 0
                    self._dispatch(self._csi, ch)
                else:
                    # malformed: abandon the sequence, reprocess this char
                    self._state = 0
                    if ch == "\x1b":
                        self._state = 1
                    else:
                        self.feed(ch)
            if self.stopped:
                return

    def _params(self, raw: str, default: int = 0) -> list[int]:
        out = []
        for p in raw.split(";"):
            p = p.strip()
            out.append(int(p) if p.isdigit() else default)
        return out

    def _dispatch(self, raw: str, final: str) -> None:
        private = raw[:1] in "?=><"
        if private:
            body = raw[1:]
            if final in "hl" and raw[0] == "?":
                for p in self._params(body):
                    if p == 33:
                        self.ice = final == "h"
            return
        if final == "m":
            self._sgr(self._params(raw or "0"))
        elif final in "Hf":
            p = self._params(raw, 1)
            row = p[0] if len(p) > 0 and p[0] > 0 else 1
            col = p[1] if len(p) > 1 and p[1] > 0 else 1
            self.y = row - 1
            self.x = col - 1
            if self.cols:
                self.x = min(self.x, self.cols - 1)
            self.stats["cursor_moves"] += 1
        elif final == "A":
            n = self._params(raw, 1)[0] or 1
            self.y = max(0, self.y - n)
            self.stats["cursor_moves"] += 1
        elif final == "B":
            n = self._params(raw, 1)[0] or 1
            self.y += n
            self.stats["cursor_moves"] += 1
        elif final == "C":
            n = self._params(raw, 1)[0] or 1
            self.x += n
            if self.cols:
                self.x = min(self.x, self.cols - 1)
        elif final == "D":
            n = self._params(raw, 1)[0] or 1
            self.x = max(0, self.x - n)
        elif final == "J":
            n = self._params(raw)[0]
            self.stats["clears"] += 1
            if n == 2:
                self.rows = []
                self.x = self.y = 0
            elif n == 0:
                width = self.cols or (len(self.rows[self.y]) if self.y < len(self.rows) else 0)
                self.fill(self.x, width, self.y)
                for y in range(self.y + 1, len(self.rows)):
                    self.rows[y] = []
            elif n == 1:
                for y in range(0, self.y):
                    self.rows[y] = []
                self.fill(0, self.x + 1, self.y)
        elif final == "K":
            n = self._params(raw)[0]
            width = self.cols or (len(self.rows[self.y]) if self.y < len(self.rows) else self.x)
            if n == 0:
                self.fill(self.x, max(width, self.x), self.y)
            elif n == 1:
                self.fill(0, self.x + 1, self.y)
            else:
                self.fill(0, max(width, self.x + 1), self.y)
        elif final == "s":
            self.saved = (self.x, self.y)
        elif final == "u":
            self.x, self.y = self.saved
        elif final == "t":
            p = self._params(raw)
            if len(p) == 4:
                c = rgb(p[1], p[2], p[3])
                if p[0] == 0:
                    self.bg_ext = c
                elif p[0] == 1:
                    self.fg_ext = c
        else:
            self.stats["unknown_csi"] += 1

    def _sgr(self, p: list[int]) -> None:
        i = 0
        n = len(p)
        while i < n:
            v = p[i]
            if v == 0:
                self.reset_attrs()
            elif v == 1:
                self.bold = True
            elif v == 5 or v == 6:
                self.blink = True
            elif v == 7:
                self.reverse = True
            elif v == 22:
                self.bold = False
            elif v == 25:
                self.blink = False
            elif v == 27:
                self.reverse = False
            elif 30 <= v <= 37:
                self.fg_idx = v - 30
                self.fg_ext = None
                self.stats["colored"] = True
            elif v == 39:
                self.fg_idx = 7
                self.fg_ext = None
            elif 40 <= v <= 47:
                self.bg_idx = v - 40
                self.bg_ext = None
                self.stats["colored"] = True
            elif v == 49:
                self.bg_idx = 0
                self.bg_ext = None
            elif 90 <= v <= 97:
                self.fg_ext = VGA16[8 + v - 90]
                self.stats["colored"] = True
            elif 100 <= v <= 107:
                self.bg_ext = VGA16[8 + v - 100]
                self.stats["colored"] = True
            elif v in (38, 48):
                mode = p[i + 1] if i + 1 < n else -1
                if mode == 5 and i + 2 < n:
                    c = xterm256(p[i + 2])
                    i += 2
                elif mode == 2 and i + 4 < n:
                    c = rgb(p[i + 2], p[i + 3], p[i + 4])
                    i += 4
                else:
                    i += 1
                    continue
                if v == 38:
                    self.fg_ext = c
                else:
                    self.bg_ext = c
                self.stats["colored"] = True
            i += 1


def interpret(text: str, cols: int = 80, ice: bool = False, wrap: str = "immediate"):
    it = Interpreter(cols=cols, ice=ice, wrap=wrap)
    it.feed(text)
    return it.grid(), it.stats
