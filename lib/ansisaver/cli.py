"""Command line interface: `ansi-screensaver <subcommand> ...`."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import __version__, paths
from . import config as C

log = logging.getLogger("ansisaver")


class Progress:
    """Line protocol for long jobs: progress n/total label | done {json} | error msg."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, n: int, total: int, label: str = "") -> None:
        if self.enabled:
            sys.stdout.write(f"progress {n}/{total} {label}\n")
            sys.stdout.flush()

    def done(self, payload) -> None:
        if self.enabled:
            sys.stdout.write("done " + json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def error(self, msg: str) -> None:
        if self.enabled:
            sys.stdout.write(f"error {msg}\n")
            sys.stdout.flush()


def emit(args, payload, human=None) -> None:
    if getattr(args, "progress", False):
        Progress(True).done(payload)
    elif getattr(args, "json", False) or human is None:
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(human if human.endswith("\n") else human + "\n")


def fail(args, msg: str, code: int = 1) -> int:
    if getattr(args, "progress", False):
        Progress(True).error(msg)
    elif getattr(args, "json", False):
        json.dump({"error": msg}, sys.stdout)
        sys.stdout.write("\n")
    else:
        sys.stderr.write(f"ansi-screensaver: {msg}\n")
    return code


# ---------------------------------------------------------------- subcommands

def cmd_config(args) -> int:
    cfg = C.load()
    if args.op == "dump":
        emit(args, cfg)
        return 0
    if args.op == "get":
        v = C.get(cfg, args.key)
        emit(args, v, json.dumps(v))
        return 0
    if args.op == "set":
        value = C.parse_value(args.value)
        try:
            C.set_value(cfg, args.key, value)
        except C.ConfigError as e:
            return fail(args, str(e), 2)
        C.save(cfg)
        emit(args, {"ok": True, "key": args.key, "value": value}, f"{args.key} = {json.dumps(value)}")
        return 0
    return 2


def _import_path(path: Path, prog: Progress, kw: dict, results: dict, counter: list) -> None:
    from . import library as L
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file())
        for p in files:
            _import_path(p, prog, kw, results, counter)
        return
    if path.suffix.lower() == ".zip":
        import zipfile
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n]
            for n in names:
                if Path(n).suffix.lower() in L.REJECT_EXTS:
                    continue
                counter[0] += 1
                prog(counter[0], max(counter[1], counter[0]), n)
                try:
                    meta, created = L.import_bytes(z.read(n), n, source={"provider": "local", "url": str(path), "pack": path.stem}, **kw)
                    results["added" if created else "skipped"].append({"id": meta["id"], "file": n} if created else {"id": meta["id"], "file": n, "reason": "duplicate"})
                except Exception as e:  # noqa: BLE001
                    results["failed"].append({"file": n, "reason": str(e)})
        return
    if path.suffix.lower() in L.REJECT_EXTS:
        results["failed"].append({"file": str(path), "reason": f"{path.suffix} not supported"})
        return
    counter[0] += 1
    prog(counter[0], max(counter[1], counter[0]), path.name)
    try:
        meta, created = L.import_bytes(path.read_bytes(), path.name, source={"provider": "local", "url": str(path)}, **kw)
        if created:
            results["added"].append({"id": meta["id"], "file": str(path)})
        else:
            results["skipped"].append({"id": meta["id"], "file": str(path), "reason": "duplicate"})
    except Exception as e:  # noqa: BLE001
        results["failed"].append({"file": str(path), "reason": str(e)})


