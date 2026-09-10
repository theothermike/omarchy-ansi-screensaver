"""Bounds on untrusted archives (stdlib unittest). Run: python3 -B -m unittest discover -s tests"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.dont_write_bytecode = True

from ansisaver.sources import archives  # noqa: E402
from ansisaver.sources.base import SourceError  # noqa: E402

# A stand-in for bsdtar whose behaviour is picked by $FAKE_TAR. `exec` so the
# kill reaches the process that is actually misbehaving.
FAKE_TAR = r'''#!/bin/sh
case "$1" in
  -tvf)
    case "$FAKE_TAR" in
      flood) exec yes -- '-rw-r--r--  0 0 0 100 Jan  1  1996 name.ans' ;;
      stderr-flood) exec yes -- 'error error error error error error error' >&2 ;;
      hang) exec sleep 1000 ;;
      *) printf -- '-rw-r--r--  0 0 0 12 Jan  1  1996 piece.ans\n-rw-r--r--  0 0 0 5 Jan  1  1996 readme.txt\ndrwxr-xr-x  0 0 0 0 Jan  1  1996 dir/\n' ;;
    esac ;;
  -xOf)
    case "$FAKE_TAR" in
      big) exec head -c 200000 /dev/zero ;;
      fail) echo "damaged" >&2; exit 1 ;;
      *) printf 'hello member' ;;
    esac ;;
esac
'''


class BsdtarBoundsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ansisaver-arch-"))
        self.script = self.tmp / "fake-bsdtar"
        self.script.write_text(FAKE_TAR)
        self.script.chmod(0o755)
        self.arch = self.tmp / "pack.lha"
        self.arch.write_bytes(b"not really an archive")
        self.saved = (archives._bsdtar, archives.MAX_LISTING, archives.MAX_STDERR, archives.LIST_DEADLINE, archives.EXTRACT_DEADLINE)
        archives._bsdtar = lambda: str(self.script)
        archives.MAX_LISTING = 64 * 1024
        archives.MAX_STDERR = 16 * 1024
        archives.LIST_DEADLINE = archives.EXTRACT_DEADLINE = 1.5

    def tearDown(self):
        archives._bsdtar, archives.MAX_LISTING, archives.MAX_STDERR, archives.LIST_DEADLINE, archives.EXTRACT_DEADLINE = self.saved
        os.environ.pop("FAKE_TAR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mode(self, m):
        os.environ["FAKE_TAR"] = m

    def assertNoChild(self):
        time.sleep(0.2)
        r = subprocess.run(["pgrep", "-f", "^yes -- -rw-r--r--|^sleep 1000$|^yes -- error error"], capture_output=True)
        self.assertEqual(r.returncode, 1, "the bsdtar child must be dead after an abort")

    def test_listing_parses(self):
        self.mode("ok")
        self.assertEqual(archives.list_members(self.arch), [("piece.ans", 12), ("readme.txt", 5)])

    def test_endless_listing_is_cut_off(self):
        self.mode("flood")
        t0 = time.monotonic()
        with self.assertRaises(SourceError) as cm:
            archives.list_members(self.arch)
        self.assertIn("output exceeds", str(cm.exception))
        self.assertLess(time.monotonic() - t0, 5)
        self.assertNoChild()

    def test_stderr_flood_does_not_hang(self):
        self.mode("stderr-flood")
        t0 = time.monotonic()
        with self.assertRaises(SourceError) as cm:
            archives.list_members(self.arch)
        self.assertIn("error output exceeds", str(cm.exception))
        self.assertLess(time.monotonic() - t0, 5)
        self.assertNoChild()

    def test_silent_child_hits_the_deadline(self):
        self.mode("hang")
        t0 = time.monotonic()
        with self.assertRaises(SourceError) as cm:
            archives.list_members(self.arch)
        self.assertIn("timed out", str(cm.exception))
        self.assertLess(time.monotonic() - t0, 5)
        self.assertNoChild()

    def test_member_extraction_is_capped(self):
        self.mode("ok")
        self.assertEqual(archives.read_member(self.arch, "piece.ans"), b"hello member")
        self.mode("big")
        with self.assertRaises(SourceError):
            archives.read_member(self.arch, "piece.ans", limit=100_000)
        self.mode("fail")
        with self.assertRaises(SourceError) as cm:
            archives.read_member(self.arch, "piece.ans")
        self.assertIn("damaged", str(cm.exception))


class ZipDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ansisaver-zip-"))
        self.saved = archives.MAX_MEMBERS
        archives.MAX_MEMBERS = 50

    def tearDown(self):
        archives.MAX_MEMBERS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, n):
        p = self.tmp / f"{n}.zip"
        with zipfile.ZipFile(p, "w") as z:
            for i in range(n):
                z.writestr(f"art/{i}.ans", b"x")
        return p

    def test_entry_count_is_read_from_the_end_record(self):
        p = self.make(50)
        entries, cd_size = archives._zip_directory(p)
        self.assertEqual(entries, 50)
        self.assertGreater(cd_size, 0)
        with archives.open_zip(p) as z:
            self.assertEqual(len(z.namelist()), 50)
        self.assertEqual(len(archives.list_members(p)), 50)

    def test_too_many_entries_are_refused_before_parsing(self):
        p = self.make(51)
        with self.assertRaises(SourceError) as cm:
            archives.open_zip(p)
        self.assertIn("51 entries", str(cm.exception))
        with self.assertRaises(SourceError):
            archives.list_members(p)

    def test_not_a_zip(self):
        p = self.tmp / "junk.zip"
        p.write_bytes(b"PK\x03\x04 but no directory at all, just bytes " * 4)
        with self.assertRaises(SourceError):
            archives.open_zip(p)


if __name__ == "__main__":
    unittest.main()
