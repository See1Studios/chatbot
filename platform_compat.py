"""PLATFORM_COMPAT_v1 (docs/plans/platform-portability.md pp/D): the one place for calls that differ by OS.

Layers call these instead of fcntl, /proc and friends; each function holds its POSIX and Windows sides, and
test_ratchets' `posix` ratchet skips this file only. The self-evolution core (core_modules.json: stdlib and each
other only) keeps its own copy inside evolution.acquire_lock.

- lock_file / unlock_file: an exclusive lock on an open file -- flock on POSIX, msvcrt.locking on Windows (the first
  byte; a lock beyond the end of the file is allowed). Where neither exists the lock is skipped (fail open: a lock
  here is a safeguard, never a reason the host cannot run).
- has_proc: whether a Linux-style /proc is there; code that reads it degrades instead of crashing without it.
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


def has_proc() -> bool:
    """A Linux-style /proc (absent on Windows and macOS)."""
    return os.path.isdir("/proc/self")
