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


MAX_MEMBER = 16 * 1024 * 1024  # a single text-art file; anything bigger is not art


def read_zip_member(z: zipfile.ZipFile, member: str, limit: int | None = None) -> bytes:
    """One member, refused when its declared or actual size exceeds `limit`
    (archives from the network can lie about sizes or be zip bombs)."""
    limit = limit or MAX_MEMBER
    info = z.getinfo(member)
    if info.file_size > limit:
        raise SourceError(f"{member}: {info.file_size // 1024} KB exceeds the {limit // (1024 * 1024)} MiB member limit")
    with z.open(info) as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise SourceError(f"{member}: exceeds the {limit // (1024 * 1024)} MiB member limit")
    return data


def read_bounded_file(path: Path, limit: int | None = None) -> bytes:
    limit = limit or MAX_MEMBER
    p = Path(path)
    if p.stat().st_size > limit:
        raise SourceError(f"{p.name}: exceeds the {limit // (1024 * 1024)} MiB limit")
    with open(p, "rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise SourceError(f"{p.name}: exceeds the {limit // (1024 * 1024)} MiB limit")
    return data


def read_member(path: Path, member: str, limit: int | None = None) -> bytes:
    limit = limit or MAX_MEMBER
    p = Path(path)
    if p.suffix.lower() == ".zip" or zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            return read_zip_member(z, member, limit)
    for name, size in list_members(p):
        if name == member and size > limit:
            raise SourceError(f"{member}: {size // 1024} KB exceeds the {limit // (1024 * 1024)} MiB member limit")
    proc = subprocess.Popen([_bsdtar(), "-xOf", str(p), member], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        data = proc.stdout.read(limit + 1)
        if len(data) > limit:
            proc.kill()
            raise SourceError(f"{member}: exceeds the {limit // (1024 * 1024)} MiB member limit")
        err = proc.stderr.read(4096)
        rc = proc.wait(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise SourceError(f"timed out extracting {member} from {p.name}")
    finally:
        proc.stdout.close()
        proc.stderr.close()
    if rc != 0:
        raise SourceError(f"cannot extract {member} from {p.name}: {err.decode(errors='replace').strip()[:120]}")
    return data


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