def cmd_import(args) -> int:
    from . import library as L
    paths.ensure_dirs()
    prog = Progress(args.progress)
    kw = {"encoding": args.encoding, "wrap": args.wrap, "bce": not args.no_bce, "force": args.force,
          "overrides": {"title": args.title, "author": args.author, "group": args.group, "year": args.year}}
    results: dict = {"added": [], "skipped": [], "failed": []}
    counter = [0, 0]
    for target in args.targets:
        if target.startswith(("http://", "https://")):
            try:
                from .importer import import_url
                meta, created = import_url(target, **kw)
                (results["added"] if created else results["skipped"]).append({"id": meta["id"], "file": target})
            except Exception as e:  # noqa: BLE001
                results["failed"].append({"file": target, "reason": str(e)})
            continue
        p = Path(target).expanduser()
        if not p.exists():
            results["failed"].append({"file": target, "reason": "not found"})
            continue
        if p.is_dir():
            counter[1] += sum(1 for q in p.rglob("*") if q.is_file())
        _import_path(p, prog, kw, results, counter)
    if args.progress:
        prog.done(results)
    else:
        human = "\n".join([f"added   {r['id']}  ({r['file']})" for r in results["added"]]
                          + [f"skipped {r['id']}  ({r.get('reason')})" for r in results["skipped"]]
                          + [f"FAILED  {r['file']}: {r['reason']}" for r in results["failed"]]) or "nothing imported"
        emit(args, results, human)
    return 0 if (results["added"] or results["skipped"]) or not results["failed"] else 1


def cmd_library(args) -> int:
    from . import library as L
    if args.op == "list":
        rows = L.summary_rows(L.list_pieces())
        human = "\n".join(f"{'*' if r['favorite'] else ' '}{'x' if r['enabled'] else ' '} {r['id']:44} {r['cols']:>3}x{r['rows']:<4} {r['format']:5} {r['title'][:30]!s:30} {r['author']}" for r in rows)
        emit(args, rows, human or "(library is empty)")
        return 0
    if args.op == "show":
        m = L.load_meta(args.id)
        if not m:
            return fail(args, f"unknown piece {args.id}")
        emit(args, m)
        return 0
    if args.op in ("enable", "disable", "favorite", "unfavorite"):
        key = "enabled" if args.op in ("enable", "disable") else "favorite"
        val = args.op in ("enable", "favorite")
        try:
            m = L.set_flag(args.id, key, val)
        except KeyError:
            return fail(args, f"unknown piece {args.id}")
        emit(args, {"ok": True, "id": m["id"], key: val}, f"{m['id']}: {key} = {val}")
        return 0
    if args.op == "remove":
        ok = L.remove(args.id)
        if not ok:
            return fail(args, f"unknown piece {args.id}")
        emit(args, {"ok": True, "removed": args.id}, f"removed {args.id}")
        return 0
    return 2


def cmd_seed(args) -> int:
    from . import library as L
    paths.ensure_dirs()
    prog = Progress(args.progress)
    result = L.seed(progress=prog)
    if args.progress:
        prog.done(result)
    else:
        emit(args, result, f"seeded {len(result['seeded'])}, skipped {len(result['skipped'])}, failed {len(result['failed'])}")
    return 0


def cmd_snapshot(args) -> int:
    from .snapshot import build
    emit(args, build(network=args.network))
    return 0


def cmd_doctor(args) -> int:
    from .doctor import run_checks
    checks = run_checks(network=args.network)
    human = "\n".join(f"[{'ok' if c['ok'] else '!!'}] {c['name']}: {c['detail']}" + (f"  -> {c['fix']}" if not c["ok"] and c.get("fix") else "") for c in checks)
    emit(args, checks, human)
    return 0 if all(c["ok"] for c in checks if c.get("critical", True)) else 1


def cmd_launch(args) -> int:
    from .launch import launch
    return launch(args)


def cmd_run(args) -> int:
    from .runner import run
    return run(args)


def cmd_stop(args) -> int:
    from .launch import stop
    return stop(args)


def cmd_preview(args) -> int:
    from .launch import preview
    return preview(args)


def cmd_install(args) -> int:
    from .install import install
    return install(args)


def cmd_idle(args) -> int:
    from .idle import cmd_idle as run
    return run(args)


def cmd_fonts(args) -> int:
    from .fonts import cmd
    return cmd(args)


def cmd_thumb(args) -> int:
    from .render import cmd_thumb
    return cmd_thumb(args)


def cmd_sources(args) -> int:
    from .sources import cli as scli
    return scli.cmd_sources(args)


def cmd_browse(args) -> int:
    from .sources import cli as scli
    return scli.cmd_browse(args)


