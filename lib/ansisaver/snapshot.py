"""One JSON document with everything the UI needs."""
from __future__ import annotations

from . import __version__
from . import config as C
from . import effects, library as L, transitions
from .doctor import run_checks


def build(network: bool = False) -> dict:
    cfg = C.load()
    pieces = L.list_pieces()
    try:
        from .sources import registry
        sources = registry.describe(cfg)
    except Exception as e:  # noqa: BLE001
        sources = [{"id": "error", "name": str(e), "kind": "error", "has_thumbnails": False,
                    "has_search": False, "can_add_collection": False, "online": False}]
    return {
        "version": __version__,
        "config": cfg,
        "library": L.summary_rows(pieces),
        "doctor": run_checks(network=network),
        "sources": sources,
        "effects": {
            "ttfx": effects.ALL_EFFECTS,
            "recommended": sorted(k for k, v in C.DEFAULT_EFFECTS.items() if v > 0),
            "transitions": transitions.ALL,
            "defaults": {"ttfx": C.DEFAULT_EFFECTS, "transitions": C.DEFAULT_TRANSITIONS},
        },
    }
