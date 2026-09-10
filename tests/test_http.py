"""Network-input limits of the HTTP client and archive readers (stdlib unittest).
Run: python3 -B -m unittest discover -s tests"""
from __future__ import annotations

import gzip
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.dont_write_bytecode = True

from ansisaver import paths  # noqa: E402
from ansisaver.sources import archives, http  # noqa: E402
from ansisaver.sources.base import SourceError  # noqa: E402

LIMIT = 64 * 1024  # small caps keep the tests fast; production values are in http.py
HITS: dict[str, int] = {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence
        pass

    def _send(self, body: bytes, status=200, headers=None, length=True):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if length:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        HITS[self.path] = HITS.get(self.path, 0) + 1
        if self.path == "/ok":
            if self.headers.get("If-None-Match") == '"v1"':
                self.send_response(304)
                self.send_header("ETag", '"v1"')
                self.end_headers()
                return
            self._send(b"hello world", headers={"ETag": '"v1"', "Content-Type": "text/plain"})
        elif self.path == "/ok-gzip":
            self._send(gzip.compress(b"inflated fine"), headers={"Content-Encoding": "gzip"})
        elif self.path == "/announced-too-big":
            # says it is huge, sends little: must be refused on the header alone
            self.send_response(200)
            self.send_header("Content-Length", str(LIMIT + 1))
            self.end_headers()
            try:
                self.wfile.write(b"x" * 10)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
        elif self.path == "/unannounced-too-big":
            # no Content-Length: only streaming with a cap can stop this
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(b"y" * (LIMIT + 1))
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
        elif self.path == "/gzip-bomb":
            # a few hundred bytes on the wire, 4x the cap once inflated
            self._send(gzip.compress(b"\0" * (LIMIT * 4)), headers={"Content-Encoding": "gzip"})
        elif self.path == "/file.zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("art/piece.ans", b"\x1b[31mhi\x1b[0m")
                z.writestr("art/bomb.ans", b"\0" * (LIMIT + 1))
            self._send(buf.getvalue(), headers={"Content-Type": "application/zip"})
        else:
            self._send(b"not found", status=404)


class HttpLimitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.tmp = Path(tempfile.mkdtemp(prefix="ansisaver-http-"))
        cls.saved = (paths.SOURCES_CACHE, http.MAX_BODY, http.MAX_DOWNLOAD, archives.MAX_MEMBER, dict(http.HOST_INTERVAL))
        paths.SOURCES_CACHE = cls.tmp
        http.MAX_BODY = http.MAX_DOWNLOAD = archives.MAX_MEMBER = LIMIT
        http.HOST_INTERVAL["127.0.0.1"] = 0

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        paths.SOURCES_CACHE, http.MAX_BODY, http.MAX_DOWNLOAD, archives.MAX_MEMBER, hosts = cls.saved
        http.HOST_INTERVAL.clear()
        http.HOST_INTERVAL.update(hosts)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        HITS.clear()
        self.client = http.HttpClient("test")
        shutil.rmtree(self.client.dir, ignore_errors=True)

    def url(self, path):
        return self.base + path

    # -- response caps --------------------------------------------------------
    def test_announced_size_refused_before_reading(self):
        with self.assertRaises(http.TooLarge):
            self.client.get_bytes(self.url("/announced-too-big"))
        self.assertEqual(list(self.client.http_dir.glob("*")), [], "nothing may be cached for a refused response")

    def test_streamed_size_refused_without_content_length(self):
        with self.assertRaises(http.TooLarge):
            self.client.get_bytes(self.url("/unannounced-too-big"))
        self.assertEqual(list(self.client.http_dir.glob("*")), [])

    def test_gzip_bomb_refused_by_inflated_ceiling(self):
        with self.assertRaises(http.TooLarge) as cm:
            self.client.get_bytes(self.url("/gzip-bomb"))
        self.assertIn("inflated", str(cm.exception))

    def test_gzip_body_inflates(self):
        self.assertEqual(self.client.get_bytes(self.url("/ok-gzip")), b"inflated fine")

    # -- cache handling -----------------------------------------------------------
    def test_cache_hit_and_etag_revalidation(self):
        self.assertEqual(self.client.get_bytes(self.url("/ok")), b"hello world")
        self.assertEqual(self.client.get_bytes(self.url("/ok"), ttl=3600), b"hello world")
        self.assertEqual(HITS["/ok"], 1, "fresh cache must not hit the network")
        self.assertEqual(self.client.get_bytes(self.url("/ok"), ttl=0), b"hello world")
        self.assertEqual(HITS["/ok"], 2, "ttl=0 revalidates with the ETag (304)")
        body_p, meta_p = self.client._cache_paths(self.url("/ok"))
        self.assertTrue(body_p.is_file() and meta_p.is_file())
        self.assertEqual([p for p in self.client.http_dir.iterdir() if p.name.endswith(".part")], [], "no temp files left")

    def test_symlinked_cache_body_is_ignored(self):
        self.client.get_bytes(self.url("/ok"))
        body_p, _ = self.client._cache_paths(self.url("/ok"))
        secret = self.tmp / "secret.txt"
        secret.write_bytes(b"not the cached body")
        body_p.unlink()
        body_p.symlink_to(secret)
        self.assertEqual(self.client.get_bytes(self.url("/ok"), ttl=3600), b"hello world")
        self.assertEqual(HITS["/ok"], 2, "a symlinked cache file must be refetched, not followed")
        self.assertFalse(body_p.is_symlink(), "the refetch replaces the symlink atomically")
        self.assertEqual(secret.read_bytes(), b"not the cached body", "the symlink target must be untouched")

    def test_oversized_cache_body_is_ignored(self):
        self.client.get_bytes(self.url("/ok"))
        body_p, _ = self.client._cache_paths(self.url("/ok"))
        body_p.write_bytes(b"z" * (LIMIT + 1))
        self.assertEqual(self.client.get_bytes(self.url("/ok"), ttl=3600), b"hello world")
        self.assertEqual(HITS["/ok"], 2)

    def test_stale_etag_without_body_refetches(self):
        self.client.get_bytes(self.url("/ok"))
        body_p, _ = self.client._cache_paths(self.url("/ok"))
        body_p.unlink()  # meta (with ETag) survives, body does not
        self.assertEqual(self.client.get_bytes(self.url("/ok"), ttl=0), b"hello world")
        self.assertTrue(body_p.is_file())

    # -- downloads ---------------------------------------------------------------
    def test_download_streams_to_disk_atomically(self):
        p = self.client.download(self.url("/file.zip"))
        self.assertTrue(p.is_file() and not p.is_symlink())
        self.assertEqual(p.name, "file.zip")
        self.assertEqual([q for q in p.parent.iterdir() if q.name.endswith(".part")], [])
        self.client.download(self.url("/file.zip"))
        self.assertEqual(HITS["/file.zip"], 1, "cached download is reused")

    def test_download_refuses_oversized_and_leaves_no_partial(self):
        with self.assertRaises(http.TooLarge):
            self.client.download(self.url("/unannounced-too-big"), filename="big.bin")
        leftovers = list(self.client.files_dir.rglob("*")) if self.client.files_dir.exists() else []
        self.assertEqual([q for q in leftovers if q.is_file()], [], "no partial download may remain")

    def test_download_filename_is_a_basename(self):
        p = self.client.download(self.url("/file.zip"), filename="../../escape.zip")
        self.assertEqual(p.name, "escape.zip")
        self.assertEqual(p.parent.parent, self.client.files_dir)
        self.assertEqual(http.safe_filename("..", "file"), "file")
        self.assertEqual(http.safe_filename("/etc/passwd"), "passwd")
        self.assertEqual(http.safe_filename(".hidden"), "hidden")

    # -- archive members -----------------------------------------------------------
    def test_zip_member_cap(self):
        p = self.client.download(self.url("/file.zip"))
        self.assertEqual(archives.read_member(p, "art/piece.ans"), b"\x1b[31mhi\x1b[0m")
        with self.assertRaises(SourceError):
            archives.read_member(p, "art/bomb.ans")
        with zipfile.ZipFile(p) as z:
            with self.assertRaises(SourceError):
                archives.read_zip_member(z, "art/bomb.ans")

    def test_bounded_file_reader(self):
        small = self.tmp / "small.ans"
        small.write_bytes(b"ok")
        self.assertEqual(archives.read_bounded_file(small), b"ok")
        big = self.tmp / "big.ans"
        big.write_bytes(b"\0" * (LIMIT + 1))
        with self.assertRaises(SourceError):
            archives.read_bounded_file(big)


if __name__ == "__main__":
    unittest.main()
