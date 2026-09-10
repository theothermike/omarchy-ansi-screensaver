"""16colo.rs — the ANSI/ASCII art archive (JSON API at api.16colo.rs/v1)."""
from __future__ import annotations

import io
import posixpath
import urllib.parse
import zipfile
from typing import Iterator

from .base import Capabilities, Credits, Entry, Fetched, Provider, SourceError, is_art_name

BASE = "https://16colo.rs"
API = "https://api.16colo.rs/v1"
PAGE = 60
MIRROR = "https://raw.githubusercontent.com/sixteencolors/sixteencolors-archive/master"


def _s(v) -> str:
    return "" if v is None else str(v)


def _abs(u: str | None) -> str | None:
    if not u:
        return None
    return u if u.startswith("http") else urllib.parse.urljoin(BASE + "/", u.lstrip("/"))


class SixteenColors(Provider):
    kind = "sixteencolors"
    label = "16colo.rs"
    caps = Capabilities(has_thumbnails=True, has_search=True, can_add_collection=True)
    license_note = "Artwork remains the artist's intellectual property; distributed via the 16colo.rs archive with SAUCE credits preserved."

    # ---------------------------------------------------------------- listing
    def _crumbs(self, path: list[str]) -> list[str]:
        out = []
        for seg in path:
            kind, _, rest = seg.partition("/")
            out.append({"years": "Years", "groups": "Groups", "artists": "Artists", "latest": "Latest"}.get(seg, rest or seg))
        return out

    def _pack_entry(self, p: dict) -> Entry:
        name = p.get("name") or p.get("pack") or ""
        groups = p.get("groups") or []
        gnames = []
        for g in groups:
            if isinstance(g, dict):
                gnames.append(g.get("name") or g.get("tag") or next(iter(g.values()), "") if g else "")
            else:
                gnames.append(str(g))
        year = p.get("year")
        return Entry(type="collection", id=f"pack/{name}", label=name,
                     sublabel=" · ".join([s for s in [str(year) if year else "", ", ".join(x for x in gnames if x)] if s]),
                     meta={"year": year, "group": ", ".join(x for x in gnames if x)}, can_add_all=True,
                     source_url=_abs(p.get("gallery")) or f"{BASE}/pack/{name}")

    def _packs_page(self, url: str, path: list[str], page: int, ttl: float = 86400) -> "Listing":
        j = self.http.get_json(url, ttl=ttl)
        results = j.get("results") or []
        entries = [self._pack_entry(p) for p in results if isinstance(p, dict)]
        pg = j.get("page") or {}
        nxt = page + 1 if pg.get("pages") and page < int(pg["pages"]) else None
        return self.listing(path, entries, self._crumbs(path), next_page=nxt)

    def _search(self, search: str, path, page: int):
        """The API's `filter` is a fuzzy match where '-' and '_' act as
        wildcards (a hyphenated pack name returns every pack), so ask for the
        longest word and narrow the result to names containing every token."""
        import re
        tokens = [t for t in re.split(r"[^a-z0-9]+", search.lower()) if t]
        if not tokens:
            return self.listing(path, [], [f"search: {search}"])
        key = max(tokens, key=len)
        j = self.http.get_json(f"{API}/pack/?filter={urllib.parse.quote(key)}&pagesize=500&page=1", ttl=86400)
        results = [p for p in (j.get("results") or []) if isinstance(p, dict)
                   and all(t in str(p.get("name") or "").lower() for t in tokens)]
        entries = [self._pack_entry(p) for p in results]
        start = (page - 1) * PAGE
        chunk = entries[start:start + PAGE]
        nxt = page + 1 if start + PAGE < len(entries) else None
        total = int((j.get("page") or {}).get("total") or 0)
        notice = f"{len(entries)} packs match" + (" (first 500 checked)" if total > 500 else "")
        return self.listing(path, chunk, [f"search: {search}"], next_page=nxt, notice=notice)

    def list(self, path, search, page):
        seg = path[-1] if path else ""
        if search and not path:
            return self._search(search, path, page)
        if seg == "":
            return self.listing(path, [
                Entry("collection", "years", "By year", "every artpack since 1990"),
                Entry("collection", "groups", "By group", "ACiD, iCE, Blocktronics, Mistigris…"),
                Entry("collection", "artists", "By artist", "individual artists"),
                Entry("collection", "latest", "Latest releases", "the 20 newest packs"),
            ], [])
        if seg == "years":
            j = self.http.get_json(f"{API}/year/", ttl=7 * 86400)
            entries = [Entry("collection", f"year/{y}", str(y), f"{v.get('packs', 0)} packs", meta={"year": int(y)}, can_add_all=False)
                       for y, v in sorted(j.items(), key=lambda kv: kv[0], reverse=True) if str(y).isdigit()]
            return self.listing(path, entries, self._crumbs(path))
        if seg.startswith("year/"):
            y = seg[5:]
            return self._packs_page(f"{API}/year/{y}?type=packs&pagesize={PAGE}&page={page}", path, page)
        if seg == "groups":
            j = self.http.get_json(f"{API}/group/?pagesize={PAGE}&page={page}", ttl=7 * 86400)
            entries = []
            for r in j.get("results") or []:
                if isinstance(r, dict):
                    for name, info in r.items():
                        info = info if isinstance(info, dict) else {}
                        entries.append(Entry("collection", f"group/{name}", name, f"{info.get('releases', '?')} releases",
                                             thumb_url=_abs(info.get("logo")), can_add_all=False))
            pg = j.get("page") or {}
            nxt = page + 1 if pg.get("pages") and page < int(pg["pages"]) else None
            return self.listing(path, entries, self._crumbs(path), next_page=nxt)
        if seg.startswith("group/"):
            g = seg[6:]
            j = self.http.get_json(f"{API}/group/{urllib.parse.quote(g)}?packs=true", ttl=86400)
            packs = ((j.get("results") or {}).get("packs")) or {}
            entries = []
            for year in sorted(packs, reverse=True):
                for p in packs[year] or []:
                    if isinstance(p, dict):
                        p = dict(p); p.setdefault("year", year)
                        entries.append(self._pack_entry(p))
                    else:
                        entries.append(self._pack_entry({"name": str(p), "year": year}))
            return self.listing(path, entries, self._crumbs(path))
        if seg == "artists":
            j = self.http.get_json(f"{API}/artist/?pagesize={PAGE}&page={page}&details=true", ttl=7 * 86400)
            entries = []
            for r in j.get("results") or []:
                a = r.get("artist") if isinstance(r, dict) else None
                if isinstance(a, dict) and a.get("name"):
                    entries.append(Entry("collection", f"artist/{a['name']}", a["name"],
                                         f"{a.get('releases', '?')} releases · " + ", ".join(map(str, (a.get("groups") or [])[:3])), can_add_all=True))
            pg = j.get("page") or {}
            nxt = page + 1 if pg.get("pages") and page < int(pg["pages"]) else None
            return self.listing(path, entries, self._crumbs(path), next_page=nxt)
        if seg.startswith("artist/"):
            a = seg[7:]
            j = self.http.get_json(f"{API}/artist/{urllib.parse.quote(a)}?view=artwork", ttl=86400)
            return self.listing(path, self._artist_items(j), self._crumbs(path))
        if seg == "latest":
            j = self.http.get_json(f"{API}/latest/releases", ttl=3600)
            results = j.get("results") or j if isinstance(j, list) else j.get("results") or []
            entries = [self._pack_entry(p) for p in results if isinstance(p, dict)]
            return self.listing(path, entries, self._crumbs(path))
        if seg.startswith("pack/"):
            return self.listing(path, self._pack_items(seg[5:]), self._crumbs(path))
        raise SourceError(f"unknown path {seg}")

    def _artist_items(self, j: dict) -> list[Entry]:
        entries = []
        res = j.get("results")
        files = []
        if isinstance(res, dict):
            for v in res.values():
                if isinstance(v, list):
                    files.extend(x for x in v if isinstance(x, dict))
                elif isinstance(v, dict):
                    for vv in v.values():
                        if isinstance(vv, list):
                            files.extend(x for x in vv if isinstance(x, dict))
        elif isinstance(res, list):
            files = [x for x in res if isinstance(x, dict)]
        for f in files:
            pack = f.get("pack") or f.get("packname") or ""
            name = f.get("file") or f.get("filename") or f.get("name") or ""
            if not pack or not name or not is_art_name(name):
                continue
            entries.append(Entry("item", f"file/{pack}/{name}", name, pack, meta={"year": f.get("year")},
                                 thumb_url=_abs(f.get("tn") or f"/pack/{pack}/tn/{name}.png"),
                                 image_url=_abs(f.get("x1") or f"/pack/{pack}/x1/{name}.png"),
                                 source_url=f"{BASE}/pack/{pack}/{urllib.parse.quote(name)}"))
        return entries

    def _pack_info(self, pack: str) -> dict:
        j = self.http.get_json(f"{API}/pack/{urllib.parse.quote(pack)}?sauce=true&content=true&dimensions=true&artists=true", ttl=7 * 86400)
        results = j.get("results") or []
        if not results:
            raise SourceError(f"pack {pack} not found on 16colo.rs")
        return results[0]

    def _pack_items(self, pack: str) -> list[Entry]:
        info = self._pack_info(pack)
        entries = []
        files = info.get("files") or {}
        for name, f in files.items():
            if not isinstance(f, dict) or not is_art_name(name):
                continue
            sauce = f.get("sauce") or {}
            if sauce and sauce.get("Datatype") not in (None, 1):
                continue
            low = name.lower()
            if low.startswith("file_id") or low.endswith((".diz", ".nfo")):
                continue
            artists = ", ".join(_s(a) for a in (f.get("artists") or []))
            author = _s(sauce.get("Author")) or artists
            year = info.get("year")
            d = str(sauce.get("Date") or "")
            if len(d) >= 4 and d[:4].isdigit():
                year = int(d[:4])
            tn = (f.get("file") or {}).get("tn") or {}
            x1 = (f.get("file") or {}).get("x1") or {}
            flags = sauce.get("ansiflags") or {}
            entries.append(Entry(
                type="item", id=f"file/{pack}/{name}", label=_s(sauce.get("Title")) or name,
                sublabel=" · ".join(s for s in [author, _s(sauce.get("Group"))] if s),
                meta={"author": author, "group": _s(sauce.get("Group")), "year": year,
                      "cols": sauce.get("Tinfo1") or (None if low.endswith((".asc", ".txt")) else 80),
                      "rows": sauce.get("Tinfo2"), "size": sauce.get("Filesize"),
                      "format": "ansi" if low.endswith((".ans", ".ansi")) else "ascii", "ice": bool(flags.get("ice")),
                      "font": sauce.get("Tinfos") or "", "tags": f.get("content") or [], "file": name},
                thumb_url=_abs(tn.get("uri")) if tn else _abs(f"/pack/{pack}/tn/{name}.png"),
                image_url=_abs(x1.get("uri")) if x1 else _abs(f"/pack/{pack}/x1/{name}.png"),
                source_url=f"{BASE}/pack/{pack}/{urllib.parse.quote(name)}"))
        entries.sort(key=lambda e: (e.meta.get("rows") or 0, e.label.lower()))
        return entries

    def iter_items(self, entry_id: str) -> Iterator[Entry]:
        if entry_id.startswith("pack/"):
            yield from self._pack_items(entry_id[5:])
            return
        if entry_id.startswith("artist/"):
            j = self.http.get_json(f"{API}/artist/{urllib.parse.quote(entry_id[7:])}?view=artwork", ttl=86400)
            yield from self._artist_items(j)
            return
        yield from super().iter_items(entry_id)

    # ---------------------------------------------------------------- fetching
    def _pack_zip(self, pack: str, info: dict):
        url = _abs(info.get("download")) or f"{BASE}/archive/{info.get('year')}/{pack}.zip"
        try:
            return self.http.download(url, filename=f"{pack}.zip")
        except Exception as first:  # noqa: BLE001
            if info.get("year"):
                return self.http.download(f"{MIRROR}/{info['year']}/{pack}.zip", filename=f"{pack}.zip")
            raise first

    def fetch(self, entry_id: str) -> Fetched:
        if not entry_id.startswith("file/"):
            raise SourceError(f"not a file entry: {entry_id}")
        pack, _, name = entry_id[5:].partition("/")
        info = self._pack_info(pack)
        zpath = self._pack_zip(pack, info)
        data = None
        with zipfile.ZipFile(zpath) as z:
            for member in z.namelist():
                if posixpath.basename(member).lower() == name.lower() and "__MACOSX" not in member:
                    data = z.read(member)
                    break
        if data is None:
            raise SourceError(f"{name} not found inside {pack}.zip")
        f = (info.get("files") or {}).get(name) or {}
        sauce = f.get("sauce") or {}
        d = str(sauce.get("Date") or "")
        year = int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else info.get("year")
        hint = "latin1" if any(k in str(sauce.get("Tinfos") or "").lower() for k in ("amiga", "topaz")) else None
        x1 = (f.get("file") or {}).get("x1") or {}
        return Fetched(data=data, filename=name,
                       credits=Credits(title=_s(sauce.get("Title")), author=_s(sauce.get("Author")) or ", ".join(_s(a) for a in (f.get("artists") or [])),
                                       group=_s(sauce.get("Group")), year=year, date=d, tags=[_s(t) for t in (f.get("content") or [])]),
                       source_url=f"{BASE}/pack/{pack}/{urllib.parse.quote(name)}", license_note=self.license_note,
                       image_url=_abs(x1.get("uri")) if x1 else _abs(f"/pack/{pack}/x1/{name}.png"), encoding_hint=hint, pack=pack)

    def ping(self):
        return self.http.ping(f"{API}/year/")
