"""asciiart.eu — the ASCII Art Archive (HTML galleries; art embedded per card)."""
from __future__ import annotations

import html
import re
import urllib.parse
from html.parser import HTMLParser

from .base import Capabilities, Credits, Entry, Fetched, Provider, SourceError

BASE = "https://www.asciiart.eu"


class _Cards(HTMLParser):
    """Collects <div class="card art-card" data-*> ... <div>ART</div> blocks and category links."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.cards: list[dict] = []
        self.links: list[tuple[str, str]] = []
        self.galleries: list[tuple[str, str]] = []
        self._card = None
        self._depth = 0
        self._capture = None
        self._cap_depth = 0
        self._href = None
        self._link_text = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and "art-card" in (a.get("class") or "") and a.get("data-id"):
            self._card = {"id": a.get("data-id"), "title": html.unescape(a.get("data-title") or ""), "artist": html.unescape(a.get("data-artist") or ""),
                          "width": a.get("data-width"), "height": a.get("data-height"), "text": None}
            self._depth = 0
        if self._card is not None:
            if tag == "div":
                self._depth += 1
                cls = a.get("class") or ""
                if self._card["text"] is None and self._capture is None and "card-header" not in cls and self._depth >= 2 and "ascii" in cls.lower() or (
                        self._card["text"] is None and self._capture is None and "card-body" in cls):
                    self._capture = ""
                    self._cap_depth = self._depth
        if tag == "a" and a.get("href"):
            self._href = a["href"]
            self._link_text = ""
            if "card-gallery" in (a.get("class") or ""):
                self.galleries.append((a["href"], html.unescape(a.get("title") or "")))

    def handle_data(self, data):
        if self._capture is not None:
            self._capture += data
        if self._href is not None:
            self._link_text += data

    def handle_entityref(self, name):
        ch = html.unescape(f"&{name};")
        if self._capture is not None:
            self._capture += ch
        if self._href is not None:
            self._link_text += ch

    def handle_charref(self, name):
        ch = html.unescape(f"&#{name};")
        if self._capture is not None:
            self._capture += ch
        if self._href is not None:
            self._link_text += ch

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, self._link_text.strip()))
            self._href = None
        if self._card is not None and tag == "div":
            if self._capture is not None and self._depth == self._cap_depth:
                self._card["text"] = self._capture
                self._capture = None
            self._depth -= 1
            if self._depth <= 0:
                if self._card.get("text") is not None:
                    self.cards.append(self._card)
                self._card = None


class AsciiArtEu(Provider):
    kind = "asciiart_eu"
    label = "asciiart.eu"
    caps = Capabilities(has_thumbnails=False, has_search=False, can_add_collection=True)
    license_note = "asciiart.eu: art may be enjoyed, used and shared; keep the artist's name/initials in the work."

    def _fetch_page(self, rel: str) -> _Cards:
        text = self.http.get_text(urllib.parse.urljoin(BASE + "/", rel.lstrip("/")), ttl=7 * 86400)
        p = _Cards()
        p.feed(text)
        return p

    def _fallback_cards(self, rel: str) -> list[dict]:
        """Regex fallback if the class-based parse finds no art (markup drift)."""
        text = self.http.get_text(urllib.parse.urljoin(BASE + "/", rel.lstrip("/")), ttl=7 * 86400)
        cards = []
        for m in re.finditer(r'<div class="card art-card[^"]*"[^>]*data-id="([^"]+)"[^>]*data-title="([^"]*)"[^>]*data-artist="([^"]*)"[^>]*data-height="(\d+)"[^>]*data-width="(\d+)"[^>]*>(.*?)</div></div></div>', text, re.S):
            body = m.group(6)
            # the art is the last text block in the card
            parts = re.split(r"<[^>]+>", body)
            art = max(parts, key=len) if parts else ""
            cards.append({"id": m.group(1), "title": html.unescape(m.group(2)), "artist": html.unescape(m.group(3)),
                          "height": m.group(4), "width": m.group(5), "text": html.unescape(art)})
        return cards

    def _cards(self, rel: str) -> list[dict]:
        p = self._fetch_page(rel)
        cards = p.cards or self._fallback_cards(rel)
        for c in cards:
            c["text"] = (c["text"] or "").replace("\r", "").strip("\n")
            # drop trailing spaces per line, keep leading ones
            c["text"] = "\n".join(line.rstrip() for line in c["text"].split("\n"))
        return [c for c in cards if c["text"].strip()]

    def _categories(self, rel: str = "") -> list[tuple[str, str]]:
        """Gallery categories/subcategories: the <a class="card-gallery" title=...> cards."""
        p = self._fetch_page(rel or "/")
        out, seen = [], set()
        for href, title in p.galleries:
            path = href.strip("/")
            if not path or path in seen or not re.fullmatch(r"[a-z0-9\-/]+", path):
                continue
            if rel and not path.startswith(rel.strip("/") + "/"):
                continue
            seen.add(path)
            out.append((path, title or path.split("/")[-1].replace("-", " ").title()))
        return out

    def list(self, path, search, page):
        seg = path[-1] if path else ""
        if seg == "":
            cats = self._categories("")
            entries = [Entry("collection", f"cat/{p}", label, p, can_add_all=False) for p, label in cats]
            return self.listing(path, entries, [], notice=None if entries else "could not find categories (markup changed?)")
        if seg.startswith("cat/"):
            rel = seg[4:]
            subs = [(p, label) for p, label in self._categories(rel) if p != rel]
            cards = self._cards(rel)
            entries = [Entry("collection", f"cat/{p}", label, p, can_add_all=True) for p, label in subs]
            for c in cards:
                entries.append(self._entry(rel, c))
            crumbs = [c.split("/")[-1].replace("-", " ") for c in path]
            return self.listing(path, entries, crumbs, notice=None if entries else "no art found on this page")
        raise SourceError(f"unknown path {seg}")

    def _entry(self, rel: str, c: dict) -> Entry:
        return Entry("item", f"piece/{rel}/{c['id']}", c["title"] or c["id"], c["artist"] or "unknown",
                     meta={"author": c["artist"], "cols": int(c["width"] or 0) or None, "rows": int(c["height"] or 0) or None, "format": "ascii",
                           "tags": rel.split("/")},
                     text_preview=c["text"], source_url=f"{BASE}/{rel}")

    def iter_items(self, entry_id: str):
        if entry_id.startswith("cat/"):
            for c in self._cards(entry_id[4:]):
                yield self._entry(entry_id[4:], c)
            return
        yield from super().iter_items(entry_id)

    def fetch(self, entry_id: str) -> Fetched:
        if not entry_id.startswith("piece/"):
            raise SourceError(f"not a piece: {entry_id}")
        rel, _, cid = entry_id[6:].rpartition("/")
        for c in self._cards(rel):
            if c["id"] == cid:
                text = c["text"] + "\n"
                name = re.sub(r"[^a-z0-9]+", "-", (c["title"] or cid).lower()).strip("-") or cid
                return Fetched(data=text.encode("utf-8"), filename=f"{name}-{cid[:6]}.txt",
                               credits=Credits(title=c["title"], author=c["artist"] if c["artist"] and c["artist"].lower() != "unknown" else "", tags=rel.split("/")),
                               source_url=f"{BASE}/{rel}", license_note=self.license_note, encoding_hint="utf8")
        raise SourceError(f"piece {cid} not found on {rel}")

    def ping(self):
        return self.http.ping(BASE + "/")
