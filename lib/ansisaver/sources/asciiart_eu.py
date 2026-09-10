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
    caps = Capabilities(has_thumbnails=False, has_search=False, can_add_collection=True, has_ratings=True, has_index=True)
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
        # likes / views per card: data-views on the card, likes after the heart icon
        text = self.http.get_text(urllib.parse.urljoin(BASE + "/", rel.lstrip("/")), ttl=7 * 86400)
        stats: dict[str, tuple[int, int]] = {}
        for m in re.finditer(r'<div class="card art-card[^"]*"([^>]*)>(.*?)</div></div></div>', text, re.S):
            attrs, body = m.group(1), m.group(2)
            mid = re.search(r'data-id="([^"]+)"', attrs)
            if not mid:
                continue
            mv = re.search(r'data-views="(\d+)"', attrs)
            ml = re.search(r'icon-heart-alt[^>]*></i>\s*(\d+)', body)
            stats[mid.group(1)] = (int(ml.group(1)) if ml else 0, int(mv.group(1)) if mv else 0)
        for c in cards:
            c["text"] = (c["text"] or "").replace("\r", "").strip("\n")
            # drop trailing spaces per line, keep leading ones
            c["text"] = "\n".join(line.rstrip() for line in c["text"].split("\n"))
            c["likes"], c["views"] = stats.get(c["id"], (0, 0))
        return [c for c in cards if c["text"].strip()]

    @staticmethod
    def score(likes: int, views: int) -> float:
        """Likes dominate; views break ties (log scale)."""
        import math
        return likes * 10.0 + math.log10(max(1, views))

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
        likes, views = int(c.get("likes") or 0), int(c.get("views") or 0)
        return Entry("item", f"piece/{rel}/{c['id']}", c["title"] or c["id"],
                     " · ".join(x for x in [c["artist"] or "unknown", f"♥ {likes}" if likes else "", f"{views} views" if views else ""] if x),
                     meta={"author": c["artist"], "cols": int(c["width"] or 0) or None, "rows": int(c["height"] or 0) or None, "format": "ascii",
                           "tags": rel.split("/"), "likes": likes, "views": views, "score": self.score(likes, views)},
                     text_preview=c["text"], source_url=f"{BASE}/{rel}")

    # -- rating index (local state for random-top picks) ----------------------
    def _index_path(self):
        from .. import paths
        return paths.SOURCES_CACHE / self.id / "index.json"

    def index_status(self) -> dict:
        import json, time
        p = self._index_path()
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            return {"available": True, "items": len(j.get("items") or []), "built": j.get("built"), "pages": j.get("pages"),
                    "age_days": round((time.time() - float(j.get("built_at") or 0)) / 86400, 1)}
        except (OSError, ValueError):
            return {"available": False}

    def index_build(self, progress=None, limit=None) -> dict:
        """Crawl every category page once and record likes/views per piece."""
        import json, time
        cats = self._categories("")
        pages: list[str] = []
        for i, (cat, _label) in enumerate(cats):
            if progress:
                progress(i + 1, len(cats), f"scanning {cat}")
            subs = [p for p, _ in self._categories(cat) if p != cat]
            pages.extend(subs or [cat])
            if limit and len(pages) >= limit:
                break
        pages = pages[:limit] if limit else pages
        items = []
        for i, rel in enumerate(pages):
            if progress:
                progress(i + 1, len(pages), rel)
            try:
                for c in self._cards(rel):
                    items.append({"id": f"piece/{rel}/{c['id']}", "rel": rel, "title": c["title"], "artist": c["artist"],
                                  "likes": int(c.get("likes") or 0), "views": int(c.get("views") or 0),
                                  "score": self.score(int(c.get("likes") or 0), int(c.get("views") or 0))})
            except Exception:  # noqa: BLE001
                continue
        p = self._index_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"built": time.strftime("%Y-%m-%d"), "built_at": time.time(), "pages": len(pages), "items": items}), encoding="utf-8")
        return {"pages": len(pages), "items": len(items), "path": str(p)}

    def random_items(self, n, rng, top=False):
        import json
        if top:
            try:
                idx = json.loads(self._index_path().read_text(encoding="utf-8")).get("items") or []
            except (OSError, ValueError):
                raise SourceError("asciiart.eu rating index not built yet (Sources tab: 'Build rating index', or `ansi-screensaver index build --source asciiart_eu`)")
            idx = sorted(idx, key=lambda x: -x["score"])
            pool = idx[: max(n * 5, len(idx) // 10 or n)]      # the top tenth (at least 5n)
            picks = rng.sample(pool, min(n, len(pool)))
            out = []
            for it in picks:
                cards = {c["id"]: c for c in self._cards(it["rel"])}
                cid = it["id"].rsplit("/", 1)[-1]
                if cid in cards:
                    out.append(self._entry(it["rel"], cards[cid]))
            return out
        # plain random: random category -> random subcategory -> random card
        picked, seen, attempts = [], set(), 0
        cats = self._categories("")
        while len(picked) < n and attempts < n * 6 + 6 and cats:
            attempts += 1
            cat, _ = rng.choice(cats)
            try:
                subs = [p for p, _ in self._categories(cat) if p != cat]
                rel = rng.choice(subs) if subs else cat
                cards = self._cards(rel)
            except Exception:  # noqa: BLE001
                continue
            if not cards:
                continue
            e = self._entry(rel, rng.choice(cards))
            if e.id not in seen:
                seen.add(e.id)
                picked.append(e)
        return picked

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
                likes, views = int(c.get("likes") or 0), int(c.get("views") or 0)
                return Fetched(data=text.encode("utf-8"), filename=f"{name}-{cid[:6]}.txt",
                               credits=Credits(title=c["title"], author=c["artist"] if c["artist"] and c["artist"].lower() != "unknown" else "", tags=rel.split("/")),
                               source_url=f"{BASE}/{rel}", license_note=self.license_note, encoding_hint="utf8",
                               rating={"likes": likes, "views": views, "score": self.score(likes, views)})
        raise SourceError(f"piece {cid} not found on {rel}")

    def ping(self):
        return self.http.ping(BASE + "/")
