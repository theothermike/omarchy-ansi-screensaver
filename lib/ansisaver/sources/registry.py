"""Instantiate providers: built-in singletons plus user instances from config."""
from __future__ import annotations

import importlib

from .. import config as C

BUILTIN = [
    ("sixteencolors", "sixteencolors", "SixteenColors"),
    ("demozoo", "demozoo", "Demozoo"),
    ("archive_org", "archive_org", "ArchiveOrg"),
    ("asciiart_eu", "asciiart_eu", "AsciiArtEu"),
    ("ascii_co_uk", "ascii_co_uk", "AsciiCoUk"),
]
INSTANCE_KINDS = {"github_repo": ("github_repo", "GitHubRepo"), "http_index": ("http_index", "HttpIndex")}


def _load(module: str, cls: str):
    try:
        mod = importlib.import_module(f"ansisaver.sources.{module}")
        return getattr(mod, cls)
    except (ImportError, AttributeError):
        return None


def instances(cfg: dict | None = None) -> list:
    cfg = cfg or C.load()
    out = []
    for pid, module, cls in BUILTIN:
        klass = _load(module, cls)
        if klass is not None:
            out.append(klass({"id": pid, "token": cfg.get("github_token") if pid == "github" else None}))
    for inst in cfg.get("sources") or []:
        kind = inst.get("provider")
        if kind not in INSTANCE_KINDS:
            continue
        module, cls = INSTANCE_KINDS[kind]
        klass = _load(module, cls)
        if klass is None:
            continue
        data = dict(inst)
        if kind == "github_repo":
            data["token"] = cfg.get("github_token")
        out.append(klass(data))
    return out


def get(source_id: str, cfg: dict | None = None):
    for p in instances(cfg):
        if p.id == source_id:
            return p
    raise KeyError(source_id)


def describe(cfg: dict | None = None) -> list[dict]:
    return [p.describe() for p in instances(cfg)]
