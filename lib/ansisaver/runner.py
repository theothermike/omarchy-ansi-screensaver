"""`run`: the slideshow loop that lives inside the fullscreen terminal."""
from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import time
from pathlib import Path

from . import config as C
from . import effects, hypr, library as L, paths, theme as T, transitions
from .ansi import BLANK
from .grid import Grid, compose, grid_to_flat, read_flat, recolor, row_to_sgr
from .palette import DEFAULT_FG, VGA16, mix
from .term import Dismissed, Painter, Terminal

log = logging.getLogger("ansisaver.run")
BRANDING_ID = "__branding__"


def setup_logging() -> None:
    paths.ensure_dirs()
    try:
        if paths.LOG_FILE.exists() and paths.LOG_FILE.stat().st_size > 1_000_000:
            paths.LOG_FILE.unlink()
        handler = logging.FileHandler(paths.LOG_FILE)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger("ansisaver")
        root.handlers = [handler]
        root.setLevel(logging.INFO)
        root.propagate = False
    except OSError:
        pass


# ---------------------------------------------------------------- playlist

def branding_meta() -> dict | None:
    p = paths.BRANDING_ART
    if not p.is_file():
        return None
    return {"id": BRANDING_ID, "title": "Omarchy", "author": "", "group": "", "year": None,
            "format": "utf8", "enabled": True, "favorite": False, "animated": False, "cols": 80, "rows": 10}


def load_piece_grid(meta: dict) -> Grid:
    if meta["id"] == BRANDING_ID:
        text = paths.BRANDING_ART.read_text(encoding="utf-8", errors="replace")
        from .ansi import Interpreter
        it = Interpreter(cols=0)
        it.feed(text)
        return it.grid()
    return L.load_grid(meta)


class Playlist:
    def __init__(self, pieces: list[dict], cfg: dict, rng: random.Random, forced: str | None = None,
                 session_playlist: list | None = None):
        self.cfg = cfg
        self.rng = rng
        self.forced = forced
        self.pieces = {m["id"]: m for m in pieces}
        self.order = cfg.get("order", "shuffle")
        self.deck: list[str] = []
        self.last: str | None = None
        self.count = 0
        self.session = session_playlist or []
        self.session_index = 0
        self.branding_every = int(cfg.get("include_branding") or 0)
        self.skipped: set[str] = set()

    def mark_unusable(self, pid: str) -> None:
        self.skipped.add(pid)

    def _candidates(self) -> list[str]:
        return [pid for pid in self.pieces if pid not in self.skipped]

    def next(self) -> dict | None:
        self.count += 1
        if self.forced and self.forced in self.pieces:
            return self.pieces[self.forced]
        if self.branding_every and self.count % (self.branding_every + 1) == 0:
            b = branding_meta()
            if b:
                return b
        if self.session:
            for _ in range(len(self.session)):
                entry = self.session[self.session_index % len(self.session)]
                self.session_index += 1
                pid = entry.get("piece")
                if pid in self.pieces and pid not in self.skipped:
                    return self.pieces[pid]
        cands = self._candidates()
        if not cands:
            return None
        if self.order == "ordered":
            cands.sort(key=lambda p: (self.pieces[p].get("added") or "", self.pieces[p].get("title") or ""))
            idx = (self.count - 1) % len(cands)
            return self.pieces[cands[idx]]
        if self.order == "favorites":
            weights = [3.0 if self.pieces[p].get("favorite") else 1.0 for p in cands]
            for _ in range(8):
                pid = self.rng.choices(cands, weights=weights, k=1)[0]
                if pid != self.last or len(cands) == 1:
                    break
            self.last = pid
            return self.pieces[pid]
        # shuffle
        self.deck = [p for p in self.deck if p in self.pieces and p not in self.skipped]
        if not self.deck:
            self.deck = list(cands)
            self.rng.shuffle(self.deck)
            if len(self.deck) > 1 and self.deck[0] == self.last:
                self.deck.append(self.deck.pop(0))
        pid = self.deck.pop(0)
        self.last = pid
        return self.pieces[pid]


# ---------------------------------------------------------------- slideshow

