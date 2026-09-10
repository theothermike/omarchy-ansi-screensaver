"""Polite cached HTTP client (stdlib only) with hard limits on everything that
arrives from the network.

Archives and API providers are not trusted: every body is streamed and capped
(compressed input and inflated output separately), a Content-Length above the
cap is refused before a single byte is read, cached bodies are checked again
before use (regular file, no symlink following, size cap) and cache files are
written atomically so a partial download is never revalidated with an old ETag.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

from .. import __version__, paths

UA = f"ansi-screensaver/{__version__} (Omarchy plugin; +https://github.com/theothermike/omarchy-ansi-screensaver)"
HOST_INTERVAL = {"api.16colo.rs": 0.5, "16colo.rs": 0.5, "demozoo.org": 1.0, "api.github.com": 1.0,
                 "archive.org": 1.0, "www.asciiart.eu": 1.0, "ascii.co.uk": 1.5, "artscene.textfiles.com": 1.0}

MIB = 1024 * 1024
MAX_BODY = 16 * MIB        # get_bytes/get_json/get_text: API pages and single art files (raw and inflated)
MAX_DOWNLOAD = 128 * MIB   # download(): packs and archives, streamed straight to disk
MAX_META = 64 * 1024       # our own .meta / state files
CHUNK = 64 * 1024


class Offline(Exception):
    pass


class HttpError(Exception):
    def __init__(self, status: int, url: str, detail: str | None = None):
        super().__init__(detail or f"HTTP {status} for {url}")
        self.status = status
        self.url = url


class TooLarge(HttpError):
    """The response (or its inflated form) is bigger than the plugin accepts.
    An HttpError so every caller that reports HTTP failures reports this too."""

    def __init__(self, url: str, limit: int, what: str = "response"):
        super().__init__(0, url, f"{what} larger than {limit // MIB} MiB refused: {url}")
        self.limit = limit


# -- bounded I/O helpers ---------------------------------------------------------
def _content_length(headers) -> int | None:
    try:
        n = int(headers.get("Content-Length", ""))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _pump(src, sink, limit: int, url: str, gzipped: bool) -> int:
    """Stream `src` into `sink(bytes)`; never accept more than `limit` bytes of
    input, nor produce more than `limit` bytes of output when inflating."""
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS) if gzipped else None
    total_in = total_out = 0
    while True:
        chunk = src.read(CHUNK)
        if not chunk:
            break
        total_in += len(chunk)
        if total_in > limit:
            raise TooLarge(url, limit)
        if inflater is None:
            total_out += len(chunk)
            sink(chunk)
            continue
        pending = chunk
        while pending:
            try:
                out = inflater.decompress(pending, limit - total_out + 1)
            except zlib.error as e:
                raise HttpError(0, url, f"corrupt gzip body from {url}: {e}") from e
            total_out += len(out)
            if total_out > limit:
                raise TooLarge(url, limit, "inflated response")
            sink(out)
            pending = inflater.unconsumed_tail
    if inflater is not None:
        try:
            tail = inflater.flush()
        except zlib.error as e:
            raise HttpError(0, url, f"corrupt gzip body from {url}: {e}") from e
        total_out += len(tail)
        if total_out > limit:
            raise TooLarge(url, limit, "inflated response")
        sink(tail)
    return total_out


def _open_regular(path: Path, limit: int, ttl: float | None = None):
    """Open `path` for reading only if it is a regular file (symlinks are not
    followed), at most `limit` bytes and, when `ttl` is given, younger than it.
    Returns (fd, stat) or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise OSError("not a usable cache file")
        if ttl is not None and ttl > 0 and time.time() - st.st_mtime >= ttl:
            raise OSError("expired")
    except OSError:
        os.close(fd)
        return None
    return fd, st


def read_bounded(path: Path, limit: int, ttl: float | None = None) -> bytes | None:
    """Contents of a cache file, or None when it is missing, not a regular
    file, a symlink, too big (also if it grew while being read) or expired."""
    opened = _open_regular(path, limit, ttl)
    if opened is None:
        return None
    fd, _ = opened
    try:
        with os.fdopen(fd, "rb") as f:
            data = f.read(limit + 1)
    except OSError:
        return None
    return data if len(data) <= limit else None


