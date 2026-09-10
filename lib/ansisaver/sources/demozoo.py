"""Demozoo — the demoscene database (JSON API, ANSI/ASCII productions)."""
from __future__ import annotations

import io
import posixpath
import urllib.parse
import zipfile

from .base import Capabilities, Credits, Entry, Fetched, Provider, SourceError, is_art_name

API = "https://demozoo.org/api/v1"
TYPES = [("ANSI", 26, "ansi"), ("ASCII", 24, "ascii"), ("ASCII collection", 25, "asciicoll"), ("Artpack", 51, "artpack")]
PAGE = 50


class Demozoo(Provider):
    kind = "demozoo"
    label = "Demozoo"
    caps = Capabilities(has_thumbnails=True, has_search=True, can_add_collection=False)
    license_note = "Catalogued by Demozoo; artwork remains its authors' property (scene release, freely distributed)."

    def _prod_entry(self, p: dict, with_detail: bool = False) -> Entry:
        authors = ", ".join(a.get("name", "") for a in p.get("author_nicks") or [])
        groups = ", ".join(a.get("name", "") for a in p.get("author_affiliation_nicks") or [])
        date = p.get("release_date") or ""
        year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None
        types = ", ".join(t.get("name", "") for t in p.get("types") or [])
        shots = p.get("screenshots") or []
        thumb = shots[0].get("thumbnail_url") if shots else None
        image = shots[0].get("original_url") if shots else None
        return Entry(type="item", id=f"prod/{p['id']}", label=p.get("title") or str(p["id"]),
                     sublabel=" · ".join(s for s in [authors, groups, str(year) if year else ""] if s),
                     meta={"author": authors, "group": groups, "year": year, "format": "ansi" if "ANSI" in types else "ascii",
                           "types": types, "tags": p.get("tags") or []},
                     thumb_url=thumb, image_url=image, source_url=p.get("demozoo_url") or f"https://demozoo.org/productions/{p['id']}/")

    def list(self, path, search, page):
        seg = path[-1] if path else ""
        if search:
            j = self.http.get_json(f"{API}/productions/?title={urllib.parse.quote(search)}&page_size={PAGE}&page={page}", ttl=86400)
            entries = [self._prod_entry(p) for p in j.get("results") or [] if any(t.get("id") in (24, 25, 26, 51) for t in p.get("types") or [])]
            return self.listing(path, entries, [f"search: {search}"], next_page=page + 1 if j.get("next") else None)
        if seg == "":
            return self.listing(path, [Entry("collection", f"type/{tid}", name, f"Demozoo production type #{tid}") for name, tid, _ in TYPES], [])
        if seg.startswith("type/"):
            tid = seg[5:]
            j = self.http.get_json(f"{API}/productions/?production_type={tid}&page_size={PAGE}&page={page}", ttl=86400)
            entries = [self._prod_entry(p) for p in j.get("results") or []]
            name = next((n for n, t, _ in TYPES if str(t) == tid), tid)
            return self.listing(path, entries, [name], next_page=page + 1 if j.get("next") else None,
                                notice="thumbnails load per item (Demozoo lists carry no screenshots)")
        raise SourceError(f"unknown path {seg}")

    def _detail(self, pid: str) -> dict:
        return self.http.get_json(f"{API}/productions/{pid}/", ttl=30 * 86400)

    def details(self, entries):
        out = []
        for e in entries:
            if e.type == "item" and not e.thumb_url and e.id.startswith("prod/"):
                try:
                    out.append(self._prod_entry(self._detail(e.id[5:])))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            out.append(e)
        return out

    def preview(self, entry_id: str) -> Fetched:
        return self.fetch(entry_id)

    def fetch(self, entry_id: str) -> Fetched:
        if not entry_id.startswith("prod/"):
            raise SourceError(f"not a production: {entry_id}")
        pid = entry_id[5:]
        d = self._detail(pid)
        links = d.get("download_links") or []
        links.sort(key=lambda l: 0 if l.get("link_class") == "SceneOrgFile" else 1)
        if not links:
            raise SourceError("this production has no download link on Demozoo")
        last_err = None
        for l in links:
            url = l.get("url") or ""
            if "files.scene.org/view/" in url:
                url = url.replace("files.scene.org/view/", "files.scene.org/get/")
            if not url.startswith("http"):
                continue
            try:
                p = self.http.download(url)
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
            data = p.read_bytes()
            name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
            if name.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    members = [m for m in z.namelist() if is_art_name(posixpath.basename(m)) and "__MACOSX" not in m]
                    members.sort(key=lambda m: (0 if m.lower().endswith((".ans", ".ansi")) else 1, -z.getinfo(m).file_size))
                    if not members:
                        last_err = SourceError(f"{name}: no art files inside")
                        continue
                    data, name = z.read(members[0]), posixpath.basename(members[0])
            elif not is_art_name(name):
                last_err = SourceError(f"{name}: not a text-art file")
                continue
            e = self._prod_entry(d)
            shots = d.get("screenshots") or []
            return Fetched(data=data, filename=name,
                           credits=Credits(title=d.get("title") or "", author=e.meta["author"], group=e.meta["group"],
                                           year=e.meta["year"], date=d.get("release_date") or "", tags=list(d.get("tags") or [])),
                           source_url=e.source_url or "", license_note=self.license_note,
                           image_url=shots[0].get("original_url") if shots else None)
        raise SourceError(f"could not download production {pid}: {last_err}")

    def ping(self):
        return self.http.ping(f"{API}/production_types/?page_size=1")