def cmd_add(args) -> int:
    from .sources import cli as scli
    return scli.cmd_add(args)


def cmd_random(args) -> int:
    from .sources import cli as scli
    return scli.cmd_random(args)


def cmd_index(args) -> int:
    from .sources import cli as scli
    return scli.cmd_index(args)


def cmd_fetch(args) -> int:
    from .catalog import cmd_fetch
    return cmd_fetch(args)


def cmd_curate(args) -> int:
    from .catalog import cmd_curate
    return cmd_curate(args)


def cmd_bundle(args) -> int:
    from .catalog import cmd_bundle
    return cmd_bundle(args)


def cmd_attribution(args) -> int:
    from .catalog import cmd_attribution
    return cmd_attribution(args)


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ansi-screensaver", description="ANSI/ASCII art screensaver for Omarchy")
    ap.add_argument("--version", action="version", version=f"ansi-screensaver {__version__}")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--progress", action="store_true", help="stream progress/done/error lines (long jobs)")
    ap.add_argument("--log-level", default=os.environ.get("ANSISAVER_LOG", "INFO"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("launch", help="start the screensaver (one fullscreen terminal per monitor)")
    p.add_argument("--force", action="store_true", help="ignore the screensaver-off toggle and lock state")
    p.add_argument("--piece", help="show only this piece id")
    p.add_argument("--effect", help="force a ttfx effect name or 'baud'")
    p.add_argument("--once", action="store_true", help="one slide then exit")
    p.add_argument("--monitor", help="only this monitor")
    p.add_argument("--window-class", default=paths.SCREENSAVER_CLASS)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("run", help="(internal) slideshow loop inside the terminal")
    p.add_argument("--monitor", default="")
    p.add_argument("--session", default="")
    p.add_argument("--piece")
    p.add_argument("--effect")
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-hypr", action="store_true")
    p.add_argument("--fast", action="store_true")
    p.add_argument("--window-class", default=paths.SCREENSAVER_CLASS)
    p.add_argument("--font-pt", type=float, default=0.0)
    p.add_argument("--font-kind", default="")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("stop", help="stop running screensaver windows")
    p.add_argument("--previews", action="store_true", help="also stop preview windows")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("preview", help="show one piece fullscreen on the focused monitor")
    p.add_argument("id", nargs="?")
    p.add_argument("--random", action="store_true")
    p.add_argument("--effect")
    p.add_argument("--source", help="preview an entry from a source instead (renders a PNG)")
    p.add_argument("--entry")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("snapshot", help="everything the UI needs in one JSON document")
    p.add_argument("--network", action="store_true")
    p.set_defaults(func=cmd_snapshot, json=True)

    p = sub.add_parser("seed", help="import the bundled art into the library")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("install", help="symlink the CLI into ~/.local/bin (and optionally fonts/seed)")
    p.add_argument("--fonts", action="store_true")
    p.add_argument("--seed", action="store_true")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("idle", help="Omarchy's idle timeouts (shell.json idle.screensaver / idle.lock)")
    p.add_argument("op", choices=["get", "set"])
    p.add_argument("--screensaver", type=int, help="seconds of idle before the screensaver")
    p.add_argument("--lock", type=int, help="seconds of idle before the lock screen")
    p.set_defaults(func=cmd_idle)

    p = sub.add_parser("fonts", help="VGA font install/status")
    p.add_argument("op", choices=["install", "status"])
    p.set_defaults(func=cmd_fonts)

    p = sub.add_parser("library", help="manage pieces")
    p.add_argument("op", choices=["list", "show", "enable", "disable", "favorite", "unfavorite", "remove"])
    p.add_argument("id", nargs="?")
    p.set_defaults(func=cmd_library)

    p = sub.add_parser("import", help="import files, directories, zips or URLs")
    p.add_argument("targets", nargs="+")
    p.add_argument("--title"); p.add_argument("--author"); p.add_argument("--group")
    p.add_argument("--year", type=int)
    p.add_argument("--encoding", choices=["cp437", "latin1", "utf8"])
    p.add_argument("--wrap", choices=["immediate", "pending"], default="immediate")
    p.add_argument("--no-bce", action="store_true", help="ignore erase-line/screen background fills")
    p.add_argument("--force", action="store_true", help="re-import even if the same bytes exist")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("sources", help="list/add/remove art sources")
    p.add_argument("op", choices=["list", "add", "remove"])
    p.add_argument("id", nargs="?")
    p.add_argument("--kind", choices=["github_repo", "http_index"])
    p.add_argument("--url"); p.add_argument("--label")
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("browse", help="browse an art source")
    p.add_argument("--source")
    p.add_argument("--path", action="append", default=[])
    p.add_argument("--search")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--details", action="store_true", help="fetch per-item details (thumbnails) where lazy")
    p.set_defaults(func=cmd_browse)

    p = sub.add_parser("add", help="add an entry (or a whole collection) from a source")
    p.add_argument("--source", required=True)
    p.add_argument("--entry", required=True)
    p.add_argument("--all", action="store_true")
    p.add_argument("--title"); p.add_argument("--author"); p.add_argument("--group")
    p.add_argument("--year", type=int)
    p.add_argument("--encoding", choices=["cp437", "latin1", "utf8"])
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("random", help="import random pieces from a source (or all sources)")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--source")
    p.add_argument("--all", action="store_true", help="draw from every source")
    p.add_argument("--top", action="store_true", help="prefer highly rated pieces (sources with ratings only)")
    p.add_argument("--seed", type=int)
    p.set_defaults(func=cmd_random)

    p = sub.add_parser("index", help="build/inspect a source's rating index (used by random --top)")
    p.add_argument("op", choices=["build", "status"])
    p.add_argument("--source", required=True)
    p.add_argument("--limit", type=int, help="only crawl this many pages (testing)")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("fetch", help="fetch catalog entries into the library (or --into a bundle dir)")
    p.add_argument("--catalog", default=str(paths.CATALOG))
    p.add_argument("--only", action="append", default=[])
    p.add_argument("--into")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("curate", help="list candidate files from packs (for building the bundled set)")
    p.add_argument("--source", default="sixteencolors")
    p.add_argument("--packs", nargs="+", required=True)
    p.add_argument("--cols", type=int, default=80)
    p.add_argument("--min-rows", type=int, default=20)
    p.add_argument("--max-rows", type=int, default=150)
    p.add_argument("--emit-catalog", action="store_true")
    p.set_defaults(func=cmd_curate)

    p = sub.add_parser("bundle", help="(dev) fetch catalog.json into art/ and write ATTRIBUTION.md")
    p.set_defaults(func=cmd_bundle)
    p = sub.add_parser("attribution", help="(dev) regenerate ATTRIBUTION.md from art/")
    p.set_defaults(func=cmd_attribution)

    p = sub.add_parser("thumb", help="render thumbnails")
    p.add_argument("id", nargs="?")
    p.add_argument("--all", action="store_true")
    p.add_argument("--missing", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_thumb)
    p = sub.add_parser("thumbs", help="render thumbnails for all pieces")
    p.add_argument("--all", action="store_true", default=True)
    p.add_argument("--missing", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_thumb, id=None)

    p = sub.add_parser("config", help="get/set/dump configuration")
    p.add_argument("op", choices=["get", "set", "dump"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("doctor", help="check the environment")
    p.add_argument("--network", action="store_true")
    p.set_defaults(func=cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    # --json / --progress are accepted anywhere on the line (the UI appends them)
    flags = {"--json": False, "--progress": False}
    rest = []
    for a in raw:
        if a in flags:
            flags[a] = True
        else:
            rest.append(a)
    args = ap.parse_args(rest)
    if flags["--json"]:
        args.json = True
    if flags["--progress"]:
        args.progress = True
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO),
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    if args.cmd == "config" and args.op in ("get", "set") and not args.key:
        ap.error("config get/set needs a key")
    if args.cmd == "config" and args.op == "set" and args.value is None:
        ap.error("config set needs a value")
    if args.cmd == "library" and args.op != "list" and not args.id:
        ap.error(f"library {args.op} needs a piece id")
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except C.ConfigError as e:
        return fail(args, str(e), 2)
