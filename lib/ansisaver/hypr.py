"""Hyprland helpers (hyprctl, socket2 events, process discovery)."""
from __future__ import annotations

import json
import os
import signal
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
    # Only real screensaver processes: a ghostty window (--class=CLS) or our
    # runner (--window-class CLS). Matching any mention of the literal would
    # also catch an unrelated shell that merely typed the class name.
    cls = window_class.encode()
    needles = (b"--class=" + cls + b"\x00", b"--window-class\x00" + cls + b"\x00", b"--class\x00" + cls + b"\x00")
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
        if any(n in cmd for n in needles):
            out.append(pid)
    return out


def cmdline(pid: int) -> bytes:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read()
    except OSError:
        return b""


def ppid(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return 0


TERMINALS = (b"ghostty", b"alacritty", b"kitty", b"foot")
STOCK_LOOP = b"omarchy-screensaver"
STOCK_LAUNCHER = b"omarchy-launch-screensaver"


class StockProcs:
    """Omarchy's stock screensaver processes, ours excluded: `launchers` are
    `omarchy-launch-screensaver` runs (one window per monitor, in sequence),
    `loops` the `omarchy-screensaver` scripts (their exit trap `pkill`s the
    whole window class -- ours included -- so they must never get to run it),
    `windows` their terminals and `children` whatever the scripts spawned
    (ttfx, socat, sleep)."""

    def __init__(self, launchers, loops, windows, children):
        self.launchers, self.loops, self.windows, self.children = launchers, loops, windows, children

    def __bool__(self) -> bool:
        return bool(self.launchers or self.loops or self.windows or self.children)

    def __str__(self) -> str:
        return f"launchers {self.launchers} loops {self.loops} windows {self.windows} children {self.children}"

    def freeze(self) -> None:
        """Stop the scripts -- a stopped shell runs no trap and spawns no more
        windows -- and kill what they already spawned. Their windows stay up,
        so the stock idle service does not read this as a dismissal."""
        _signal(self.launchers + self.loops, signal.SIGSTOP)
        _signal(self.children, signal.SIGKILL)

    def kill(self) -> None:
        _signal(self.launchers + self.loops + self.children + self.windows, signal.SIGKILL)


def _signal(pids: list[int], sig: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def stock_screensaver_procs() -> StockProcs:
    skip = _ancestors()
    launchers, loops, windows, cmds = [], [], [], {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in skip:
            continue
        cmd = cmdline(pid)
        if not cmd:
            continue
        cmds[pid] = cmd
        argv = cmd.split(b"\0")
        # the launcher script itself, not the `bash -lc` wrapper naming it
        if any(a == STOCK_LAUNCHER or a.endswith(b"/" + STOCK_LAUNCHER) for a in argv):
            launchers.append(pid)
        elif STOCK_LOOP in cmd and b"ansi-screensaver" not in cmd:
            (windows if any(t in cmd for t in TERMINALS) else loops).append(pid)
    parents = set(launchers) | set(loops)
    children = [pid for pid in cmds if pid not in parents and ppid(pid) in parents]
    return StockProcs(sorted(launchers), sorted(loops), sorted(windows), sorted(children))
