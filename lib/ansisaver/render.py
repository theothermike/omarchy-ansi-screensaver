"""Render grids to PNG with the vendored VGA font (Pillow, optional)."""
from __future__ import annotations

import json
from pathlib import Path

from . import library as L, paths
from .palette import split

CELL_W, CELL_H = 8, 16
MAX_ROWS = 300
THUMB_W = 320
THUMB_H = 640


def available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


class Renderer:
    def __init__(self):
        from PIL import Image, ImageDraw, ImageFont
        self.Image = Image
        self.ImageDraw = ImageDraw
        self.font = ImageFont.truetype(str(paths.VGA_TTF), CELL_H)
        self.masks: dict[str, object] = {}

    def mask(self, ch: str):
        m = self.masks.get(ch)
        if m is None:
            img = self.Image.new("L", (CELL_W, CELL_H), 0)
            d = self.ImageDraw.Draw(img)
            try:
                d.text((0, 0), ch, font=self.font, fill=255)
            except Exception:  # noqa: BLE001
                pass
            m = img
            self.masks[ch] = m
        return m

    def render(self, grid, max_rows: int = MAX_ROWS):
        rows = grid.rows[:max_rows]
        cols = max(1, grid.painted_cols)
        img = self.Image.new("RGB", (cols * CELL_W, max(1, len(rows)) * CELL_H), (0, 0, 0))
        for y, row in enumerate(rows):
            for x in range(min(cols, len(row))):
                ch, fg, bg = row[x]
                box = (x * CELL_W, y * CELL_H)
                if bg is not None:
                    img.paste(split(bg), (box[0], box[1], box[0] + CELL_W, box[1] + CELL_H))
                if ch != " ":
                    img.paste(split(fg), (box[0], box[1], box[0] + CELL_W, box[1] + CELL_H), self.mask(ch))
        return img

    def thumb(self, img):
        w, h = img.size
        tw = min(THUMB_W, w)
        th = max(1, round(h * tw / w))
        t = img.resize((tw, th), self.Image.LANCZOS) if (tw, th) != (w, h) else img.copy()
        if th > THUMB_H:
            t = t.crop((0, 0, tw, THUMB_H))
        return t


_renderer: Renderer | None = None


def renderer() -> Renderer:
    global _renderer
    if _renderer is None:
        _renderer = Renderer()
    return _renderer


def render_piece(meta: dict, force: bool = False) -> dict:
    d = L.piece_dir(meta["id"])
    render_p, thumb_p = d / "render.png", d / "thumb.png"
    if not force and render_p.exists() and thumb_p.exists():
        return {"id": meta["id"], "render": str(render_p), "thumb": str(thumb_p), "cached": True}
    grid = L.load_grid(meta)
    r = renderer()
    img = r.render(grid)
    img.save(render_p, optimize=True)
    r.thumb(img).save(thumb_p, optimize=True)
    meta["render"] = "render.png"
    meta["thumb"] = "thumb.png"
    meta["render_truncated"] = grid.height > MAX_ROWS
    L.save_meta(meta)
    return {"id": meta["id"], "render": str(render_p), "thumb": str(thumb_p), "cached": False}


def render_grid_to(grid, out_dir: Path, stem: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    r = renderer()
    img = r.render(grid)
    render_p, thumb_p = out_dir / f"{stem}.png", out_dir / f"{stem}.thumb.png"
    img.save(render_p, optimize=True)
    r.thumb(img).save(thumb_p, optimize=True)
    return {"render": str(render_p), "png": str(thumb_p), "cols": grid.painted_cols, "rows": grid.height}


def cmd_thumb(args) -> int:
    from .cli import Progress, emit, fail
    if not available():
        return fail(args, "Pillow is missing: add the python-pillow package to render thumbnails")
    if args.id:
        m = L.load_meta(args.id)
        if not m:
            return fail(args, f"unknown piece {args.id}")
        emit(args, render_piece(m, force=args.force))
        return 0
    prog = Progress(args.progress)
    pieces = L.list_pieces()
    done, failed = [], []
    for i, m in enumerate(pieces):
        prog(i + 1, len(pieces), m["id"])
        try:
            res = render_piece(m, force=args.force and not args.missing)
            if not res["cached"]:
                done.append(m["id"])
        except Exception as e:  # noqa: BLE001
            failed.append({"id": m["id"], "reason": str(e)})
    from .config import touch_revision
    touch_revision()
    result = {"rendered": done, "failed": failed, "total": len(pieces)}
    if args.progress:
        prog.done(result)
    else:
        emit(args, result, f"rendered {len(done)} of {len(pieces)} ({len(failed)} failed)")
    return 0
