"""Import from URLs (any direct .ans/.asc/.txt/.zip link)."""
from __future__ import annotations

import io
import urllib.parse
import zipfile

from . import library as L
from .sources.http import HttpClient


def import_url(url: str, **kw) -> tuple[dict, bool]:
    http = HttpClient("url")
    data = http.get_bytes(url, ttl=0)
    name = urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1]) or "download.ans"
    source = {"provider": "url", "url": url, "license_note": "downloaded from a URL; credits from SAUCE"}
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = [m for m in z.namelist() if not m.endswith("/") and "__MACOSX" not in m
                       and m.lower().rsplit(".", 1)[-1] in ("ans", "asc", "txt", "nfo", "diz", "ansi")]
            if not members:
                raise L.ImportError_(f"{name}: no art files inside")
            last = None
            for m in members:
                last = L.import_bytes(z.read(m), m, source={**source, "pack": name[:-4]}, **kw)
            return last
    return L.import_bytes(data, name, source=source, **kw)
