"""Internet Archive — search-driven (advancedsearch + metadata APIs)."""
from __future__ import annotations

import io
import posixpath
import urllib.parse
import zipfile

from .base import Capabilities, Credits, Entry, Fetched, Provider, SourceError, is_art_name

PRESETS = [("ansi art", "ANSI art"), ("ascii art collection", "ASCII art collections"), ("artpack ansi", "Artpacks"),
           ("blocktronics", "Blocktronics"), ("mistigris", "Mistigris"), ("acid productions ansi", "ACiD Productions")]
ROWS = 50


class ArchiveOrg(Provider):
    kind = "archive_org"
    label = "Internet Archive"
    caps = Capabilities(has_thumbnails=True, has_search=True, can_add_collection=True)
    license_note = "Hosted by the Internet Archive; see the item's page for its licence."

    def _search(self, q: str, page: int, path):
        url = ("https://archive.org/advancedsearch.php?q=" + urllib.parse.quote(q)
               + "&fl[]=identifier&fl[]=title&fl[]=year&fl[]=mediatype&fl[]=creator"
               + f"&rows={ROWS}&page={page}&output=json")
        j = self.http.get_json(url, ttl=86400)
        resp = j.get("response") or {}
        docs = resp.get("docs") or []
        entries = []
        for d in docs:
            ident = d.get("identifier")
            if not ident:
                continue
            creator = d.get("creator")
            creator = ", ".join(creator) if isinstance(creator, list) else (creator or "")
            entries.append(Entry("collection", f"item/{ident}", d.get("title") or ident,
                                 " · ".join(s for s in [str(d.get("year") or ""), d.get("mediatype") or "", creator] if s),
                                 meta={"year": d.get("year"), "author": creator}, thumb_url=f"https://archive.org/services/img/{ident}",
                                 can_add_all=True, source_url=f"https://archive.org/details/{ident}"))
        total = int(resp.get("numFound") or 0)
        nxt = page + 1 if page * ROWS < total else None
        return self.listing(path, entries, [f"search: {q}"], next_page=nxt, notice=f"{total} items match")

    def list(self, path, search, page):
        seg = path[-1] if path else ""
        if search:
            return self._search(search, page, path)
        if seg == "":
            return self.listing(path, [Entry("collection", f"q/{q}", label, f"search: {q}") for q, label in PRESETS], [],
                                notice="type a search above for anything else")
        if seg.startswith("q/"):
            return self._search(seg[2:], page, path)
        if seg.startswith("item/"):
            ident = seg[5:]
            j = self.http.get_json(f"https://archive.org/metadata/{ident}", ttl=7 * 86400)
            files = j.get("files") or []
            title = (j.get("metadata") or {}).get("title") or ident
            entries = []
            for f in files:
                name = f.get("name") or ""
                low = name.lower()
                if is_art_name(posixpath.basename(name)):
                    entries.append(Entry("item", f"file/{ident}/{name}", posixpath.basename(name), f"{int(f.get('size') or 0) // 1024} KB",
                                         meta={"size": f.get("size")}, source_url=f"https://archive.org/download/{ident}/{urllib.parse.quote(name)}"))
                elif low.endswith(".zip"):
                    entries.append(Entry("collection", f"zip/{ident}/{name}", posixpath.basename(name), f"zip · {int(f.get('size') or 0) // 1024} KB",
                                         can_add_all=True, source_url=f"https://archive.org/download/{ident}/{urllib.parse.quote(name)}"))
            return self.listing(path, entries, [title], notice=None if entries else "no text-art files in this item")
        if seg.startswith("zip/"):
            ident, _, name = seg[4:].partition("/")
            zpath = self.http.download(f"https://archive.org/download/{ident}/{urllib.parse.quote(name)}", filename=posixpath.basename(name))
            entries = []
            with zipfile.ZipFile(zpath) as z:
                for m in z.namelist():
                    if is_art_name(posixpath.basename(m)) and "__MACOSX" not in m:
                        entries.append(Entry("item", f"zipfile/{ident}/{name}!/{m}", posixpath.basename(m), f"{z.getinfo(m).file_size // 1024} KB"))
            return self.listing(path, entries, [posixpath.basename(name)])
        raise SourceError(f"unknown path {seg}")

    def fetch(self, entry_id: str) -> Fetched:
        if entry_id.startswith("file/"):
            ident, _, name = entry_id[5:].partition("/")
            url = f"https://archive.org/download/{ident}/{urllib.parse.quote(name)}"
            data = self.http.get_bytes(url, ttl=30 * 86400)
            return Fetched(data=data, filename=posixpath.basename(name), credits=Credits(), source_url=url, license_note=self.license_note, pack=ident)
        if entry_id.startswith("zipfile/"):
            rest = entry_id[8:]
            ident, _, rest = rest.partition("/")
            zname, _, member = rest.partition("!/")
            zpath = self.http.download(f"https://archive.org/download/{ident}/{urllib.parse.quote(zname)}", filename=posixpath.basename(zname))
            with zipfile.ZipFile(zpath) as z:
                data = z.read(member)
            return Fetched(data=data, filename=posixpath.basename(member), credits=Credits(), pack=posixpath.basename(zname).rsplit(".", 1)[0],
                           source_url=f"https://archive.org/download/{ident}/{urllib.parse.quote(zname)}", license_note=self.license_note)
        raise SourceError(f"not a file: {entry_id}")

    def ping(self):
        return self.http.ping("https://archive.org/metadata/textfiles")
