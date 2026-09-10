"""Archive members: zip via the stdlib, everything else (lha/lzh/arj/rar/7z…)
through bsdtar (libarchive), which Omarchy ships."""
from __future__ import annotations

import os
import posixpath
import selectors
import shutil
import struct
import subprocess
import time
import zipfile
from pathlib import Path

from .base import SourceError, is_art_name

ARCHIVE_EXTS = (".zip", ".lha", ".lzh", ".arj", ".rar", ".7z", ".tar", ".tgz", ".tar.gz")

# Archives come from the network and are not trusted. Everything read out of
# one is capped: the member count and central-directory size of a zip before
# it is parsed, the output of bsdtar (both streams, under one deadline) and
# the bytes of any single member.
MAX_MEMBER = 16 * 1024 * 1024      # a single text-art file; anything bigger is not art
MAX_MEMBERS = 20000                # entries in one archive
MAX_DIRECTORY = 8 * 1024 * 1024    # a zip's central directory
MAX_LISTING = 4 * 1024 * 1024      # bsdtar -tv output
MAX_STDERR = 64 * 1024
LIST_DEADLINE = 60.0               # seconds, end to end
EXTRACT_DEADLINE = 120.0


def is_archive_name(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_EXTS)


def _bsdtar() -> str:
    exe = shutil.which("bsdtar")
    if not exe:
        raise SourceError("bsdtar (libarchive) is needed to open this archive")
    return exe


def _run_bounded(argv: list[str], *, stdout_limit: int, stderr_limit: int, deadline: float, what: str) -> tuple[int, bytes, bytes]:
    """Run `argv` with both pipes drained together, each capped, under one
    end-to-end deadline. The child is killed and reaped on any overflow or
    timeout, so a member listing that never ends or a child stuck on a full
    stderr pipe cannot hang or fill memory."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out_buf, err_buf = bytearray(), bytearray()
    bufs = {proc.stdout.fileno(): out_buf, proc.stderr.fileno(): err_buf}
    limits = {proc.stdout.fileno(): stdout_limit, proc.stderr.fileno(): stderr_limit}
    names = {proc.stdout.fileno(): "output", proc.stderr.fileno(): "error output"}
    started = time.monotonic()

    def abort(msg: str) -> SourceError:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return SourceError(msg)

    sel = selectors.DefaultSelector()
    try:
        for fd in bufs:
            os.set_blocking(fd, False)
            sel.register(fd, selectors.EVENT_READ)
        while sel.get_map():
            left = deadline - (time.monotonic() - started)
            if left <= 0:
                raise abort(f"{what}: timed out after {int(deadline)}s")
            for key, _ in sel.select(timeout=min(left, 1.0)):
                fd = key.fd
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    sel.unregister(fd)
                    continue
                bufs[fd] += chunk
                if len(bufs[fd]) > limits[fd]:
                    raise abort(f"{what}: {names[fd]} exceeds {limits[fd] // 1024} KB")
        left = deadline - (time.monotonic() - started)
        try:
            rc = proc.wait(timeout=max(0.0, left))
        except subprocess.TimeoutExpired:
            raise abort(f"{what}: timed out after {int(deadline)}s")
    finally:
        sel.close()
        proc.stdout.close()
        proc.stderr.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return rc, bytes(out_buf), bytes(err_buf)


def _zip_directory(path: Path) -> tuple[int, int]:
    """(entry count, central-directory size) from a zip's end record, read
    before the stdlib parses the whole directory into memory. ZIP64 aware."""
    size = os.path.getsize(path)
    if size < 22:
        raise SourceError(f"{Path(path).name}: not a zip file")
    with open(path, "rb") as f:
        tail = min(size, 65535 + 22)
        f.seek(size - tail)
        buf = f.read(tail)
        i = buf.rfind(b"PK\x05\x06")
        if i < 0:
            raise SourceError(f"{Path(path).name}: not a zip file")
        entries, cd_size = struct.unpack_from("<HI", buf, i + 10)
        if entries == 0xFFFF or cd_size == 0xFFFFFFFF:
            j = buf.rfind(b"PK\x06\x07", 0, i)          # zip64 end-record locator
            if j >= 0:
                (rec_off,) = struct.unpack_from("<Q", buf, j + 8)
                if 0 <= rec_off < size:
                    f.seek(rec_off)
                    rec = f.read(56)
                    if rec[:4] == b"PK\x06\x06" and len(rec) >= 48:
                        entries, cd_size = struct.unpack_from("<QQ", rec, 32)
    return entries, cd_size


def open_zip(path: Path) -> zipfile.ZipFile:
    """ZipFile for an untrusted archive: the directory is size-checked first."""
    entries, cd_size = _zip_directory(path)
    if entries > MAX_MEMBERS:
        raise SourceError(f"{Path(path).name}: {entries} entries exceed the {MAX_MEMBERS} member limit")
    if cd_size > MAX_DIRECTORY:
        raise SourceError(f"{Path(path).name}: zip directory of {cd_size // 1024} KB exceeds the {MAX_DIRECTORY // (1024 * 1024)} MiB limit")
    return zipfile.ZipFile(path)


def _is_zip(p: Path) -> bool:
    return p.suffix.lower() == ".zip" or zipfile.is_zipfile(p)


def list_members(path: Path) -> list[tuple[str, int]]:
    """[(member name, size)] of a supported archive."""
    p = Path(path)
    if _is_zip(p):
        with open_zip(p) as z:
            return [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
    rc, out, err = _run_bounded([_bsdtar(), "-tvf", str(p)], stdout_limit=MAX_LISTING, stderr_limit=MAX_STDERR,
                                deadline=LIST_DEADLINE, what=f"listing {p.name}")
    if rc != 0:
        raise SourceError(f"cannot list {p.name}: {err.decode(errors='replace').strip()[:120]}")
    members = []
    for line in out.decode("utf-8", "replace").splitlines():
        # bsdtar -tv: "-rw-r--r--  0 0      0        1234 Jan  1  1996 NAME"
        parts = line.split(None, 8)
        if len(parts) >= 9 and not line.startswith("d"):
            try:
                size = int(parts[4])
            except ValueError:
                size = 0
            members.append((parts[8], size))
            if len(members) > MAX_MEMBERS:
                raise SourceError(f"{p.name}: more than {MAX_MEMBERS} members")
    return members


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
    if _is_zip(p):
        with open_zip(p) as z:
            return read_zip_member(z, member, limit)
    for name, size in list_members(p):
        if name == member and size > limit:
            raise SourceError(f"{member}: {size // 1024} KB exceeds the {limit // (1024 * 1024)} MiB member limit")
    rc, data, err = _run_bounded([_bsdtar(), "-xOf", str(p), member], stdout_limit=limit, stderr_limit=MAX_STDERR,
                                 deadline=EXTRACT_DEADLINE, what=f"extracting {member} from {p.name}")
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
