"""Any GitHub repository (contents API + raw downloads); zips are browsable."""
from __future__ import annotations

import posixpath
import urllib.parse
import zipfile

from .base import Capabilities, Credits, Entry, Fetched, Provider, SourceError, is_art_name

API = "https://api.github.com"


class GitHubRepo(Provider):
    kind = "github_repo"
    label = "GitHub repository"
    caps = Capabilities(has_thumbnails=False, has_search=False, can_add_collection=True)
    license_note = "From a GitHub repository; see the repository's licence for reuse terms."

    def __init__(self, instance, http=None):
        super().__init__(instance, http)
        self.repo = instance.get("repo") or ""
        self.branch = instance.get("branch") or ""
        self.label = instance.get("label") or self.repo
        self.mirror_thumbs = self.repo == "sixteencolors/sixteencolors-archive"

    def _contents(self, subpath: str) -> list[dict]:
        url = f"{API}/repos/{self.repo}/contents/{urllib.parse.quote(subpath)}" + (f"?ref={self.branch}" if self.branch else "")
        j = self.http.get_json(url, ttl=6 * 3600)
        if isinstance(j, dict) and j.get("message"):
            raise SourceError(f"GitHub: {j['message']}")
        return j if isinstance(j, list) else [j]

    def list(self, path, search, page):
        seg = path[-1] if path else ""
        if seg.startswith("zip/"):
            return self._zip_listing(seg[4:], path)
        sub = seg[4:] if seg.startswith("dir/") else ""
        items = self._contents(sub)
        entries = []
        for it in sorted(items, key=lambda x: (x.get("type") != "dir", x.get("name", "").lower())):
            name = it.get("name", "")
            p = it.get("path", name)
            if it.get("type") == "dir":
                entries.append(Entry("collection", f"dir/{p}", name, "folder", can_add_all=True, source_url=it.get("html_url")))
            elif name.lower().endswith(".zip"):
                thumb = None
                if self.mirror_thumbs:
                    pack = name[:-4]
                    thumb = None  # pack thumbnails need a file name; the pack page itself has none
                entries.append(Entry("collection", f"zip/{p}", name, f"zip · {int(it.get('size') or 0) // 1024} KB", can_add_all=True,
                                     thumb_url=thumb, source_url=it.get("html_url")))
            elif is_art_name(name):
                entries.append(Entry("item", f"file/{p}", name, f"{int(it.get('size') or 0) // 1024} KB", meta={"size": it.get("size")},
                                     source_url=it.get("html_url")))
        crumbs = [c.split("/")[-1] for c in path]
        return self.listing(path, entries, crumbs, notice=None if entries else "nothing browsable here")

    def _zip_path(self, p: str):
        url = f"https://raw.githubusercontent.com/{self.repo}/{self.branch or 'HEAD'}/{urllib.parse.quote(p)}"
        return self.http.download(url, filename=posixpath.basename(p))

    def _zip_listing(self, p: str, path):
        zpath = self._zip_path(p)
        pack = posixpath.basename(p)[:-4]
        entries = []
        with zipfile.ZipFile(zpath) as z:
            for m in z.namelist():
                base = posixpath.basename(m)
                if is_art_name(base) and "__MACOSX" not in m and not base.lower().startswith("file_id"):
                    thumb = f"https://16colo.rs/pack/{pack}/tn/{urllib.parse.quote(base)}.png" if self.mirror_thumbs else None
                    entries.append(Entry("item", f"zipfile/{p}!/{m}", base, f"{z.getinfo(m).file_size // 1024} KB", thumb_url=thumb,
                                         image_url=f"https://16colo.rs/pack/{pack}/x1/{urllib.parse.quote(base)}.png" if self.mirror_thumbs else None,
                                         source_url=f"https://16colo.rs/pack/{pack}/{urllib.parse.quote(base)}" if self.mirror_thumbs else None))
        return self.listing(path, entries, [c.split("/")[-1] for c in path])

    def iter_items(self, entry_id: str):
        if entry_id.startswith("zip/"):
            yield from self._zip_listing(entry_id[4:], [entry_id]).entries
            return
        if entry_id.startswith("dir/"):
            for e in self.list([entry_id], None, 1).entries:
                if e.type == "item":
                    yield e
                elif e.id.startswith("zip/"):
                    yield from self.iter_items(e.id)
            return
        yield from super().iter_items(entry_id)

    def fetch(self, entry_id: str) -> Fetched:
        if entry_id.startswith("file/"):
            p = entry_id[5:]
            url = f"https://raw.githubusercontent.com/{self.repo}/{self.branch or 'HEAD'}/{urllib.parse.quote(p)}"
            data = self.http.get_bytes(url, ttl=30 * 86400)
            return Fetched(data=data, filename=posixpath.basename(p), credits=Credits(), source_url=f"https://github.com/{self.repo}/blob/HEAD/{p}",
                           license_note=self.license_note)
        if entry_id.startswith("zipfile/"):
            p, _, member = entry_id[8:].partition("!/")
            zpath = self._zip_path(p)
            with zipfile.ZipFile(zpath) as z:
                data = z.read(member)
            pack = posixpath.basename(p)[:-4]
            base = posixpath.basename(member)
            src = f"https://16colo.rs/pack/{pack}/{urllib.parse.quote(base)}" if self.mirror_thumbs else f"https://github.com/{self.repo}/blob/HEAD/{p}"
            return Fetched(data=data, filename=base, credits=Credits(), source_url=src, license_note=self.license_note, pack=pack,
                           image_url=f"https://16colo.rs/pack/{pack}/x1/{urllib.parse.quote(base)}.png" if self.mirror_thumbs else None)
        raise SourceError(f"not a file: {entry_id}")

    def ping(self):
        return self.http.ping(f"{API}/repos/{self.repo}")
