"""Out-transitions: generators of full-screen frames ending fully black."""
from __future__ import annotations

import math
import random
from typing import Iterator

from .ansi import BLANK, Cell
from .palette import BLACK, mix, scale, split, rgb

Frame = list[list[Cell]]

DURATIONS = {"fade": 0.6, "dissolve": 0.8, "wipe": 0.6, "melt": 1.2, "curtain": 0.6,
             "glitch": 0.7, "blocks": 1.0, "cut": 0.0}
ALL = sorted(DURATIONS)


def _copy(frame: Frame) -> Frame:
    return [list(r) for r in frame]


def _black(rows: int, cols: int) -> Frame:
    return [[BLANK] * cols for _ in range(rows)]


def _painted(frame: Frame) -> list[tuple[int, int]]:
    out = []
    for y, row in enumerate(frame):
        for x, (ch, _fg, bg) in enumerate(row):
            if ch != " " or bg is not None:
                out.append((x, y))
    return out


def fade(frame: Frame, rng: random.Random, fps: int) -> Iterator[Frame]:
    steps = max(4, int(DURATIONS["fade"] * fps))
    for i in range(1, steps + 1):
        f = 1.0 - i / steps
        memo: dict[int, int] = {}

        def sc(c: int) -> int:
            v = memo.get(c)
            if v is None:
                v = scale(c, f)
                memo[c] = v
            return v
        yield [[(ch, sc(fg), (sc(bg) if bg is not None else None)) if (ch != " " or bg is not None) else cell
                for cell in row for (ch, fg, bg) in (cell,)] for row in frame]
    yield _black(len(frame), len(frame[0]) if frame else 0)


def dissolve(frame: Frame, rng: random.Random, fps: int) -> Iterator[Frame]:
    cells = _painted(frame)
    rng.shuffle(cells)
    steps = max(4, int(DURATIONS["dissolve"] * fps))
    per = max(1, math.ceil(len(cells) / steps))
    cur = _copy(frame)
    for i in range(0, len(cells), per):
        for x, y in cells[i:i + per]:
            cur[y][x] = BLANK
        yield _copy(cur)
    yield _black(len(frame), len(frame[0]) if frame else 0)


def wipe(frame: Frame, rng: random.Random, fps: int) -> Iterator[Frame]:
    rows, cols = len(frame), (len(frame[0]) if frame else 0)
    mode = rng.choice(["left", "right", "top", "bottom", "diag", "center-out", "center-in"])
    cy, cx = (rows - 1) / 2, (cols - 1) / 2

    def dist(x: int, y: int) -> float:
        if mode == "left":
            return x
        if mode == "right":
            return cols - 1 - x
        if mode == "top":
            return y
        if mode == "bottom":
            return rows - 1 - y
        if mode == "diag":
            return x + y * 2
        d = max(abs(x - cx) / max(cx, 1), abs(y - cy) / max(cy, 1))
        return d if mode == "center-out" else 1.0 - d
    maxd = max((dist(x, y) for y in range(rows) for x in range(cols)), default=1) or 1
    steps = max(4, int(DURATIONS["wipe"] * fps))
    cur = _copy(frame)
    for i in range(1, steps + 1):
        t = maxd * i / steps
        for y in range(rows):
            row = cur[y]
            for x in range(cols):
                if row[x] is not BLANK and dist(x, y) <= t:
                    row[x] = BLANK
        yield _copy(cur)
    yield _black(rows, cols)


def melt(frame: Frame, rng: random.Random, fps: int) -> Iterator[Frame]:
    rows, cols = len(frame), (len(frame[0]) if frame else 0)
    delay = [0] * cols
    d = rng.randint(0, 8)
    for c in range(cols):
        d = max(0, min(8, d + rng.randint(-1, 1)))
        delay[c] = d
    off = [0] * cols
    vel = [0.0] * cols
    frames = max(6, int(DURATIONS["melt"] * fps))
    step = 0
    while True:
        step += 1
        done = True
        for c in range(cols):
            if step > delay[c]:
                vel[c] = min(vel[c] + rows / (frames * 3), rows / 6)
                off[c] += max(1, int(vel[c]))
            if off[c] < rows:
                done = False
        cur = _black(rows, cols)
        for c in range(cols):
            o = off[c]
            for y in range(o, rows):
                cur[y][c] = frame[y - o][c]
        yield cur
        if done or step > frames * 3:
            break
    yield _black(rows, cols)


