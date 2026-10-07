"""PLATFORM_COMPAT_v1 (docs/plans/platform-portability.md pp/D): the one place for calls that differ by OS.

Layers call these instead of fcntl, /proc and friends; each function holds its POSIX and Windows sides, and
test_ratchets' `posix` ratchet skips this file only. It is a core module (core_modules.json, PP5): standard
library only, so the self-evolution core may use it too.

- lock_file / unlock_file: an exclusive lock on an open file -- flock on POSIX, msvcrt.locking on Windows (the first
  byte; a lock beyond the end of the file is allowed). Where neither exists the lock is skipped (fail open: a lock
  here is a safeguard, never a reason the host cannot run).
- has_proc: whether a Linux-style /proc is there; code that reads it degrades instead of crashing without it.
- write_text: Path.write_text with \n line endings everywhere. Python 3.8 (the NAS) has no newline= there, and on
  Windows text mode writes \r\n -- a 2048-byte card budget failed at 2088 (#405).
- http_server: a ThreadingHTTPServer that owns its port. On Windows SO_REUSEADDR (which http.server turns on) lets a
  second socket bind a port already bound -- another program could listen beside the host, and a test's new server
  could get a port whose old server was still closing, so requests hit a dead socket (WinError 10054, #409). There
  it binds with SO_EXCLUSIVEADDRUSE instead; POSIX keeps SO_REUSEADDR (restart after TIME_WAIT).
- named_file: the first of several names that exists in a folder, spelled as it is on disk. Windows and macOS file
  systems ignore case, so `(d / "ROLE.md").is_file()` is true for role.md there and the caller would show a name
  that is not on disk (FIREBAT 2026-09-29, #405).
- parent_pid / tcp_socket_pid: walk a process's ancestry, and find which of some processes holds a loopback TCP
  socket -- how the hosts tell which agent process called them (inbox/0). Without /proc both answer None.
"""
from __future__ import annotations

import os
import time

try:  # POSIX
    import fcntl
except ImportError:
    fcntl = None
try:  # Windows
    import msvcrt
except ImportError:
    msvcrt = None

WINDOWS_LOCK_POLL_SEC = 0.05


def lock_file(fh, blocking: bool = True) -> bool:
    """Take an exclusive lock on the open file `fh`. True when held (or when this OS has no locking); False when
    `blocking` is off and another holder has it."""
    if fcntl is not None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            return True
        except OSError:
            return False
    if msvcrt is not None:
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                if not blocking:
                    return False
                time.sleep(WINDOWS_LOCK_POLL_SEC)
    return True


def unlock_file(fh) -> None:
    """Release a lock taken with lock_file (closing the file releases it too)."""
    if fcntl is not None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
    elif msvcrt is not None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


def write_text(path, text: str, encoding: str = "utf-8", errors=None) -> int:
    """Write `text` to `path` with \n line endings on every OS; returns the characters written."""
    with open(str(path), "w", encoding=encoding, errors=errors, newline="\n") as fh:
        return fh.write(text)


_HTTP_SERVER = None


def http_server(address, handler):
    """ThreadingHTTPServer(address, handler), bound exclusively on Windows. http.server is imported on first use."""
    global _HTTP_SERVER
    if _HTTP_SERVER is None:
        import socket
        from http.server import ThreadingHTTPServer

        class ExclusiveHTTPServer(ThreadingHTTPServer):
            allow_reuse_address = os.name != "nt"

            def server_bind(self):
                if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                super().server_bind()

        _HTTP_SERVER = ExclusiveHTTPServer
    return _HTTP_SERVER(address, handler)


def named_file(folder, names):
    """The first of `names` that is a file in `folder`, matched exactly against the folder's entries; None if none."""
    try:
        on_disk = {e.name for e in os.scandir(str(folder)) if e.is_file()}
    except OSError:
        return None
    for n in names:
        if n in on_disk:
            return os.path.join(str(folder), n)
    return None


def has_proc() -> bool:
    """A Linux-style /proc (absent on Windows and macOS)."""
    return os.path.isdir("/proc/self")


def proc_cmdline(pid: int) -> list:
    """A process's argv as strings; [] when it cannot be read (gone, not ours, or no /proc)."""
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return []


def terminate(pid: int) -> bool:
    """Ask one process (not its group) to stop. False when it is gone or not ours."""
    import signal
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def parent_pid(pid: int):
    """A process's parent pid; None when it cannot be read (gone, not ours, or no /proc)."""
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8", errors="replace") as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def tcp_socket_pid(local_port: int, remote_port: int, pids):
    """Which of `pids` holds the TCP socket whose local port is `local_port` and remote port `remote_port` (a client
    connected to one of our servers, seen from the client's side); None when none does or there is no /proc."""
    want = (":%04X" % int(local_port), ":%04X" % int(remote_port))
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, encoding="ascii", errors="replace") as f:
                rows = f.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            cols = row.split()
            if len(cols) > 9 and cols[1].endswith(want[0]) and cols[2].endswith(want[1]):
                inodes.add("socket:[%s]" % cols[9])
    if not inodes:
        return None
    for pid in pids:
        try:
            fds = os.listdir("/proc/%d/fd" % pid)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink("/proc/%d/fd/%s" % (pid, fd)) in inodes:
                    return pid
            except OSError:
                continue
    return None


def child_pids(pids) -> set:
    """`pids` and every process descended from them (one pass over /proc); just `pids` without /proc."""
    out = set(pids)
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return out
    parent = {}
    for n in names:
        pp = parent_pid(int(n))
        if pp is not None:
            parent[int(n)] = pp
    grew = True
    while grew:
        grew = False
        for pid, pp in parent.items():
            if pp in out and pid not in out:
                out.add(pid)
                grew = True
    return out
