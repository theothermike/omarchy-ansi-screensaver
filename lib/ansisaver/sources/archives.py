"""Archive members: zip via the stdlib, everything else (lha/lzh/arj/rar/7z…)
through bsdtar (libarchive), which Omarchy ships."""
from __future__ import annotations

import posixpath
import shutil
import subprocess
import zipfile
from pathlib import Path

from .base import SourceError, is_art_name

ARCHIVE_EXTS = (".zip", ".lha", ".lzh", ".arj", ".rar", ".7z", ".tar", ".tgz", ".tar.gz")


def is_archive_name(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_EXTS)


def _bsdtar() -> str:
    exe = shutil.which("bsdtar")
    if not exe:
        raise SourceError("bsdtar (libarchive) is needed to open this archive")
    return exe


def list_members(path: Path) -> list[tuple[str, int]]:
    """[(member name, size)] of a supported archive."""
    p = Path(path)
    if p.suffix.lower() == ".zip" or zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            return [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
    r = subprocess.run([_bsdtar(), "-tvf", str(p)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise SourceError(f"cannot list {p.name}: {r.stderr.strip()[:120]}")
    out = []
    for line in r.stdout.splitlines():
        # bsdtar -tv: "-rw-r--r--  0 0      0        1234 Jan  1  1996 NAME"
        parts = line.split(None, 8)
        if len(parts) >= 9 and not line.startswith("d"):
            try:
                size = int(parts[4])
            except ValueError:
                size = 0
            out.append((parts[8], size))
    return out


def read_member(path: Path, member: str) -> bytes:
    p = Path(path)
    if p.suffix.lower() == ".zip" or zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            return z.read(member)
    r = subprocess.run([_bsdtar(), "-xOf", str(p), member], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise SourceError(f"cannot extract {member} from {p.name}: {r.stderr.decode(errors='replace').strip()[:120]}")
    return r.stdout


def art_members(path: Path) -> list[tuple[str, int]]:
    return [(m, s) for m, s in list_members(path)
            if is_art_name(posixpath.basename(m)) and "__MACOSX" not in m and not posixpath.basename(m).lower().startswith("file_id")]


def find_member(path: Path, name: str) -> str | None:
    """Case-insensitive basename match."""
    low = name.lower()
    for m, _ in list_members(path):
        if posixpath.basename(m).lower() == low:
            return m
    return None
