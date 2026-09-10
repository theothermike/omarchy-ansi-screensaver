"""Provider contract shared by every art source."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Iterator

from .. import paths
from .http import HttpClient, HttpError, Offline

ART_EXTS = (".ans", ".asc", ".txt", ".nfo", ".diz", ".ansi")


@dataclass
class Capabilities:
    has_thumbnails: bool = False
    has_search: bool = False
    can_add_collection: bool = False
    needs_network: bool = True
    has_ratings: bool = False      # items carry meta.score (likes/views…)
    has_index: bool = False        # supports `index build` for top-rated sampling


@dataclass
class Entry:
    type: str                      # "collection" | "item"
    id: str
    label: str
    sublabel: str = ""
    meta: dict = field(default_factory=dict)
    thumb_url: str | None = None
    image_url: str | None = None
    text_preview: str | None = None
    can_add_all: bool = False
    source_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Listing:
    source: str
    path: list[str]
    breadcrumbs: list[str]
    entries: list[Entry]
    next_page: int | None = None
    notice: str | None = None
    total_pages: int | None = None

    def to_dict(self) -> dict:
        return {"source": self.source, "path": self.path, "breadcrumbs": self.breadcrumbs,
                "entries": [e.to_dict() for e in self.entries], "next_page": self.next_page, "notice": self.notice,
                "total_pages": self.total_pages}


@dataclass
class Credits:
    title: str = ""
    author: str = ""
    group: str = ""
    year: int | None = None
    date: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class Fetched:
    data: bytes
    filename: str
    credits: Credits
    source_url: str
    license_note: str
    image_url: str | None = None
    encoding_hint: str | None = None
    pack: str | None = None
    rating: dict | None = None     # {"likes", "views", "score"} when the source has ratings


class SourceError(Exception):
    pass


# .ans/.asc plus the pack-specific extensions 1990s groups used for their ANSIs
SCENE_EXTS = {"ans", "asc", "txt", "nfo", "diz", "ansi", "ice", "acd", "cia", "dds", "mir", "rem", "fir", "fire", "blk",
              "bld", "lit", "msg", "art", "lgc", "tpa", "tri", "imp", "fuel", "ess", "law", "dez", "bad", "goa", "kts",
              "zaz", "gdt", "dsx", "clr", "fzl", "sac", "spd", "mim", "avg", "mo", "odl", "pgn", "gro", "hrt", "sfc",
              "sbn", "nwa", "dark", "trbl", "jed", "ext", "sdl", "ptk", "fst", "fli"}


def is_art_name(name: str) -> bool:
    if "." not in name:
        return False
    return name.lower().rsplit(".", 1)[-1] in SCENE_EXTS


class Provider:
    kind = "base"
    label = "Source"
    caps = Capabilities()
    license_note = ""

    def __init__(self, instance: dict, http: HttpClient | None = None):
        self.instance = instance
        self.id = instance.get("id") or self.kind
        self.label = instance.get("label") or self.label
        self.http = http or HttpClient(self.id, token=instance.get("token"))

    # -- to implement ------------------------------------------------------
    def list(self, path: list[str], search: str | None, page: int) -> Listing:
        raise NotImplementedError

    def fetch(self, entry_id: str) -> Fetched:
        raise NotImplementedError

    def iter_items(self, entry_id: str) -> Iterator[Entry]:
        """Expand a collection into art items (for `add --all`)."""
        listing = self.list([entry_id], None, 1)
        page = 1
        while True:
            for e in listing.entries:
                if e.type == "item":
                    yield e
            if not listing.next_page:
                break
            page = listing.next_page
            listing = self.list([entry_id], None, page)

    def preview(self, entry_id: str) -> Fetched:
        return self.fetch(entry_id)

    def details(self, entries: list[Entry]) -> list[Entry]:
        """Optionally fill lazy fields (thumbnails) for a page of entries."""
        return entries

    def ping(self) -> tuple[bool, str]:
        return True, "no check"

    # -- random sampling ----------------------------------------------------
    def random_items(self, n: int, rng, top: bool = False) -> list[Entry]:
        """Pick up to n random art items from the whole catalogue by walking
        the tree at random (providers with a cheaper way override this).
        `top` asks for highly rated items (only meaningful with has_ratings)."""
        picked: list[Entry] = []
        seen: set[str] = set()
        attempts = 0
        while len(picked) < n and attempts < n * 6 + 6:
            attempts += 1
            e = self._random_walk(rng)
            if e is not None and e.id not in seen:
                seen.add(e.id)
                picked.append(e)
        return picked

    def _random_walk(self, rng, max_depth: int = 6) -> Entry | None:
        path: list[str] = []
        for _ in range(max_depth):
            try:
                listing = self.list(path, None, 1)
            except Exception:  # noqa: BLE001
                return None
            if listing.total_pages and listing.total_pages > 1:
                page = rng.randint(1, listing.total_pages)
                if page > 1:
                    try:
                        listing = self.list(path, None, page)
                    except Exception:  # noqa: BLE001
                        pass
            items = [e for e in listing.entries if e.type == "item"]
            cols = [e for e in listing.entries if e.type == "collection"]
            if items and (not cols or rng.random() < 0.7):
                return rng.choice(items)
            if not cols:
                return None
            path = path + [rng.choice(cols).id]
        return None

    def index_build(self, progress=None, limit: int | None = None) -> dict:
        raise SourceError(f"{self.label} has no rating index")

    def index_status(self) -> dict:
        return {"available": False}

    # -- helpers -----------------------------------------------------------
    def online(self) -> bool | None:
        try:
            j = json.loads((paths.SOURCES_CACHE / self.id / "online.json").read_text())
            if time.time() - float(j.get("checked_at", 0)) > 3600:
                return None
            return bool(j.get("ok"))
        except (OSError, ValueError):
            return None

    def describe(self) -> dict:
        return {"id": self.id, "name": self.label, "kind": self.kind,
                "has_thumbnails": self.caps.has_thumbnails, "has_search": self.caps.has_search,
                "can_add_collection": self.caps.can_add_collection, "online": self.online(),
                "has_ratings": self.caps.has_ratings, "has_index": self.caps.has_index,
                "index": self.index_status() if self.caps.has_index else None,
                "user": bool(self.instance.get("user")), "url": self.instance.get("url") or self.instance.get("repo")}

    def listing(self, path, entries, breadcrumbs=None, next_page=None, notice=None) -> Listing:
        return Listing(source=self.id, path=list(path), breadcrumbs=breadcrumbs or [], entries=entries,
                       next_page=next_page, notice=notice)

    def offline_listing(self, path, err: Exception) -> Listing:
        return self.listing(path, [], notice=f"offline: {err}")


__all__ = ["Capabilities", "Entry", "Listing", "Credits", "Fetched", "Provider", "SourceError",
           "HttpClient", "HttpError", "Offline", "is_art_name", "ART_EXTS"]