def curtain(frame: Frame, rng: random.Random, fps: int) -> Iterator[Frame]:
    rows, cols = len(frame), (len(frame[0]) if frame else 0)
    vertical = rng.random() < 0.5
    steps = max(4, int(DURATIONS["curtain"] * fps))
    for i in range(1, steps + 1):
        cur = _black(rows, cols)
        if vertical:
            shift = int(math.ceil(rows / 2 * i / steps))
            half = rows // 2
            for y in range(rows):
                ny = y - shift if y < half else y + shift
                if 0 <= ny < rows:
                    cur[ny] = list(frame[y])
        else:
            shift = int(math.ceil(cols / 2 * i / steps))
            half = cols // 2
            for y in range(rows):
                for x in range(cols):
                    nx = x - shift if x < half else x + shift
                    if 0 <= nx < cols:
                        cur[y][nx] = frame[y][x]
        yield cur
    yield _black(rows, cols)


def glitch(frame: Frame, rng: random.Random, fps: int) -> Iterator[Frame]:
    rows, cols = len(frame), (len(frame[0]) if frame else 0)
    steps = max(6, int(DURATIONS["glitch"] * fps))
    for i in range(1, steps + 1):
        intensity = i / steps
        cur = _copy(frame)
        for _ in range(int(5 + 12 * intensity)):
            y0 = rng.randrange(rows)
            h = rng.randint(1, 3)
            dx = rng.randint(-8, 8)
            swap = rng.random() < 0.4
            for y in range(y0, min(rows, y0 + h)):
                src = frame[y]
                row = [BLANK] * cols
                for x in range(cols):
                    nx = x + dx
                    if 0 <= nx < cols:
                        ch, fg, bg = src[x]
                        if swap:
                            r, g, b = split(fg)
                            fg = rgb(b, g, r)
                            if bg is not None:
                                r, g, b = split(bg)
                                bg = rgb(b, g, r)
                        row[nx] = (ch, fg, bg)
                cur[y] = row
        if i > steps * 0.6:
            for _ in range(int(rows * (i / steps - 0.6) * 2)):
                cur[rng.randrange(rows)] = [BLANK] * cols
        yield cur
    yield _black(rows, cols)


def _perceived(cell: Cell) -> int:
    ch, fg, bg = cell
    b = bg if bg is not None else BLACK
    if ch == " ":
        return b
    if ch == "█":
        return fg
    if ch in "▄▀▌▐":
        return mix(b, fg, 0.5)
    if ch == "▓":
        return mix(b, fg, 0.75)
    if ch == "▒":
        return mix(b, fg, 0.5)
    if ch == "░":
        return mix(b, fg, 0.25)
    return mix(b, fg, 0.35)


def blocks(frame: Frame, rng: random.Random, fps: int) -> Iterator[Frame]:
    rows, cols = len(frame), (len(frame[0]) if frame else 0)
    sizes = [(2, 1), (4, 2), (8, 4), (16, 8)]
    last = frame
    for bw, bh in sizes:
        cur = _black(rows, cols)
        for by in range(0, rows, bh):
            for bx in range(0, cols, bw):
                acc = [0, 0, 0]
                n = 0
                for y in range(by, min(rows, by + bh)):
                    for x in range(bx, min(cols, bx + bw)):
                        r, g, b = split(_perceived(frame[y][x]))
                        acc[0] += r; acc[1] += g; acc[2] += b
                        n += 1
                c = rgb(acc[0] // n, acc[1] // n, acc[2] // n) if n else BLACK
                cell: Cell = ("█", c, None) if c != BLACK else BLANK
                for y in range(by, min(rows, by + bh)):
                    for x in range(bx, min(cols, bx + bw)):
                        cur[y][x] = cell
        last = cur
        for _ in range(max(1, int(fps * DURATIONS["blocks"] / 5))):
            yield last
    for i in range(1, 5):
        f = 1 - i / 4
        yield [[(ch, scale(fg, f), None) if ch != " " else cell for cell in row for (ch, fg, _bg) in (cell,)] for row in last]
    yield _black(rows, cols)


def cut(frame: Frame, rng: random.Random, fps: int) -> Iterator[Frame]:
    yield _black(len(frame), len(frame[0]) if frame else 0)


GENERATORS = {"fade": fade, "dissolve": dissolve, "wipe": wipe, "melt": melt, "curtain": curtain,
              "glitch": glitch, "blocks": blocks, "cut": cut}


def pick(weights: dict[str, float], rng: random.Random) -> str:
    items = [(k, w) for k, w in weights.items() if k in GENERATORS and w > 0]
    if not items:
        return "cut"
    names, ws = zip(*items)
    return rng.choices(names, weights=ws, k=1)[0]
