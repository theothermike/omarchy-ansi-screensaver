"""catalog.json: the bundled set. fetch / curate / bundle / attribution."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import library as L, paths
from .cli import Progress, emit, fail
from .sources import registry
from .sources.base import Offline
from .sources.cli import import_fetched


def load_catalog(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_fetch(args) -> int:
    """Fetch every catalog entry into the library (or --into a bundle dir)."""
    try:
        cat = load_catalog(Path(args.catalog))
    except (OSError, ValueError) as e:
        return fail(args, f"catalog: {e}")
    entries = cat.get("entries") or []
    if args.only:
        entries = [e for e in entries if e.get("id") in args.only or e.get("entry") in args.only]
    into = Path(args.into).expanduser() if args.into else None
    prog = Progress(args.progress)
    result: dict = {"added": [], "skipped": [], "failed": []}
    providers: dict = {}
    for i, e in enumerate(entries):
        prog(i + 1, len(entries), e.get("id") or e.get("entry"))
        try:
            src = e["source"]
            if src not in providers:
                providers[src] = registry.get(src)
            f = providers[src].fetch(e["entry"])
            credits = e.get("credits") or {}
            if into is not None:
                norm = L.normalize(f.data, f.filename, encoding=f.encoding_hint)
                for k in ("title", "author", "group", "year"):
                    if credits.get(k):
                        norm.meta[k] = credits[k]
                    elif not norm.meta.get(k) and getattr(f.credits, k, None):
                        norm.meta[k] = getattr(f.credits, k)
                if e.get("id"):
                    norm.meta["id"] = e["id"]
                norm.meta["tags"] = sorted(set((norm.meta.get("tags") or []) + list(f.credits.tags) + list(e.get("tags") or [])))
                norm.meta["category"] = e.get("category")
                from .sources.cli import _source_meta
                meta, created = L.store(norm, f.data, source=_source_meta(providers[src], e["entry"], f), bundled=True, into=into, force=True)
            else:
                from types import SimpleNamespace
                ns = SimpleNamespace(title=credits.get("title"), author=credits.get("author"), group=credits.get("group"),
                                     year=credits.get("year"), encoding=None, force=False)
                meta, created = import_fetched(providers[src], e["entry"], f, ns, tags=e.get("tags"))
                if e.get("category") and meta.get("category") != e.get("category"):
                    meta["category"] = e["category"]
                    L.save_meta(meta)
            (result["added"] if created else result["skipped"]).append({"id": meta["id"], "entry": e["entry"]})
        except Offline as ex:
            result["failed"].append({"entry": e.get("entry"), "reason": f"offline: {ex}"})
        except Exception as ex:  # noqa: BLE001
            result["failed"].append({"entry": e.get("entry"), "reason": str(ex)})
    if args.progress:
        prog.done(result)
    else:
        emit(args, result, f"added {len(result['added'])}, skipped {len(result['skipped'])}, failed {len(result['failed'])}"
             + ("".join(f"\n  FAILED {r['entry']}: {r['reason']}" for r in result["failed"])))
    return 0 if not result["failed"] or result["added"] else 1


def cmd_curate(args) -> int:
    """List candidate files from packs for building the bundled set."""
    provider = registry.get(args.source)
    rows = []
    for pack in args.packs:
        try:
            items = list(provider.iter_items(f"pack/{pack}"))
        except Exception as e:  # noqa: BLE001
            rows.append({"pack": pack, "error": str(e)})
            continue
        for it in items:
            m = it.meta or {}
            cols, r = m.get("cols") or 0, m.get("rows") or 0
            if cols != args.cols or not (args.min_rows <= r <= args.max_rows):
                continue
            rows.append({"pack": pack, "entry": it.id, "file": m.get("file"), "title": it.label, "author": m.get("author"),
                         "group": m.get("group"), "year": m.get("year"), "cols": cols, "rows": r, "format": m.get("format"),
                         "ice": m.get("ice"), "tags": m.get("tags") or [], "thumb": it.thumb_url, "image": it.image_url})
    rows.sort(key=lambda x: (x.get("pack", ""), x.get("rows", 0)))
    if args.emit_catalog:
        emit(args, {"version": 1, "entries": [{"id": None, "source": args.source, "entry": r["entry"], "pack": r["pack"], "file": r["file"],
                                                 "year": r["year"], "credits": {"title": r["title"], "author": r["author"], "group": r["group"]},
                                                 "category": None, "tags": r["tags"]} for r in rows if "entry" in r]})
        return 0
    human = "\n".join(f"{r['pack']:32} {str(r.get('rows')):>4} {r.get('format', ''):5} {str(r.get('title'))[:28]:28} {str(r.get('author'))[:18]:18} {r['entry'] if 'entry' in r else r['error']}" for r in rows)
    emit(args, rows, human or "no candidates")
    return 0


def cmd_bundle(args) -> int:
    from types import SimpleNamespace
    ns = SimpleNamespace(catalog=str(paths.CATALOG), only=[], into=str(paths.ART_DIR), progress=args.progress, json=args.json)
    rc = cmd_fetch(ns)
    write_attribution()
    return rc


def write_attribution() -> Path:
    metas = []
    if paths.ART_DIR.is_dir():
        for d in sorted(paths.ART_DIR.iterdir()):
            try:
                metas.append(json.loads((d / "meta.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    lines = ["# Attribution", "",
             "The bundled pieces are the work of the artists credited below. They are distributed as they have always been",
             "in the ANSI/ASCII art scene — freely, with credits intact — and remain the intellectual property of their authors.",
             "SAUCE metadata is preserved in every `original.*` file. If you are an artist and want a piece removed, open an issue.",
             "", f"Generated {time.strftime('%Y-%m-%d')} from `art/*/meta.json` by `ansi-screensaver attribution`.", ""]
    by_cat: dict[str, list] = {}
    for m in metas:
        by_cat.setdefault(m.get("category") or "uncategorised", []).append(m)
    for cat in sorted(by_cat):
        lines += [f"## {cat}", "", "| Title | Artist | Group | Year | Pack | Source | Licence note |", "|---|---|---|---|---|---|---|"]
        for m in sorted(by_cat[cat], key=lambda x: (x.get("group") or "", x.get("title") or "")):
            s = m.get("source") or {}
            lines.append(f"| {m.get('title') or m['id']} | {m.get('author') or ''} | {m.get('group') or ''} | {m.get('year') or ''} | "
                         f"{s.get('pack') or ''} | {('[' + s.get('provider', '') + '](' + s['url'] + ')') if s.get('url') else s.get('provider', '')} | {s.get('license_note') or ''} |")
        lines.append("")
    lines += ["## Fonts", "", "`fonts/Px437_IBM_VGA_8x16.ttf` — The Ultimate Oldschool PC Font Pack v2.2 by VileR, CC BY-SA 4.0 (https://int10h.org/oldschool-pc-fonts/).", ""]
    out = paths.PLUGIN_DIR / "ATTRIBUTION.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def cmd_attribution(args) -> int:
    out = write_attribution()
    emit(args, {"written": str(out)}, f"wrote {out}")
    return 0