class Slideshow:
    def __init__(self, args, cfg: dict, theme: T.Theme, pieces: list[dict], term: Terminal, session: dict):
        self.args = args
        self.cfg = cfg
        self.theme = theme
        self.term = term
        self.painter = Painter(term)
        self.session = session
        seed = int(time.time_ns() ^ (hash(args.monitor or "") & 0xFFFFFFFF))
        if cfg.get("multi_monitor") == "mirrored" and session.get("seed") is not None:
            seed = int(session["seed"])
        self.rng = random.Random(seed)
        session_playlist = session.get("playlist") if cfg.get("multi_monitor") == "mirrored" else None
        self.playlist = Playlist(pieces, cfg, self.rng, forced=args.piece, session_playlist=session_playlist)
        self.effect_weights = C.effect_weights(cfg)
        self.out_weights = C.transition_weights(cfg)
        fast = bool(args.fast)
        self.hold = 2.0 if fast else float(cfg.get("hold_seconds", 20))
        self.hold_top = 0.0 if fast else float(cfg.get("hold_top_seconds", 0))
        self.scroll_rate = 15.0 if fast else float(cfg.get("scroll_rows_per_second", 15))
        self.slide_max = float(cfg.get("slide_max_seconds", 120))
        self.fps = int(C.get(cfg, "transitions.fps", 30))
        self.slide_file = paths.RUNTIME_DIR / f"slide-{os.getpid()}.ans"
        self.slide_no = 0

    # -- helpers --------------------------------------------------------
    def colorize(self, grid: Grid) -> Grid:
        mode = self.cfg.get("ascii_color", "theme-gradient")
        if mode == "vga-grey":
            return grid
        if mode == "theme-foreground":
            c = self.theme.rgb("foreground")
            return recolor(grid, lambda r, n: c)
        a, b, c = self.theme.rgb("accent"), self.theme.rgb("foreground"), self.theme.rgb("light_foreground")

        def color_for_row(r: int, n: int) -> int:
            t = r / max(1, n - 1)
            return mix(a, b, t * 2) if t < 0.5 else mix(b, c, (t - 0.5) * 2)
        return recolor(grid, color_for_row)

    def caption_text(self, meta: dict) -> str:
        parts = [meta.get("title") or meta["id"]]
        if meta.get("author"):
            parts.append(" — " + meta["author"])
        if meta.get("group"):
            parts.append(" / " + meta["group"])
        if meta.get("year"):
            parts.append(f", {meta['year']}")
        return "".join(parts)

    def caption_spot(self, meta: dict, frame):
        """(row, col, text) for the caption, or None if it would cover art."""
        if not self.cfg.get("caption", True) or meta["id"] == BRANDING_ID:
            return None
        cols, rows = self.term.cols, self.term.rows
        text = self.caption_text(meta)[: max(0, cols - 2)]
        if not text:
            return None
        pos = self.cfg.get("caption_position", "br")
        col = cols - len(text) if pos[1] == "r" else 2

        def free(r: int) -> bool:
            line = frame[r - 1]
            return not any(line[x - 1] != BLANK for x in range(col, col + len(text)) if 0 < x <= cols)
        first, second = (rows, 1) if pos[0] == "b" else (1, rows)
        for r in (first, second):
            if free(r):
                return r, col, text
        return None

    def draw_caption(self, meta: dict, frame) -> bool:
        spot = self.caption_spot(meta, frame)
        if spot is None:
            return False
        row, col, text = spot
        c = self.theme.rgb("muted")
        r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
        self.term.write(f"\x1b[{row};{col}H\x1b[38;2;{r};{g};{b}m{text}\x1b[0m")
        self.term.flush()
        return True

    def choose_mode(self, meta: dict) -> str:
        forced = self.args.effect
        if forced == "baud":
            return "baud"
        if forced:
            return "ttfx"
        if meta.get("animated"):
            return "baud"
        w = self.cfg.get("reveal") or {}
        tw, bw = float(w.get("ttfx", 70)), float(w.get("baud", 30))
        if tw + bw <= 0:
            return "ttfx"
        return self.rng.choices(["ttfx", "baud"], weights=[tw, bw], k=1)[0]

    # -- reveal ------------------------------------------------------------
    def reveal_ttfx(self, frame, effect: str) -> None:
        term = self.term
        cols, rows = term.cols, term.rows
        # ttfx anchors the text's bounding box and drops leading blank rows,
        # which would shift a vertically centred piece to the top. An
        # invisible (black-on-black) dot in the top-left corner pins the box.
        ttfx_rows = [list(r) for r in frame]
        if ttfx_rows and all(c == BLANK for c in ttfx_rows[0]):
            ttfx_rows[0][0] = (".", 0x000000, None)
        flat = grid_to_flat(Grid(cols=cols, rows=ttfx_rows))
        self.slide_file.write_text(flat, encoding="utf-8")
        seed = self.rng.randrange(1, 2**31)
        argv = effects.build_argv(effect, str(self.slide_file), cols, rows, theme=self.theme, seed=seed,
                                  color_mode=C.get(self.cfg, "ttfx.existing_color_handling", "always"),
                                  fps_scale=float(C.get(self.cfg, "ttfx.frame_rate_scale", 1.0)), rng=self.rng)
        log.info("slide %d effect=%s seed=%d", self.slide_no, effect, seed)
        term.clear()
        term.flush()
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=term.fd_out, stderr=subprocess.DEVNULL)
        term.child = proc
        started = time.monotonic()
        max_s = float(C.get(self.cfg, "ttfx.max_seconds", 30))
        while proc.poll() is None:
            term.poll(0.03)
            if time.monotonic() - started > max_s:
                log.info("effect %s exceeded %.0fs; painting final frame", effect, max_s)
                term.kill_child()
                self.painter.paint(frame, force=True)
                break
        term.child = None
        self.painter.prime(frame)

    def reveal_baud(self, meta: dict, grid: Grid, x_off: int, y_off: int) -> int:
        from .baud import play
        return play(self, meta, grid, x_off, y_off)

    def scroll_rest(self, grid: Grid, top: int, rows: int, x_off: int, slide_started: float) -> int:
        """Reveal the rows below the first screenful the way a BBS would have:
        the screen scrolls one line at a time and each new line is drawn left
        to right, at `scroll_rows_per_second` (raised if the slide would
        overrun `slide_max_seconds`)."""
        term = self.term
        prows = grid.height
        remaining = prows - rows
        rate = max(self.scroll_rate, 0.1)
        budget = self.slide_max - (time.monotonic() - slide_started) - self.hold
        if budget > 0 and remaining / rate > budget:
            rate = remaining / budget
        row_time = 1.0 / rate
        segs = 4 if row_time >= 0.04 else 1
        log.info("scroll %d rows at %.1f rows/s", remaining, rate)
        next_due = time.monotonic()
        while top + rows < prows:
            row = grid.rows[top + rows]
            width = len(row)
            self.painter.scroll_blank()
            if width == 0:
                next_due += row_time
                term.poll(max(0.0, next_due - time.monotonic()))
            else:
                step = max(1, -(-width // segs))
                for a in range(0, width, step):
                    self.painter.draw_segment(row, x_off, a, min(width, a + step))
                    next_due += row_time / segs
                    term.poll(max(0.0, next_due - time.monotonic()))
            self.painter.commit_bottom(row, pad=x_off)
            top += 1
        return top

    # -- one slide -----------------------------------------------------------
    def slide(self) -> bool:
        term = self.term
        self.slide_no += 1
        meta = self.playlist.next()
        if meta is None:
            log.warning("no usable pieces")
            term.poll(5)
            return False
        try:
            grid = load_piece_grid(meta)
        except Exception as e:  # noqa: BLE001
            log.warning("piece %s unreadable: %s", meta["id"], e)
            self.playlist.mark_unusable(meta["id"])
            return False
        if meta.get("format") in ("ascii", "utf8") or not grid.is_colored():
            grid = self.colorize(grid)
        cols, rows = term.measure()
        pcols, prows = grid.painted_cols, grid.height
        if pcols > cols and self.cfg.get("wide_pieces", "skip") != "clip":
            log.info("skip %s: %d cols > %d", meta["id"], pcols, cols)
            self.playlist.mark_unusable(meta["id"])
            return False
        x_off = max(0, (cols - pcols) // 2)
        tall = prows > rows
        y_off = 0 if tall else max(0, (rows - prows) // 2)
        top = 0
        mode = self.choose_mode(meta)
        slide_started = time.monotonic()
        frame = compose(grid, cols, rows, x_off, y_off, top)
        if mode == "baud":
            try:
                top = self.reveal_baud(meta, grid, x_off, y_off)
            except ImportError:
                mode = "ttfx"
        if mode == "ttfx":
            effect = self.args.effect if self.args.effect in effects.TABLE else effects.pick(self.effect_weights, self.rng)
            self.reveal_ttfx(frame, effect)
        if tall and top == 0:
            if self.hold_top > 0:
                term.poll(self.hold_top)
            top = self.scroll_rest(grid, top, rows, x_off, slide_started)
        frame = compose(grid, cols, rows, x_off, y_off, top)
        if tall and self.caption_spot(meta, frame) is None and self.cfg.get("caption", True):
            # the art fills the last row: scroll once more so the caption gets
            # an empty line instead of covering the picture
            self.painter.scroll_blank()
            top += 1
            frame = compose(grid, cols, rows, x_off, y_off, top)
        self.painter.prime(frame)
        self.draw_caption(meta, frame)
        term.poll(self.hold)
        name = transitions.pick(self.out_weights, self.rng)
        gen = transitions.GENERATORS[name](frame, self.rng, self.fps)
        log.info("out=%s", name)
        step = 1.0 / self.fps
        for f in gen:
            t0 = time.monotonic()
            self.painter.paint(f)
            term.poll(max(0.0, step - (time.monotonic() - t0)))
        term.clear()
        self.painter.reset()
        return True


# ---------------------------------------------------------------- entry

def _plan(args, cfg, pieces) -> dict:
    return {"monitor": args.monitor, "window_class": args.window_class, "pieces": len(pieces),
            "order": cfg.get("order"), "reveal": cfg.get("reveal"), "effects": {k: v for k, v in C.effect_weights(cfg).items() if v > 0},
            "transitions": {k: v for k, v in C.transition_weights(cfg).items() if v > 0},
            "hold_seconds": cfg.get("hold_seconds"), "forced_piece": args.piece, "forced_effect": args.effect}


def run(args) -> int:
    setup_logging()
    paths.ensure_dirs()
    cfg = C.load()
    theme = T.load()
    pieces = [m for m in L.list_pieces() if m.get("enabled", True)]
    if args.piece and args.piece not in {m["id"] for m in pieces}:
        m = L.load_meta(args.piece)
        if m:
            pieces.append(m)
    session: dict = {}
    if args.session:
        try:
            session = json.loads(Path(args.session).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            session = {}
    if args.dry_run:
        print(json.dumps(_plan(args, cfg, pieces), indent=2))
        return 0
    if not pieces:
        log.error("library has no enabled pieces")
        return 1
    term = Terminal(args.window_class, use_hypr=not args.no_hypr)
    term.install_signals()
    rc = 0
    try:
        term.wait_for_resize()
        log.info("terminal %dx%d class=%s monitor=%s pt=%s", term.cols, term.rows, args.window_class, args.monitor, args.font_pt)
        if args.font_pt and args.monitor and not args.no_hypr:
            from .sizing import record_calibration
            record_calibration(args.monitor, args.font_kind or "unknown", float(args.font_pt), term.cols, term.rows)
        term.enter()
        show = Slideshow(args, cfg, theme, pieces, term, session)
        empty_streak = 0
        while True:
            ok = show.slide()
            empty_streak = 0 if ok else empty_streak + 1
            if args.once and ok:
                break
            if empty_streak > max(3, len(pieces)):
                log.error("no piece fits this terminal (%dx%d)", term.cols, term.rows)
                rc = 1
                break
    except Dismissed as e:
        log.info("dismissed: %s", e)
    except Exception as e:  # noqa: BLE001
        log.exception("runner crashed: %s", e)
        rc = 1
    finally:
        term.exit()
        try:
            show_file = paths.RUNTIME_DIR / f"slide-{os.getpid()}.ans"
            show_file.unlink(missing_ok=True)
        except OSError:
            pass
        if not args.once and not args.no_hypr:
            _close_siblings(args.window_class)
    return rc


def _close_siblings(window_class: str) -> None:
    import signal
    subprocess.run(["pkill", "-x", "ttfx"], capture_output=True)
    for pid in hypr.class_pids(window_class):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
