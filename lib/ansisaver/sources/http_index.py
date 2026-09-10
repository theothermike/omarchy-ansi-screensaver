"""Plain HTTP directory listings (Apache/nginx style, and textfiles.com's)."""
from __future__ import annotations

import html
import posixpath
import re
import urllib.parse
from html.parser import HTMLParser

from .base import Capabilities, Credits, Entry, Fetched, Provider, SourceError, is_art_name
from .archives import art_members, is_archive_name, read_member

SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".html", ".htm", ".css", ".js", ".mp3", ".xb", ".exe", ".com", ".zip.txt")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = None
        self._text = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            for k, v in attrs:
                if k.lower() == "href" and v:
                    self._href = v
                    self._text = ""

    def handle_data(self, data):
        if self._href is not None:
            self._text += data

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, self._text.strip()))
            self._href = None


class HttpIndex(Provider):
    kind = "http_index"
    label = "HTTP directory"
    caps = Capabilities(has_thumbnails=True, has_search=False, can_add_collection=True)
    license_note = "Fetched from a public web archive; artwork remains its authors' property."

    def __init__(self, instance, http=None):
        super().__init__(instance, http)
        self.base = instance.get("url") or "http://artscene.textfiles.com/"
        if not self.base.endswith("/"):
            self.base += "/"
        self.timeout = float(instance.get("timeout") or 8)
        self.label = instance.get("label") or urllib.parse.urlsplit(self.base).hostname or self.base

    def _page(self, rel: str) -> tuple[list[tuple[str, str]], set[str]]:
        url = urllib.parse.urljoin(self.base, rel)
        text = self.http.get_text(url, ttl=86400, encoding="latin-1", timeout=self.timeout)
        p = _Links()
        p.feed(text)
        links = []
        names = set()
        for href, label in p.links:
            if href.startswith(("?", "#", "mailto:", "javascript:")):
                continue
            absu = urllib.parse.urljoin(url, href)
            if not absu.startswith(self.base):
                continue
            rel2 = absu[len(self.base):]
            if rel2 in ("", rel) or rel2.startswith("..") or (rel and not rel2.startswith(rel)):
                continue
            links.append((rel2, label or posixpath.basename(rel2.rstrip("/"))))
            names.add(rel2)
        return links, names

    def list(self, path, search, page):
        seg = path[-1] if path else ""
        if seg.startswith("zip/"):
            return self._zip_listing(seg[4:], path)
        rel = seg[4:] if seg.startswith("dir/") else ""
        links, names = self._page(rel)
        entries = []
        seen = set()
        for rel2, label in links:
            if rel2 in seen:
                continue
            seen.add(rel2)
            name = posixpath.basename(rel2.rstrip("/"))
            low = name.lower()
            if rel2.endswith("/") or ("." not in name and not is_art_name(name)):
                d = rel2 if rel2.endswith("/") else rel2 + "/"
                if d.rstrip("/").startswith(rel.rstrip("/")) and d != rel:
                    entries.append(Entry("collection", f"dir/{d}", name, "folder", can_add_all=True, source_url=urllib.parse.urljoin(self.base, d)))
            elif is_archive_name(low):
                entries.append(Entry("collection", f"zip/{rel2}", name, "zip", can_add_all=True, source_url=urllib.parse.urljoin(self.base, rel2)))
            elif is_art_name(name) and not low.endswith(SKIP_EXT):
                # textfiles.com keeps PNG renders next to the art under .png/<name>.png
                pngrel = posixpath.join(posixpath.dirname(rel2), ".png", name + ".png")
                thumb = urllib.parse.urljoin(self.base, pngrel) if pngrel in names else None
                entries.append(Entry("item", f"file/{rel2}", name, "", thumb_url=thumb, image_url=thumb,
                                     source_url=urllib.parse.urljoin(self.base, rel2)))
        entries.sort(key=lambda e: (e.type != "collection", e.label.lower()))
        crumbs = [c.rstrip("/").split("/")[-1] for c in path]
        return self.listing(path, entries, crumbs, notice=None if entries else "no browsable entries here")

    def _zip_listing(self, rel: str, path):
        zpath = self.http.download(urllib.parse.urljoin(self.base, rel), filename=posixpath.basename(rel))
        entries = [Entry("item", f"zipfile/{rel}!/{m}", posixpath.basename(m), f"{size // 1024} KB") for m, size in art_members(zpath)]
        return self.listing(path, entries, [c.rstrip("/").split("/")[-1] for c in path], notice=None if entries else "no text-art files in this archive")

    def iter_items(self, entry_id: str):
        if entry_id.startswith("zip/"):
            yield from self._zip_listing(entry_id[4:], [entry_id]).entries
            return
        if entry_id.startswith("dir/"):
            for e in self.list([entry_id], None, 1).entries:
                if e.type == "item":
                    yield e
            return
        yield from super().iter_items(entry_id)

    def fetch(self, entry_id: str) -> Fetched:
        if entry_id.startswith("file/"):
            rel = entry_id[5:]
            url = urllib.parse.urljoin(self.base, rel)
            data = self.http.get_bytes(url, ttl=30 * 86400, timeout=self.timeout)
            return Fetched(data=data, filename=posixpath.basename(rel), credits=Credits(), source_url=url, license_note=self.license_note,
                           pack=posixpath.basename(posixpath.dirname(rel)) or None)
        if entry_id.startswith("zipfile/"):
            rel, _, member = entry_id[8:].partition("!/")
            zpath = self.http.download(urllib.parse.urljoin(self.base, rel), filename=posixpath.basename(rel))
            data = read_member(zpath, member)
            return Fetched(data=data, filename=posixpath.basename(member), credits=Credits(), source_url=urllib.parse.urljoin(self.base, rel),
                           license_note=self.license_note, pack=posixpath.basename(rel)[:-4])
        raise SourceError(f"not a file: {entry_id}")

    def ping(self):
        return self.http.ping(self.base)
