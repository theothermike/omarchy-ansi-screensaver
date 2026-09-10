"""CLI glue for sources: list/add/remove, browse, add, preview."""
from __future__ import annotations

import hashlib
import json
import re
import time

from .. import config as C
from .. import library as L, paths
from ..cli import Progress, emit, fail
from . import registry
from .base import Fetched, Offline, HttpError, SourceError


def _source_meta(provider, entry_id: str, f: Fetched) -> dict:
    return {"provider": provider.id, "entry": entry_id, "url": f.source_url, "pack": f.pack,
            "image_url": f.image_url, "license_note": f.license_note or provider.license_note,
            "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _overrides(args, f: Fetched) -> dict:
    o = {"title": getattr(args, "title", None), "author": getattr(args, "author", None),
         "group": getattr(args, "group", None), "year": getattr(args, "year", None)}
    return o


def import_fetched(provider, entry_id: str, f: Fetched, args=None, tags=None) -> tuple[dict, bool]:
    kw = {"encoding": (getattr(args, "encoding", None) if args else None) or f.encoding_hint,
          "force": bool(getattr(args, "force", False)) if args else False}
    norm = L.normalize(f.data, f.filename, encoding=kw["encoding"])
    c = f.credits
    # provider credits fill gaps SAUCE left; explicit CLI overrides win
    if not norm.meta.get("title") or norm.meta["title"] == f.filename.rsplit(".", 1)[0]:
        if c.title:
            norm.meta["title"] = c.title
    if not norm.meta.get("author") and c.author:
        norm.meta["author"] = c.author
    if not norm.meta.get("group") and c.group:
        norm.meta["group"] = c.group
    if not norm.meta.get("year") and c.year:
        norm.meta["year"] = c.year
    if c.tags:
        norm.meta["tags"] = sorted(set((norm.meta.get("tags") or []) + list(c.tags) + list(tags or [])))
    ov = _overrides(args, f) if args else {}
    if f.rating:
        norm.meta["rating"] = dict(f.rating)
    return L.store(norm, f.data, source=_source_meta(provider, entry_id, f), overrides=ov, force=kw["force"])


def cmd_sources(args) -> int:
    cfg = C.load()
    if args.op == "list":
        rows = registry.describe(cfg)
        emit(args, rows, "\n".join(f"{r['id']:16} {r['name']:32} {r['kind']:14} {'thumbs ' if r['has_thumbnails'] else ''}{'search ' if r['has_search'] else ''}{'online' if r['online'] else ('offline' if r['online'] is False else '')}" for r in rows))
        return 0
    if args.op == "add":
        if not args.kind or not args.url:
            return fail(args, "sources add needs --kind and --url", 2)
        url = args.url.strip()
        inst = {"provider": args.kind, "user": True}
        if args.kind == "github_repo":
            m = re.search(r"github\.com/([^/]+)/([^/#?]+)", url)
            repo = f"{m.group(1)}/{m.group(2).removesuffix('.git')}" if m else url.strip("/")
            if "/" not in repo:
                return fail(args, "github_repo needs owner/repo", 2)
            inst["repo"] = repo
            inst["id"] = args.id or "gh-" + re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")
            inst["label"] = args.label or repo
        else:
            if not url.startswith(("http://", "https://")):
                return fail(args, "http_index needs an http(s) URL", 2)
            inst["url"] = url if url.endswith("/") else url + "/"
            host = re.sub(r"^https?://", "", url).split("/")[0]
            inst["id"] = args.id or re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
            inst["label"] = args.label or host
            inst["timeout"] = 8
        sources = [s for s in (cfg.get("sources") or []) if s.get("id") != inst["id"]]
        sources.append(inst)
        cfg["sources"] = sources
        C.save(cfg)
        emit(args, inst, f"added source {inst['id']}")
        return 0
    if args.op == "remove":
        if not args.id:
            return fail(args, "sources remove needs an id", 2)
        before = len(cfg.get("sources") or [])
        cfg["sources"] = [s for s in (cfg.get("sources") or []) if s.get("id") != args.id]
        if len(cfg["sources"]) == before:
            return fail(args, f"no user source {args.id} (built-in sources cannot be removed)")
        C.save(cfg)
        emit(args, {"removed": args.id}, f"removed {args.id}")
        return 0
    return 2


def cmd_browse(args) -> int:
    cfg = C.load()
    if not args.source:
        from .base import Entry, Listing
        entries = [Entry(type="collection", id=p.id, label=p.label, sublabel=p.kind, can_add_all=False) for p in registry.instances(cfg)]
        emit(args, Listing(source="", path=[], breadcrumbs=[], entries=entries).to_dict())
        return 0
    try:
        provider = registry.get(args.source, cfg)
    except KeyError:
        return fail(args, f"unknown source {args.source}")
    try:
        listing = provider.list(list(args.path or []), args.search or None, max(1, int(args.page or 1)))
        if getattr(args, "details", False):
            listing.entries = provider.details(listing.entries)
    except Offline as e:
        listing = provider.offline_listing(list(args.path or []), e)
    except (HttpError, SourceError) as e:
        return fail(args, str(e))
    emit(args, listing.to_dict())
    return 0


def cmd_add(args) -> int:
    cfg = C.load()
    try:
        provider = registry.get(args.source, cfg)
    except KeyError:
        return fail(args, f"unknown source {args.source}")
    prog = Progress(args.progress)
    result: dict = {"added": [], "skipped": [], "failed": []}

    def one(entry_id: str, label: str = "") -> None:
        try:
            f = provider.fetch(entry_id)
            meta, created = import_fetched(provider, entry_id, f, args)
            (result["added"] if created else result["skipped"]).append({"entry": entry_id, "id": meta["id"], "title": meta.get("title"), **({} if created else {"reason": "duplicate"})})
        except Offline as e:
            result["failed"].append({"entry": entry_id, "reason": f"offline: {e}"})
        except Exception as e:  # noqa: BLE001
            result["failed"].append({"entry": entry_id, "reason": str(e)})

    if args.all:
        try:
            items = list(provider.iter_items(args.entry))
        except Offline as e:
            return fail(args, f"offline: {e}", 3)
        for i, it in enumerate(items):
            prog(i + 1, len(items), it.label)
            one(it.id, it.label)
    else:
        prog(1, 1, args.entry)
        one(args.entry)
    if args.progress:
        prog.done(result)
    else:
        human = "\n".join([f"added   {r['id']}  {r.get('title') or ''}" for r in result["added"]]
                          + [f"skipped {r['id']}  (duplicate)" for r in result["skipped"]]
                          + [f"FAILED  {r['entry']}: {r['reason']}" for r in result["failed"]]) or "nothing added"
        emit(args, result, human)
    return 0 if (result["added"] or result["skipped"] or not result["failed"]) else 1


def cmd_preview_source(args) -> int:
    cfg = C.load()
    try:
        provider = registry.get(args.source, cfg)
    except KeyError:
        return fail(args, f"unknown source {args.source}")
    if not args.entry:
        return fail(args, "preview --source needs --entry", 2)
    key = hashlib.sha1(f"{provider.id}|{args.entry}".encode()).hexdigest()[:16]
    out_dir = paths.PREVIEWS_CACHE
    png, render_p = out_dir / f"{key}.thumb.png", out_dir / f"{key}.png"
    meta_p = out_dir / f"{key}.json"
    if png.exists() and meta_p.exists():
        emit(args, json.loads(meta_p.read_text()))
        return 0
    try:
        f = provider.preview(args.entry)
        norm = L.normalize(f.data, f.filename, encoding=f.encoding_hint)
    except Offline as e:
        return fail(args, f"offline: {e}", 3)
    except Exception as e:  # noqa: BLE001
        return fail(args, str(e))
    res = {"cols": norm.grid.painted_cols, "rows": norm.grid.height,
           "credits": {"title": f.credits.title or norm.meta.get("title"), "author": f.credits.author or norm.meta.get("author"),
                       "group": f.credits.group or norm.meta.get("group"), "year": f.credits.year or norm.meta.get("year")},
           "png": None, "render": None}
    try:
        from ..render import render_grid_to
        r = render_grid_to(norm.grid, out_dir, key)
        res["png"], res["render"] = r["png"], r["render"]
    except ImportError:
        res["notice"] = "Pillow missing: no preview image"
    meta_p.write_text(json.dumps(res))
    emit(args, res)
    return 0


def _pick_sources(args, cfg):
    if getattr(args, "all", False) or not getattr(args, "source", None):
        srcs = registry.instances(cfg)
    else:
        srcs = [registry.get(args.source, cfg)]
    if getattr(args, "top", False):
        srcs = [s for s in srcs if s.caps.has_ratings]
        if not srcs:
            raise SourceError("no selected source has ratings (only asciiart.eu does)")
    return srcs


def _history_path():
    return paths.SOURCES_CACHE / "random-history.json"


def _load_history() -> set[str]:
    try:
        return set(json.loads(_history_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _save_history(h: set[str]) -> None:
    try:
        _history_path().parent.mkdir(parents=True, exist_ok=True)
        _history_path().write_text(json.dumps(sorted(h)[-20000:]), encoding="utf-8")
    except OSError:
        pass


def cmd_random(args) -> int:
    """Import N random pieces from one source or all of them (round-robin);
    --top restricts to highly rated items where a source has ratings."""
    import random
    cfg = C.load()
    try:
        srcs = _pick_sources(args, cfg)
    except (KeyError, SourceError) as e:
        return fail(args, str(e))
    n = max(1, int(args.count or 1))
    rng = random.Random(args.seed) if getattr(args, "seed", None) else random.Random()
    prog = Progress(args.progress)
    history = _load_history()
    result: dict = {"added": [], "skipped": [], "failed": [], "sources": [s.id for s in srcs]}
    order = list(srcs)
    rng.shuffle(order)
    i = 0
    done = 0
    stalled: dict[str, int] = {}
    while done < n and order:
        src = order[i % len(order)]
        i += 1
        if stalled.get(src.id, 0) >= 4:
            order = [s for s in order if s.id != src.id]
            continue
        prog(done + 1, n, f"picking from {src.label}")
        try:
            items = src.random_items(1, rng, top=bool(getattr(args, "top", False)))
        except Offline as e:
            result["failed"].append({"source": src.id, "reason": f"offline: {e}"})
            stalled[src.id] = 99
            continue
        except SourceError as e:
            result["failed"].append({"source": src.id, "reason": str(e)})
            stalled[src.id] = 99
            continue
        except Exception as e:  # noqa: BLE001
            result["failed"].append({"source": src.id, "reason": str(e)})
            stalled[src.id] = stalled.get(src.id, 0) + 1
            continue
        if not items:
            stalled[src.id] = stalled.get(src.id, 0) + 1
            continue
        item = items[0]
        key = f"{src.id}:{item.id}"
        if key in history:
            stalled[src.id] = stalled.get(src.id, 0) + 1
            continue
        try:
            f = src.fetch(item.id)
            meta, created = import_fetched(src, item.id, f, None, tags=["random"] + (["top-rated"] if getattr(args, "top", False) else []))
        except Exception as e:  # noqa: BLE001
            result["failed"].append({"source": src.id, "entry": item.id, "reason": str(e)})
            stalled[src.id] = stalled.get(src.id, 0) + 1
            continue
        history.add(key)
        if created:
            done += 1
            stalled[src.id] = 0
            result["added"].append({"source": src.id, "id": meta["id"], "title": meta.get("title"), "entry": item.id})
            prog(done, n, f"{src.label}: {meta.get('title') or item.label}")
        else:
            result["skipped"].append({"source": src.id, "id": meta["id"], "reason": "duplicate"})
            stalled[src.id] = stalled.get(src.id, 0) + 1
    _save_history(history)
    if args.progress:
        prog.done(result)
    else:
        human = "\n".join([f"added   {r['id']:44} {r['source']:14} {r.get('title') or ''}" for r in result["added"]]
                          + [f"skipped {r['id']} (duplicate)" for r in result["skipped"]]
                          + [f"FAILED  {r['source']}: {r['reason']}" for r in result["failed"]]) or "nothing added"
        emit(args, result, human)
    return 0 if result["added"] else 1


def cmd_index(args) -> int:
    cfg = C.load()
    try:
        provider = registry.get(args.source, cfg)
    except KeyError:
        return fail(args, f"unknown source {args.source}")
    if args.op == "status":
        emit(args, provider.index_status())
        return 0
    prog = Progress(args.progress)
    try:
        res = provider.index_build(progress=prog, limit=getattr(args, "limit", None))
    except Offline as e:
        return fail(args, f"offline: {e}", 3)
    except SourceError as e:
        return fail(args, str(e))
    from ..config import touch_revision
    touch_revision()
    if args.progress:
        prog.done(res)
    else:
        emit(args, res, f"indexed {res.get('items')} items from {res.get('pages')} pages -> {res.get('path')}")
    return 0
