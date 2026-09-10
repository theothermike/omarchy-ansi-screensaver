"""Polite cached HTTP client (stdlib only)."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import __version__, paths

UA = f"ansi-screensaver/{__version__} (Omarchy plugin; +https://github.com/theothermike/omarchy-ansi-screensaver)"
HOST_INTERVAL = {"api.16colo.rs": 0.5, "16colo.rs": 0.5, "demozoo.org": 1.0, "api.github.com": 1.0,
                 "archive.org": 1.0, "www.asciiart.eu": 2.0, "ascii.co.uk": 2.0, "artscene.textfiles.com": 1.0}


class Offline(Exception):
    pass


class HttpError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url


class HttpClient:
    def __init__(self, provider: str, timeout: float = 15.0, token: str | None = None):
        self.provider = provider
        self.timeout = timeout
        self.token = token
        self.dir = paths.SOURCES_CACHE / provider
        self.http_dir = self.dir / "http"
        self.files_dir = self.dir / "files"
        self.state_file = paths.SOURCES_CACHE / "last-request.json"

    # -- rate limiting ----------------------------------------------------
    def _wait_turn(self, host: str) -> None:
        interval = HOST_INTERVAL.get(host, 1.0)
        try:
            state = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            state = {}
        last = float(state.get(host, 0))
        wait = last + interval - time.time()
        if wait > 0:
            time.sleep(min(wait, 5))
        state[host] = time.time()
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(state))
        except OSError:
            pass

    def _mark_online(self, ok: bool) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / "online.json").write_text(json.dumps({"ok": ok, "checked_at": time.time()}))
        except OSError:
            pass

    # -- raw fetch ------------------------------------------------------------
    def _request(self, url: str, etag: str | None = None, headers: dict | None = None, timeout: float | None = None) -> tuple[int, bytes, dict]:
        host = urllib.parse.urlsplit(url).hostname or ""
        self._wait_turn(host)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
        if etag:
            req.add_header("If-None-Match", etag)
        if self.token and host == "api.github.com":
            req.add_header("Authorization", f"Bearer {self.token}")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    data = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                    self._mark_online(True)
                    return resp.status, data, dict(resp.headers)
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    return 304, b"", dict(e.headers)
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                self._mark_online(True)
                raise HttpError(e.code, url) from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < 1:
                    time.sleep(1.0)
                    continue
                self._mark_online(False)
                raise Offline(f"{host}: {getattr(e, 'reason', e)}") from e
        raise Offline(host)

    # -- cached helpers --------------------------------------------------------
    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        h = hashlib.sha1(url.encode()).hexdigest()
        self.http_dir.mkdir(parents=True, exist_ok=True)
        return self.http_dir / f"{h}.bin", self.http_dir / f"{h}.meta"

    def get_bytes(self, url: str, ttl: float = 3600, headers: dict | None = None, timeout: float | None = None) -> bytes:
        body_p, meta_p = self._cache_paths(url)
        meta = None
        if body_p.exists() and meta_p.exists():
            try:
                meta = json.loads(meta_p.read_text())
            except ValueError:
                meta = None
        if meta and ttl > 0 and time.time() - meta.get("fetched_at", 0) < ttl:
            return body_p.read_bytes()
        try:
            status, data, hdrs = self._request(url, etag=(meta or {}).get("etag"), headers=headers, timeout=timeout)
        except Offline:
            if body_p.exists():
                return body_p.read_bytes()
            raise
        if status == 304 and body_p.exists():
            meta["fetched_at"] = time.time()
            meta_p.write_text(json.dumps(meta))
            return body_p.read_bytes()
        body_p.write_bytes(data)
        meta_p.write_text(json.dumps({"url": url, "fetched_at": time.time(), "etag": hdrs.get("ETag") or hdrs.get("etag"),
                                      "status": status, "content_type": hdrs.get("Content-Type", "")}))
        return data

    def get_json(self, url: str, ttl: float = 3600, headers: dict | None = None):
        data = self.get_bytes(url, ttl=ttl, headers={"Accept": "application/json", **(headers or {})})
        return json.loads(data.decode("utf-8", "replace"))

    def get_text(self, url: str, ttl: float = 3600, encoding: str = "utf-8", timeout: float | None = None) -> str:
        return self.get_bytes(url, ttl=ttl, timeout=timeout).decode(encoding, "replace")

    def download(self, url: str, filename: str | None = None, ttl: float = 30 * 86400) -> Path:
        """Fetch a (large) file into the files cache; returns its path."""
        h = hashlib.sha1(url.encode()).hexdigest()
        d = self.files_dir / h
        d.mkdir(parents=True, exist_ok=True)
        name = filename or (urllib.parse.unquote(url.rsplit("/", 1)[-1]) or "file")
        p = d / name
        if p.exists() and (ttl <= 0 or time.time() - p.stat().st_mtime < ttl):
            return p
        status, data, _ = self._request(url)
        p.write_bytes(data)
        return p

    def ping(self, url: str) -> tuple[bool, str]:
        try:
            self._request(url, timeout=5)
            return True, "reachable"
        except HttpError as e:
            return e.status < 500, f"HTTP {e.status}"
        except Offline as e:
            return False, str(e)


import urllib.parse  # noqa: E402  (used above)
