"""Baud-rate emulated reveal: replay the decoded original through the
interpreter, mirroring every cell write to the terminal at BBS speed."""
from __future__ import annotations

import time

from . import config as C
from . import library as L
from .ansi import Interpreter
from .grid import row_to_sgr
from .palette import split

RATES = (2400, 9600, 14400, 28800, 57600)


class TermSink:
    def __init__(self, term, rows: int, x_off: int, y_off: int):
        self.term = term
        self.rows = rows
        self.x_off = x_off
        self.y_off = y_off
        self.top = 0
        self.last = None
        self.fg = None
        self.bg = None
        self.pending: list[str] = []

    def _scroll_to(self, top: int) -> None:
        n = top - self.top
        if n <= 0:
            return
        # Reset first: with background-colour-erase the terminal paints the
        # lines it scrolls in with the current background, full width --
        # coloured bars beyond the art. The next cell re-emits its colours.
        self.pending.append(f"\x1b[0m\x1b[{self.rows};1H" + "\n" * n)
        self.fg = self.bg = None
        self.top = top
        self.last = None

    def put(self, x: int, y: int, cell) -> None:
        ch, fg, bg = cell
        sy = y + self.y_off
        if sy >= self.top + self.rows:
            self._scroll_to(sy - self.rows + 1)
        row = sy - self.top + 1
        col = x + self.x_off + 1
        if col > self.term.cols:
            # clipped wide piece: printing here would wrap onto the next line
            self.last = None
            return
        if self.last != (col, row):
            self.pending.append(f"\x1b[{row};{col}H")
        if bg != self.bg:
            if bg is None:
                self.pending.append("\x1b[49m")
            else:
                r, g, b = split(bg)
                self.pending.append(f"\x1b[48;2;{r};{g};{b}m")
            self.bg = bg
        if fg != self.fg and ch != " ":
            r, g, b = split(fg)
            self.pending.append(f"\x1b[38;2;{r};{g};{b}m")
            self.fg = fg
        self.pending.append(ch)
        self.last = (col + 1, row)

    def flush(self) -> None:
        if self.pending:
            self.term.write("".join(self.pending))
            self.term.flush()
            self.pending.clear()


def choose_rate(cfg: dict, nchars: int) -> float:
    """Characters per second."""
    rate = C.get(cfg, "baud.rate", "auto")
    target = float(C.get(cfg, "baud.target_seconds", 20))
    max_s = float(C.get(cfg, "baud.max_seconds", 45))
    if rate == "auto":
        cps = None
        for r in RATES:
            if nchars / (r / 10) <= target:
                cps = r / 10
                break
        if cps is None:
            cps = RATES[-1] / 10
    else:
        cps = float(rate) / 10
    if nchars / cps > max_s:
        cps = nchars / max_s
    return cps


def play(show, meta: dict, grid, x_off: int, y_off: int) -> int:
    """Reveal `meta` by replaying its original bytes. Returns the final
    viewport top row (for tall pieces the screen has scrolled)."""
    term = show.term
    cols, rows = term.cols, term.rows
    if meta["id"] == "__branding__":
        raise ImportError("no original for branding art")
    text = L.load_original_text(meta)
    sink = TermSink(term, rows, x_off, y_off)
    it = Interpreter(cols=int(meta.get("cols") or 80) if meta.get("format") != "ascii" else 0,
                     ice=bool(meta.get("ice")), wrap=meta.get("wrap", "immediate"), sink=sink.put)
    if meta.get("sauce") and meta["sauce"].get("tinfo1"):
        it.cols = int(meta["sauce"]["tinfo1"]) if 1 <= int(meta["sauce"]["tinfo1"]) <= 1000 else it.cols
    cps = choose_rate(show.cfg, len(text))
    show_cursor = bool(C.get(show.cfg, "baud.show_cursor", True))
    term.clear()
    if show_cursor:
        term.write("\x1b[?25h")
    term.flush()
    tick = 1 / 60
    per_tick = max(1, int(cps * tick))
    pos = 0
    n = len(text)
    started = time.monotonic()
    while pos < n and not it.stopped:
        it.feed(text[pos:pos + per_tick])
        pos += per_tick
        sink.flush()
        # keep the real cursor where the art's cursor is
        elapsed = time.monotonic() - started
        due = pos / cps
        term.poll(max(0.0, due - elapsed))
    sink.flush()
    term.write("\x1b[0m" + ("\x1b[?25l" if show_cursor else ""))  # leave no colour armed
    term.flush()
    top = sink.top
    # the terminal now shows grid rows [top-y_off, ...]; prime the painter
    from .grid import compose
    frame = compose(grid, cols, rows, x_off, y_off, max(0, top))
    show.painter.prime(frame)
    return max(0, top)
