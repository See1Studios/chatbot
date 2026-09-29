"""Test markers for what differs by OS (docs/plans/platform-portability.md pp/E, #407).

dev_only_bash: the test drives dev-build tooling written in bash -- chatbot-ctl.sh (the NAS host control), the git
hooks, run-tests.sh as the ticket gate, the worktree runner, the run_command tool. None of these is in the shipped
build (edition-boundary), and Windows has no POSIX bash (its bash.exe is a WSL stub, so which("bash") is not enough).
"""
import os
import shutil
import unittest

POSIX_BASH = os.name == "posix" and bool(shutil.which("bash"))
dev_only_bash = unittest.skipUnless(POSIX_BASH, "dev-build bash tooling; no POSIX bash on this OS (platform-portability pp/E)")

POSIX = os.name == "posix"
posix_only = unittest.skipUnless(POSIX, "POSIX-only by design (the NAS host plugin, /dev/tty, mode bits)")


def home_env(path) -> dict:
    """Environment that moves `~` to `path` on every OS: POSIX reads HOME, Windows' Python reads USERPROFILE (#411:
    tests that set only HOME kept Windows' real home, and with neither set the home was unknown)."""
    return {"HOME": str(path), "USERPROFILE": str(path)}
