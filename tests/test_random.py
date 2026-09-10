"""Random import stop conditions (stdlib unittest). Run: python3 -B -m unittest discover -s tests"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.dont_write_bytecode = True

from ansisaver import paths  # noqa: E402
from ansisaver.sources import cli as scli  # noqa: E402
from ansisaver.sources.base import Entry, SourceError  # noqa: E402
from ansisaver.sources.http import Offline  # noqa: E402


class FakeSource:
    """Yields item-1, item-2, … ; `created_until` says how many are new to the library."""

    def __init__(self, sid, created_until=10**9, offline=False, empty=False):
        self.id = self.label = sid
        self.created_until = created_until
        self.offline = offline
        self.empty = empty
        self.n = 0

    def random_items(self, n, rng, top=False):
        if self.offline:
            raise Offline(f"{self.id} down")
        if self.empty:
            return []
        self.n += 1
        return [Entry("item", f"item-{self.n}", f"item {self.n}", "")]

    def fetch(self, entry_id):
        return SimpleNamespace(id=entry_id, data=b"art")


class RandomImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ansisaver-random-"))
        self.saved = (paths.SOURCES_CACHE, scli._pick_sources, scli.import_fetched, scli.C.load)
        paths.SOURCES_CACHE = self.tmp
        scli.C.load = lambda: {}
        scli.import_fetched = self.fake_import

    def tearDown(self):
        paths.SOURCES_CACHE, scli._pick_sources, scli.import_fetched, scli.C.load = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def fake_import(src, entry_id, fetched, args, tags=None):
        n = int(entry_id.split("-")[1])
        return {"id": f"{src.id}-{entry_id}", "title": entry_id}, n <= src.created_until

    def run_random(self, sources, count):
        scli._pick_sources = lambda args, cfg: list(sources)
        args = SimpleNamespace(count=count, source=None, all=True, top=False, seed=7, progress=True, json=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = scli.cmd_random(args)
        lines = out.getvalue().splitlines()
        done = [l for l in lines if l.startswith("done ")]
        self.assertEqual(len(done), 1, lines[-3:])
        return rc, json.loads(done[0][5:]), lines

    def test_duplicates_do_not_end_the_run_after_four_misses(self):
        src = FakeSource("dz", created_until=5)   # 5 new pieces, then only duplicates
        rc, r, lines = self.run_random([src], 20)
        self.assertEqual(len(r["added"]), 5)
        self.assertEqual(r["requested"], 20)
        # the old code stopped after 4 misses; a single source now gets max(8, min(40, n)) = 20 in a row
        self.assertEqual(len(r["skipped"]), 20)
        self.assertIn("20 misses in a row", r["exhausted"]["dz"])
        self.assertIn("ran dry", r["stopped"])
        self.assertTrue(any(l.startswith("error stopped after 5/20") for l in lines), lines[-2])
        self.assertEqual(rc, 0)

    def test_offline_source_is_set_aside_and_the_rest_continue(self):
        rc, r, _ = self.run_random([FakeSource("down", offline=True), FakeSource("ok")], 12)
        self.assertEqual(len(r["added"]), 12)
        self.assertNotIn("stopped", r)
        self.assertIn("offline", r["exhausted"]["down"])
        self.assertEqual(rc, 0)

    def test_source_that_finds_nothing_is_set_aside(self):
        rc, r, _ = self.run_random([FakeSource("empty", empty=True)], 3)
        self.assertEqual(r["added"], [])
        self.assertIn("nothing found on this walk", r["exhausted"]["empty"])
        self.assertEqual(rc, 1)

    def test_history_prevents_repeats_across_runs(self):
        src = FakeSource("s")
        self.run_random([src], 3)
        src2 = FakeSource("s")                     # restarts at item-1: those three are in the history now
        rc, r, _ = self.run_random([src2], 2)
        self.assertEqual([a["entry"] for a in r["added"]], ["item-4", "item-5"])

    def test_oversized_pick_is_a_miss(self):
        class Big(FakeSource):
            def fetch(self, entry_id):
                return SimpleNamespace(id=entry_id, data=b"x" * (scli.RANDOM_MAX_BYTES + 1))
        rc, r, _ = self.run_random([Big("big")], 2)
        self.assertEqual(r["added"], [])
        self.assertTrue(all("too big" in f["reason"] for f in r["failed"]), r["failed"])


class NameFilterTests(unittest.TestCase):
    def test_info_text_files_are_not_art(self):
        from ansisaver.sources.base import is_art_name
        for bad in ("README.TXT", "readme.txt", "LICENSE.txt", "file_id.diz", "install.nfo", "Index.txt"):
            self.assertFalse(is_art_name(bad), bad)
        for good in ("piece.ans", "logo.asc", "readme.ans", "story.txt", "us-ncg2.ans"):
            self.assertTrue(is_art_name(good), good)


if __name__ == "__main__":
    unittest.main()
