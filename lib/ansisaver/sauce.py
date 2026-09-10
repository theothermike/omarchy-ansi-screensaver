"""SAUCE metadata record parsing (http://www.acid.org/info/sauce/sauce.htm)."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

_RECORD = struct.Struct("<5s2s35s20s20s8sLBBHHHHBB22s")
_MAGIC = b"SAUCE00"
_COMNT = b"COMNT"
_SUB = b"\x1a"


def _s(raw: bytes) -> str:
    return raw.decode("cp437", "replace").rstrip(" \x00")


@dataclass
class Sauce:
    title: str = ""
    author: str = ""
    group: str = ""
    date: str = ""
    filesize: int = 0
    datatype: int = 0
    filetype: int = 0
    tinfo1: int = 0
    tinfo2: int = 0
    tinfo3: int = 0
    tinfo4: int = 0
    tflags: int = 0
    tinfos: str = ""
    comments: list[str] = field(default_factory=list)

    @property
    def ice(self) -> bool:
        return self.datatype == 1 and bool(self.tflags & 1)

    @property
    def letter_spacing(self) -> str | None:
        return {0: None, 1: "8px", 2: "9px"}.get((self.tflags >> 1) & 3)

    @property
    def aspect(self) -> str | None:
        return {0: None, 1: "stretch", 2: "square"}.get((self.tflags >> 3) & 3)

    @property
    def year(self) -> int | None:
        try:
            y = int(self.date[:4])
            return y if 1980 <= y <= 2100 else None
        except ValueError:
            return None

    @property
    def is_character(self) -> bool:
        return self.datatype == 1

    @property
    def is_ansimation(self) -> bool:
        return self.datatype == 1 and self.filetype == 2

    @property
    def is_amiga(self) -> bool:
        s = self.tinfos.lower()
        return any(k in s for k in ("amiga", "topaz", "microknight", "mosoul", "p0t-noodle", "potnoodle"))

    @property
    def columns(self) -> int | None:
        if self.datatype == 1 and 1 <= self.tinfo1 <= 1000:
            return self.tinfo1
        return None

    def as_dict(self) -> dict:
        return {
            "title": self.title, "author": self.author, "group": self.group, "date": self.date,
            "filesize": self.filesize, "datatype": self.datatype, "filetype": self.filetype,
            "tinfo1": self.tinfo1, "tinfo2": self.tinfo2, "tinfo3": self.tinfo3, "tinfo4": self.tinfo4,
            "tflags": self.tflags, "tinfos": self.tinfos, "comments": list(self.comments),
        }


def parse(data: bytes) -> tuple[bytes, Sauce | None]:
    """Split raw file bytes into (body, sauce). The body has the SAUCE block and
    one trailing SUB (EOF marker) removed."""
    if len(data) < 128 or data[-128:-121] != _MAGIC:
        return data, None
    rec = data[-128:]
    (_, _ver, title, author, group, date, filesize, datatype, filetype,
     t1, t2, t3, t4, ncomments, tflags, tinfos) = _RECORD.unpack(rec)
    sauce = Sauce(
        title=_s(title), author=_s(author), group=_s(group), date=_s(date),
        filesize=filesize, datatype=datatype, filetype=filetype,
        tinfo1=t1, tinfo2=t2, tinfo3=t3, tinfo4=t4, tflags=tflags, tinfos=_s(tinfos),
    )
    end = len(data) - 128
    if ncomments:
        cstart = end - (5 + 64 * ncomments)
        if cstart >= 0 and data[cstart:cstart + 5] == _COMNT:
            block = data[cstart + 5:end]
            sauce.comments = [_s(block[i:i + 64]) for i in range(0, len(block), 64)]
            end = cstart
    body = data[:end]
    if body.endswith(_SUB):
        body = body[:-1]
    return body, sauce
