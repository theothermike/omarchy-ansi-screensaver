"""Terminal control for the runner: raw mode, alt screen, mouse reporting,
dismissal polling and a diffing frame painter."""
from __future__ import annotations

import os
import select
import signal
import sys
import termios
import time
import tty

from . import hypr
from .grid import row_to_sgr


class Dismissed(Exception):
    """Raised when the user (or the system) ends the screensaver."""


class Terminal:
    def __init__(self, window_class: str, use_hypr: bool = True, mouse: bool = True):
        self.window_class = window_class
        self.use_hypr = use_hypr
        self.mouse = mouse
        self.fd_in = sys.stdin.fileno() if sys.stdin and sys.stdin.isatty() else -1
        self.fd_out = sys.stdout.fileno()
        self._saved = None
        self._entered = False
        self._last_focus_check = 0.0
        self._armed_at = 0.0
        self.cols = 80
        self.rows = 24
        self.child = None
        self._buf: list[bytes] = []

    # -- setup ----------------------------------------------------------
    def install_signals(self) -> None:
        def handler(signum, _frame):
            raise Dismissed(f"signal {signum}")
        for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGQUIT):
            signal.signal(s, handler)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    def wait_for_resize(self, timeout: float = 2.0, settle: float = 0.3) -> None:
        """Terminals allocate the pty at 80x24 and resize once the compositor
        sizes the window -- possibly twice (floating size, then fullscreen).
        Wait for the first change, then until the size has been stable."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            size = os.get_terminal_size(self.fd_out)
            if (size.columns, size.lines) != (80, 24):
                break
            time.sleep(0.02)
        last = os.get_terminal_size(self.fd_out)
        stable_since = time.monotonic()
        end = time.monotonic() + max(settle * 5, 1.5)
        while time.monotonic() < end:
            size = os.get_terminal_size(self.fd_out)
            if size != last:
                last = size
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= settle:
                break
            time.sleep(0.02)
        self.measure()

    def measure(self) -> tuple[int, int]:
        size = os.get_terminal_size(self.fd_out)
        self.cols, self.rows = size.columns, size.lines
        return self.cols, self.rows

    def enter(self, grace: float = 1.0) -> None:
        if self.fd_in >= 0:
            self._saved = termios.tcgetattr(self.fd_in)
            tty.setcbreak(self.fd_in)
        self.write("\x1b]11;rgb:00/00/00\x07")
        self.write("\x1b[?1049h\x1b[?25l")
        if self.mouse:
            self.write("\x1b[?1006h\x1b[?1003h")
        self.write("\x1b[2J\x1b[H")
        self.flush()
        self._entered = True
        if self.use_hypr:
            try:
                hypr.cursor_invisible(True)
            except Exception:  # noqa: BLE001
                pass
        # swallow the mouse report ghostty may emit when mapping under the pointer
        end = time.monotonic() + grace
        while time.monotonic() < end:
            r, _, _ = select.select([self.fd_in], [], [], max(0.0, end - time.monotonic())) if self.fd_in >= 0 else ([], [], [])
            if r:
                try:
                    os.read(self.fd_in, 4096)
                except OSError:
                    break
        self._armed_at = time.monotonic()

    def exit(self) -> None:
        if not self._entered:
            return
        self._entered = False
        try:
            self.kill_child()
            self.write("\x1b[?1003l\x1b[?1006l\x1b[0m\x1b[?25h\x1b[?1049l")
            self.flush()
        except Exception:  # noqa: BLE001
            pass
        if self._saved is not None and self.fd_in >= 0:
            try:
                termios.tcsetattr(self.fd_in, termios.TCSADRAIN, self._saved)
            except termios.error:
                pass
        if self.use_hypr:
            try:
                hypr.cursor_invisible(False)
            except Exception:  # noqa: BLE001
                pass

    # -- output ---------------------------------------------------------
    def write(self, s: str) -> None:
        self._buf.append(s.encode("utf-8", "replace"))

    def flush(self) -> None:
        if not self._buf:
            return
        data = b"".join(self._buf)
        self._buf.clear()
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.fd_out, view)
            except InterruptedError:
                continue
            except OSError as e:
                raise Dismissed(f"terminal gone ({e.errno})") from e
            view = view[n:]

    def clear(self) -> None:
        self.write("\x1b[2J\x1b[H")
        self.flush()

    # -- dismissal --------------------------------------------------------
    def kill_child(self) -> None:
        p = self.child
        self.child = None
        if p is None or p.poll() is not None:
            return
        try:
            p.terminate()
            try:
                p.wait(0.5)
            except Exception:  # noqa: BLE001
                p.kill()
        except OSError:
            pass

    def in_focus(self) -> bool:
        if not self.use_hypr:
            return True
        cls = hypr.active_window_class()
        return cls is None or cls == self.window_class

    def poll(self, timeout: float) -> None:
        """Sleep up to `timeout` seconds; raise Dismissed on input, focus loss
        or when a child ttfx dies from a signal."""
        end = time.monotonic() + max(0.0, timeout)
        while True:
            now = time.monotonic()
            if now - self._last_focus_check >= 1.0:
                self._last_focus_check = now
                if not self.in_focus():
                    raise Dismissed("focus lost")
            if self.child is not None:
                rc = self.child.poll()
                if rc is not None and rc < 0:
                    self.child = None
                    raise Dismissed(f"ttfx killed ({rc})")
            remaining = end - now
            if remaining <= 0:
                return
            step = min(remaining, 0.25)
            if self.fd_in >= 0:
                r, _, _ = select.select([self.fd_in], [], [], step)
                if r:
                    try:
                        data = os.read(self.fd_in, 4096)
                    except OSError:
                        data = b""
                    if data or True:
                        raise Dismissed("input")
            else:
                time.sleep(step)


class Painter:
    """Full-screen frame painter with per-row diffing."""

    def __init__(self, term: Terminal):
        self.term = term
        self.cache: list[str] = []

    def reset(self) -> None:
        self.cache = []

    def prime(self, frame) -> None:
        self.cache = [row_to_sgr(row, upto=len(row)) for row in frame]

    def paint(self, frame, force: bool = False) -> None:
        t = self.term
        out = []
        for r, row in enumerate(frame):
            s = row_to_sgr(row, upto=len(row))
            if force or r >= len(self.cache) or self.cache[r] != s:
                out.append(f"\x1b[{r + 1};1H{s}\x1b[K")
        if r_len := len(frame):
            self.cache = (self.cache + [""] * r_len)[:r_len]
            for r, row in enumerate(frame):
                self.cache[r] = row_to_sgr(row, upto=len(row))
        if out:
            t.write("".join(out))
            t.flush()

    def scroll_up(self, new_row, pad: int = 0) -> None:
        """Scroll the screen one line and draw `new_row` at the bottom."""
        t = self.term
        s = row_to_sgr(new_row, upto=self.fit(new_row, pad), pad=pad)
        t.write(f"\x1b[S\x1b[{t.rows};1H{s}\x1b[K")
        t.flush()
        if self.cache:
            self.cache = self.cache[1:] + [s]

    def scroll_blank(self) -> None:
        """Scroll one line; the new bottom line is left empty."""
        self.term.write("\x1b[S")
        self.term.flush()
        if self.cache:
            self.cache = self.cache[1:] + [""]

    def fit(self, row, pad: int = 0) -> int:
        """How many cells of `row` fit on a line after `pad` columns. Writing
        past the last column wraps, and on the bottom line that scrolls the
        screen -- a blank line under every row of a clipped wide piece."""
        return max(0, min(len(row), self.term.cols - pad))

    def draw_segment(self, row, pad: int, a: int, b: int) -> None:
        """Paint cells [a, b) of `row` on the bottom line (progressive reveal)."""
        b = min(b, self.fit(row, pad))
        if b <= a:
            return
        t = self.term
        t.write(f"\x1b[{t.rows};{pad + a + 1}H{row_to_sgr(row[a:b], upto=b - a)}")
        t.flush()

    def commit_bottom(self, row, pad: int = 0) -> None:
        if self.cache:
            self.cache[-1] = row_to_sgr(row, upto=self.fit(row, pad), pad=pad)
