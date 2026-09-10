"""The art library: ~/.config/omarchy/ansi-screensaver/library/<id>/."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import NORMALIZER_VERSION, paths
from . import ansi as A
from . import sauce as S
from .config import touch_revision
from .grid import Grid, grid_to_flat, read_flat

ART_EXTS = (".ans", ".asc", ".txt", ".nfo", ".diz", ".ansi", ".ice", ".acd", ".cia", ".dds", ".mir", ".rem", ".fir", ".fire", ".blk",
            ".bld", ".lit", ".msg", ".art", ".lgc", ".tpa", ".tri", ".imp", ".fuel", ".ess", ".law", ".dez", ".bad", ".goa", ".kts")
REJECT_EXTS = (".xb", ".bin", ".rip", ".pcb", ".avt", ".png", ".gif", ".jpg", ".jpeg", ".mp4", ".mp3", ".it", ".xm", ".mod", ".s3m", ".zip", ".exe", ".com")


class ImportError_(Exception):
    pass


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:40] or "piece"


def make_id(stem: str, digest: str) -> str:
    return f"{slug(stem)}-{digest[:6]}"


@dataclass
class Normalized:
    grid: Grid
    meta: dict
    text: str            # decoded original text (for the baud player)
    warnings: list[str] = field(default_factory=list)


def classify(sauce: S.Sauce | None, stats: dict, encoding: str, colored: bool) -> str:
    if sauce is not None and sauce.is_ansimation:
        return "ansimation"
    if stats.get("clears", 0) > 0 or stats.get("overwrites", 0) > 50:
        return "ansimation"
    if colored:
        return "ansi"
    return "utf8" if encoding == "utf8" else "ascii"


def normalize(data: bytes, filename: str, *, encoding: str | None = None, wrap: str = "immediate",
              bce: bool = True, columns: int | None = None) -> Normalized:
    ext = os.path.splitext(filename)[1].lower()
    if ext in REJECT_EXTS:
        raise ImportError_(f"{filename}: {ext} files are not supported (only character-based ANSI/ASCII art)")
    body, sauce = S.parse(data)
    if sauce is not None and sauce.datatype not in (0, 1):
        raise ImportError_(f"{filename}: SAUCE datatype {sauce.datatype} is not character art")
    enc = A.detect_encoding(body, sauce, encoding)
    text = A.decode(body, enc)
    if columns is None:
        columns = sauce.columns if sauce else None
        if columns is None:
            columns = 0 if ext in (".asc", ".txt", ".nfo", ".diz") else 80
    it = A.Interpreter(cols=columns, ice=bool(sauce.ice) if sauce else False, wrap=wrap)
    if not bce:
        it.fill = lambda x0, x1, y: None  # type: ignore[assignment]
    it.feed(text)
    grid = it.grid()
    warnings: list[str] = []
    if grid.height == 0:
        raise ImportError_(f"{filename}: no visible characters")
    if grid.height > 1000:
        warnings.append(f"very tall: {grid.height} rows")
    if it.stats["unknown_csi"]:
        warnings.append(f"{it.stats['unknown_csi']} unsupported escape sequences ignored")
    colored = grid.is_colored()
    fmt = classify(sauce, it.stats, enc, colored)
    stem = os.path.splitext(os.path.basename(filename))[0]
    digest = sha256(data)
    meta: dict[str, Any] = {
        "id": make_id(stem, digest),
        "version": NORMALIZER_VERSION,
        "title": (sauce.title if sauce and sauce.title else stem),
        "author": (sauce.author if sauce else ""),
        "group": (sauce.group if sauce else ""),
        "year": (sauce.year if sauce else None),
        "date": (sauce.date if sauce else ""),
        "cols": max(grid.painted_cols, 1),
        "rows": grid.height,
        "format": fmt,
        "encoding": enc,
        "ice": bool(sauce.ice) if sauce else False,
        "wrap": wrap,
        "font": (sauce.tinfos if sauce else ""),
        "letter_spacing": (sauce.letter_spacing if sauce else None),
        "aspect": (sauce.aspect if sauce else None),
        "animated": fmt == "ansimation",
        "bytes": len(data),
        "hash": f"sha256:{digest}",
        "original": f"original{ext if ext in ART_EXTS else '.txt'}",
        "sauce": sauce.as_dict() if sauce else None,
        "comments": list(sauce.comments) if sauce else [],
        "source": {"provider": "local", "entry": None, "url": None, "pack": None, "image_url": None,
                   "license_note": None, "fetched": None},
        "tags": [],
        "category": None,
        "enabled": True,
        "favorite": False,
        "bundled": False,
        "added": now_iso(),
        "thumb": None,
        "render": None,
        "warnings": warnings,
    }
    return Normalized(grid=grid, meta=meta, text=text, warnings=warnings)


# -- index -----------------------------------------------------------------

def _read_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(p: Path, obj: Any) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def piece_dir(pid: str) -> Path:
    return paths.LIBRARY_DIR / pid


def load_meta(pid: str) -> dict | None:
    p = piece_dir(pid) / "meta.json"
    try:
        return _read_json(p)
    except (OSError, ValueError):
        return None


def save_meta(meta: dict) -> None:
    _write_json(piece_dir(meta["id"]) / "meta.json", meta)


def list_pieces() -> list[dict]:
    out = []
    if not paths.LIBRARY_DIR.is_dir():
        return out
    for d in sorted(paths.LIBRARY_DIR.iterdir()):
        if d.is_dir():
            m = load_meta(d.name)
            if m:
                out.append(m)
    return out


def hash_index() -> dict[str, str]:
    try:
        idx = _read_json(paths.LIBRARY_INDEX)
        if isinstance(idx, dict):
            return idx
    except (OSError, ValueError):
        pass
    return rebuild_index()


def rebuild_index() -> dict[str, str]:
    idx = {m["hash"]: m["id"] for m in list_pieces() if m.get("hash")}
    paths.LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(paths.LIBRARY_INDEX, idx)
    return idx


def _index_add(h: str, pid: str) -> None:
    idx = hash_index()
    idx[h] = pid
    _write_json(paths.LIBRARY_INDEX, idx)


# -- import ------------------------------------------------------------------

def store(norm: Normalized, data: bytes, *, source: dict | None = None, overrides: dict | None = None,
          force: bool = False, bundled: bool = False, into: Path | None = None) -> tuple[dict, bool]:
    """Write a normalised piece into the library (or `into`/<id>/ for bundling).
    Returns (meta, created)."""
    meta = dict(norm.meta)
    if source:
        meta["source"] = {**meta["source"], **{k: v for k, v in source.items() if v is not None}}
    if overrides:
        for k, v in overrides.items():
            if v is not None and k in meta:
                meta[k] = v
    meta["bundled"] = bundled
    base = into if into is not None else paths.LIBRARY_DIR
    if into is None and not force:
        existing = hash_index().get(meta["hash"])
        if existing and piece_dir(existing).is_dir():
            return load_meta(existing) or meta, False
    d = base / meta["id"]
    if d.exists() and not force and into is None:
        return load_meta(meta["id"]) or meta, False
    d.mkdir(parents=True, exist_ok=True)
    with open(d / meta["original"], "wb") as f:
        f.write(data)
    if into is None:
        with open(d / "flat.ans", "w", encoding="utf-8", newline="\n") as f:
            f.write(grid_to_flat(norm.grid))
    _write_json(d / "meta.json", meta)
    if into is None:
        _index_add(meta["hash"], meta["id"])
        try:  # thumbnails are best-effort (Pillow optional)
            from .render import available, render_piece
            if available():
                render_piece(meta, force=True)
        except Exception:  # noqa: BLE001
            pass
        touch_revision()
    return meta, True


def import_bytes(data: bytes, filename: str, **kw) -> tuple[dict, bool]:
    opts = {k: kw.pop(k) for k in ("encoding", "wrap", "bce", "columns") if k in kw}
    norm = normalize(data, filename, **opts)
    return store(norm, data, **kw)


def ensure_flat(meta: dict) -> Path:
    """Re-normalise a piece whose flat.ans is missing or stale; return its path."""
    d = piece_dir(meta["id"])
    flat = d / "flat.ans"
    if flat.is_file() and meta.get("version") == NORMALIZER_VERSION:
        return flat
    data = (d / meta["original"]).read_bytes()
    norm = normalize(data, meta["original"], encoding=meta.get("encoding"), wrap=meta.get("wrap", "immediate"))
    with open(flat, "w", encoding="utf-8", newline="\n") as f:
        f.write(grid_to_flat(norm.grid))
    for k in ("cols", "rows", "format", "animated"):
        meta[k] = norm.meta[k]
    meta["version"] = NORMALIZER_VERSION
    save_meta(meta)
    return flat


def load_grid(meta: dict) -> Grid:
    flat = ensure_flat(meta)
    return read_flat(flat.read_text(encoding="utf-8"))


def load_original_text(meta: dict) -> str:
    d = piece_dir(meta["id"])
    data = (d / meta["original"]).read_bytes()
    body, _ = S.parse(data)
    return A.decode(body, meta.get("encoding", "cp437"))


# -- mutations -----------------------------------------------------------------

def set_flag(pid: str, key: str, value: bool) -> dict:
    meta = load_meta(pid)
    if meta is None:
        raise KeyError(pid)
    meta[key] = bool(value)
    save_meta(meta)
    touch_revision()
    return meta


def remove(pid: str) -> bool:
    d = piece_dir(pid)
    if not d.is_dir():
        return False
    meta = load_meta(pid)
    shutil.rmtree(d)
    idx = hash_index()
    if meta and meta.get("hash") in idx:
        del idx[meta["hash"]]
        _write_json(paths.LIBRARY_INDEX, idx)
    if meta and meta.get("bundled"):
        from . import config as C
        cfg = C.load()
        removed = list(cfg.get("removed_bundled") or [])
        if pid not in removed:
            removed.append(pid)
            cfg["removed_bundled"] = removed
            C.save(cfg)
    touch_revision()
    return True


# -- seeding from the bundled art dir ----------------------------------------------

def seed(progress=None) -> dict:
    """Copy bundled art/<id>/ pieces into the library. Idempotent."""
    from . import config as C
    result: dict[str, list] = {"seeded": [], "skipped": [], "failed": []}
    if not paths.ART_DIR.is_dir():
        return result
    removed = set(C.load().get("removed_bundled") or [])
    idx = hash_index()
    dirs = sorted(d for d in paths.ART_DIR.iterdir() if d.is_dir())
    for i, d in enumerate(dirs):
        pid = d.name
        try:
            bmeta = _read_json(d / "meta.json")
        except (OSError, ValueError):
            result["failed"].append({"id": pid, "reason": "no meta.json"})
            continue
        if progress:
            progress(i + 1, len(dirs), pid)
        if pid in removed or piece_dir(pid).is_dir() or bmeta.get("hash") in idx:
            result["skipped"].append(pid)
            continue
        try:
            data = (d / bmeta["original"]).read_bytes()
            norm = normalize(data, bmeta["original"], encoding=bmeta.get("encoding"), wrap=bmeta.get("wrap", "immediate"))
            keep = {k: bmeta.get(k) for k in ("id", "title", "author", "group", "year", "date", "tags", "category", "source")}
            keep = {k: v for k, v in keep.items() if v is not None}
            norm.meta.update(keep)
            store(norm, data, bundled=True, force=True)
            idx[norm.meta["hash"]] = norm.meta["id"]
            result["seeded"].append(pid)
        except Exception as e:  # noqa: BLE001
            result["failed"].append({"id": pid, "reason": str(e)})
    return result


def summary_rows(pieces: list[dict]) -> list[dict]:
    """Compact rows for snapshot/list --json."""
    out = []
    for m in pieces:
        d = piece_dir(m["id"])
        thumb = d / "thumb.png"
        render = d / "render.png"
        out.append({
            "id": m["id"], "title": m.get("title", ""), "author": m.get("author", ""),
            "group": m.get("group", ""), "year": m.get("year"), "cols": m.get("cols"), "rows": m.get("rows"),
            "format": "ansi" if m.get("format") in ("ansi", "ansimation") else "ascii",
            "animated": bool(m.get("animated")), "encoding": m.get("encoding"),
            "source": (m.get("source") or {}).get("provider"),
            "source_id": (m.get("source") or {}).get("entry"),
            "source_url": (m.get("source") or {}).get("url"),
            "pack": (m.get("source") or {}).get("pack"),
            "image_url": (m.get("source") or {}).get("image_url"),
            "tags": m.get("tags") or [], "category": m.get("category"),
            "enabled": bool(m.get("enabled", True)), "favorite": bool(m.get("favorite")),
            "bundled": bool(m.get("bundled")),
            "thumb": str(thumb) if thumb.is_file() else None,
            "render": str(render) if render.is_file() else None,
            "added": m.get("added"), "warnings": m.get("warnings") or [],
        })
    return out