def _tmp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.part")


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a fresh temp file in the same directory, then rename over."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        os.unlink(tmp)  # a leftover from a crashed run with our pid
    except OSError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def safe_filename(name: str | None, fallback: str = "file") -> str:
    """Basename only: no directory parts, nothing hidden, never '.' or '..'."""
    base = os.path.basename((name or "").replace("\\", "/")).strip().lstrip(".")
    return base or fallback


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
            state = json.loads(read_bounded(self.state_file, MAX_META) or b"{}")
        except ValueError:
            state = {}
        if not isinstance(state, dict):
            state = {}
        last = float(state.get(host, 0))
        wait = last + interval - time.time()
        if wait > 0:
            time.sleep(min(wait, 5))
        state[host] = time.time()
        try:
            write_atomic(self.state_file, json.dumps(state).encode())
        except OSError:
            pass

    def _mark_online(self, ok: bool) -> None:
        try:
            write_atomic(self.dir / "online.json", json.dumps({"ok": ok, "checked_at": time.time()}).encode())
        except OSError:
            pass

    # -- raw fetch ------------------------------------------------------------
    def _request(self, url: str, etag: str | None = None, headers: dict | None = None, timeout: float | None = None,
                 limit: int | None = None, sink=None) -> tuple[int, bytes, dict]:
        """GET `url`. The body is streamed into `sink` (or collected and
        returned) and refused beyond `limit` bytes, before reading when the
        server announces its size and while reading otherwise."""
        limit = limit or MAX_BODY
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
                    announced = _content_length(resp.headers)
                    if announced is not None and announced > limit:
                        raise TooLarge(url, limit)
                    buf = bytearray()
                    _pump(resp, sink or buf.extend, limit, url, resp.headers.get("Content-Encoding", "").lower() == "gzip")
                    self._mark_online(True)
                    return resp.status, bytes(buf), dict(resp.headers)
            except urllib.error.HTTPError as e:
                code, hdrs = e.code, dict(e.headers)
                e.close()
                if code == 304:
                    return 304, b"", hdrs
                if code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                self._mark_online(True)
                raise HttpError(code, url) from e
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

    def _read_meta(self, meta_p: Path) -> dict | None:
        raw = read_bounded(meta_p, MAX_META)
        if raw is None:
            return None
        try:
            meta = json.loads(raw)
        except ValueError:
            return None
        return meta if isinstance(meta, dict) else None

    def get_bytes(self, url: str, ttl: float = 3600, headers: dict | None = None, timeout: float | None = None,
                  limit: int | None = None) -> bytes:
        limit = limit or MAX_BODY
        body_p, meta_p = self._cache_paths(url)
        meta = self._read_meta(meta_p)
        cached = read_bounded(body_p, limit)  # None when missing, symlinked, wrong type or oversized
        if meta is None or cached is None:
            meta, cached = None, None
        if cached is not None and ttl > 0 and time.time() - meta.get("fetched_at", 0) < ttl:
            return cached
        try:
            status, data, hdrs = self._request(url, etag=(meta or {}).get("etag"), headers=headers, timeout=timeout, limit=limit)
        except Offline:
            if cached is not None:
                return cached
            raise
        if status == 304:
            if cached is not None:
                write_atomic(meta_p, json.dumps({**meta, "fetched_at": time.time()}).encode())
                return cached
            # the ETag was stale (no usable body behind it): fetch without it
            status, data, hdrs = self._request(url, headers=headers, timeout=timeout, limit=limit)
        write_atomic(body_p, data)
        write_atomic(meta_p, json.dumps({"url": url, "fetched_at": time.time(), "etag": hdrs.get("ETag") or hdrs.get("etag"),
                                         "status": status, "content_type": hdrs.get("Content-Type", "")}).encode())
        return data

    def get_json(self, url: str, ttl: float = 3600, headers: dict | None = None):
        data = self.get_bytes(url, ttl=ttl, headers={"Accept": "application/json", **(headers or {})})
        return json.loads(data.decode("utf-8", "replace"))

    def get_text(self, url: str, ttl: float = 3600, encoding: str = "utf-8", timeout: float | None = None) -> str:
        return self.get_bytes(url, ttl=ttl, timeout=timeout).decode(encoding, "replace")

    def download(self, url: str, filename: str | None = None, ttl: float = 30 * 86400, limit: int | None = None) -> Path:
        """Fetch a (large) file into the files cache, streamed to disk with a
        size cap; returns its path. ttl <= 0 keeps a cached copy forever."""
        limit = limit or MAX_DOWNLOAD
        h = hashlib.sha1(url.encode()).hexdigest()
        d = self.files_dir / h
        d.mkdir(parents=True, exist_ok=True)
        p = d / safe_filename(filename or urllib.parse.unquote(url.rsplit("/", 1)[-1]))
        opened = _open_regular(p, limit, ttl if ttl > 0 else None)
        if opened is not None:
            os.close(opened[0])
            return p
        tmp = _tmp_path(p)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        try:
            with os.fdopen(fd, "wb") as f:
                self._request(url, limit=limit, sink=f.write)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return p

    def ping(self, url: str) -> tuple[bool, str]:
        try:
            self._request(url, timeout=5, limit=256 * 1024)
            return True, "reachable"
        except TooLarge:
            return True, "reachable"
        except HttpError as e:
            return e.status < 500, f"HTTP {e.status}"
        except Offline as e:
            return False, str(e)
