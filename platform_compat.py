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
- named_file: the first of several names that exists in a folder, spelled as it is on disk. Windows and macOS file
  systems ignore case, so `(d / "ROLE.md").is_file()` is true for role.md there and the caller would show a name
  that is not on disk (FIREBAT 2026-09-29, #405).
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
