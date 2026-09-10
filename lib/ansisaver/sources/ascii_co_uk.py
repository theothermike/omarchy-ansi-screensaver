"""ascii.co.uk — topic pages with <pre> blocks of ASCII art."""
from __future__ import annotations

import html
import re
import urllib.parse

from .base import Capabilities, Credits, Entry, Fetched, Provider, SourceError

BASE = "https://ascii.co.uk"


class AsciiCoUk(Provider):
    kind = "ascii_co_uk"
    label = "ascii.co.uk"
    caps = Capabilities(has_thumbnails=False, has_search=False, can_add_collection=True)
    license_note = "ascii.co.uk: keep the artist's initials/signature in the work."

    def _topics(self) -> list[str]:
        text = self.http.get_text(f"{BASE}/art", ttl=7 * 86400)
        seen, out = set(), []
        for m in re.finditer(r'href="/art/([a-z0-9\-]+)"', text):
            t = m.group(1)
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def _blocks(self, topic: str) -> list[str]:
        text = self.http.get_text(f"{BASE}/art/{urllib.parse.quote(topic)}", ttl=7 * 86400)
        blocks = []
        for m in re.finditer(r"<pre[^>]*>(.*?)</pre>", text, re.S):
            art = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).replace("\r", "")
            art = "\n".join(line.rstrip() for line in art.split("\n")).strip("\n")
            if art.strip() and len(art) > 20:
                blocks.append(art)
        return blocks

    @staticmethod
    def _signature(art: str) -> str:
        lines = [l for l in art.split("\n") if l.strip()]
        if not lines:
            return ""
        m = re.search(r"([A-Za-z][A-Za-z./\-]{1,11})\s*$", lines[-1])
        return m.group(1) if m and len(m.group(1)) <= 12 else ""

    def list(self, path, search, page):
        seg = path[-1] if path else ""
        if seg == "":
            entries = [Entry("collection", f"topic/{t}", t.replace("-", " "), "topic", can_add_all=True) for t in self._topics()]
            return self.listing(path, entries, [], notice=None if entries else "no topics found (markup changed?)")
        if seg.startswith("topic/"):
            topic = seg[6:]
            entries = [self._entry(topic, i, art) for i, art in enumerate(self._blocks(topic))]
            return self.listing(path, entries, [topic.replace("-", " ")], notice=None if entries else "no <pre> art on this page")
        raise SourceError(f"unknown path {seg}")

    def _entry(self, topic: str, i: int, art: str) -> Entry:
        lines = art.split("\n")
        return Entry("item", f"piece/{topic}/{i}", f"{topic.replace('-', ' ')} #{i + 1}", self._signature(art) or "",
                     meta={"author": self._signature(art), "cols": max(len(l) for l in lines), "rows": len(lines), "format": "ascii", "tags": [topic]},
                     text_preview=art, source_url=f"{BASE}/art/{topic}")

    def iter_items(self, entry_id: str):
        if entry_id.startswith("topic/"):
            topic = entry_id[6:]
            for i, art in enumerate(self._blocks(topic)):
                yield self._entry(topic, i, art)
            return
        yield from super().iter_items(entry_id)

    def fetch(self, entry_id: str) -> Fetched:
        if not entry_id.startswith("piece/"):
            raise SourceError(f"not a piece: {entry_id}")
        topic, _, idx = entry_id[6:].rpartition("/")
        blocks = self._blocks(topic)
        i = int(idx)
        if i >= len(blocks):
            raise SourceError("piece index out of range (page changed)")
        art = blocks[i]
        return Fetched(data=(art + "\n").encode("utf-8"), filename=f"{topic}-{i + 1}.txt",
                       credits=Credits(title=f"{topic.replace('-', ' ')} #{i + 1}", author=self._signature(art), tags=[topic]),
                       source_url=f"{BASE}/art/{topic}", license_note=self.license_note, encoding_hint="utf8")

    def ping(self):
        return self.http.ping(f"{BASE}/art")
