"""Hyprland helpers (hyprctl, socket2 events, process discovery)."""
from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import time
from pathlib import Path


def hyprctl(*args: str, timeout: float = 3.0) -> subprocess.CompletedProcess:
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=timeout)


def hyprctl_json(*args: str):
    r = hyprctl(*args, "-j")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"hyprctl {' '.join(args)} failed")
    return json.loads(r.stdout)


def available() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


def monitors() -> list[dict]:
    return hyprctl_json("monitors")


def focused_monitor() -> str | None:
    for m in monitors():
        if m.get("focused"):
            return m["name"]
    return None


def focus_monitor(name: str) -> None:
    r = hyprctl("dispatch", f'hl.dsp.focus({{ monitor = "{name}" }})')
    if r.returncode != 0 or "ok" not in r.stdout.lower():
        hyprctl("dispatch", "focusmonitor", name)


def exec_cmd(argv: list[str]) -> None:
    cmd = shlex.join(argv)
    if "]]" not in cmd:
        r = hyprctl("dispatch", f"hl.dsp.exec_cmd([[{cmd}]])")
        if r.returncode == 0 and "ok" in r.stdout.lower():
            return
    hyprctl("dispatch", "exec", "--", "bash", "-lc", cmd)


def active_window_class() -> str | None:
    try:
        return hyprctl_json("activewindow").get("class")
    except Exception:  # noqa: BLE001
        return None


def cursor_invisible(flag: bool) -> None:
    v = "true" if flag else "false"
    r = hyprctl("eval", f"hl.config({{ cursor = {{ invisible = {v} }} }})")
    if r.returncode != 0:
        hyprctl("keyword", "cursor:invisible", v)


def add_fullscreen_rule(window_class: str) -> bool:
    r = hyprctl("eval", f'hl.window_rule({{ match = {{ class = "{window_class}" }}, fullscreen = true, float = true }})')
    return r.returncode == 0 and "error" not in r.stdout.lower()


def socket2_path() -> Path | None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    run = os.environ.get("XDG_RUNTIME_DIR")
    if not sig or not run:
        return None
    p = Path(run) / "hypr" / sig / ".socket2.sock"
    return p if p.exists() else None


class Events:
    """Hyprland event stream (socket2). Open BEFORE spawning windows."""

    def __init__(self):
        self.sock: socket.socket | None = None
        self.buf = b""
        p = socket2_path()
        if p is not None:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(str(p))
                s.setblocking(False)
                self.sock = s
            except OSError:
                self.sock = None

    def wait_for_open(self, window_class: str, timeout: float = 5.0) -> str | None:
        """Block until an openwindow event for window_class; return its address."""
        if self.sock is None:
            time.sleep(min(timeout, 0.5))
            return None
        import select
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            r, _, _ = select.select([self.sock], [], [], remaining)
            if not r:
                return None
            try:
                chunk = self.sock.recv(65536)
            except BlockingIOError:
                continue
            if not chunk:
                return None
            self.buf += chunk
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                text = line.decode("utf-8", "replace")
                if text.startswith("openwindow>>"):
                    parts = text[len("openwindow>>"):].split(",")
                    if len(parts) >= 3 and parts[2] == window_class:
                        return parts[0]

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def _ancestors() -> set[int]:
    out = set()
    pid = os.getpid()
    while pid > 1:
        out.add(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                fields = f.read().rsplit(")", 1)[1].split()
            pid = int(fields[1])
        except (OSError, IndexError, ValueError):
            break
    return out


def class_pids(window_class: str, exclude_self: bool = True) -> list[int]:
    """PIDs whose command line contains the window class literal."""
    needle = window_class.encode()
    skip = _ancestors() if exclude_self else set()
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in skip:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read()
        except OSError:
            continue
        if needle in cmd:
            out.append(pid)
    return out
