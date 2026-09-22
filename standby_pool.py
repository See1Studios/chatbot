"""Standby agent process pool and background maintenance.

Keeps one pre-spawned, idle agy process warm to skip cold-start latency.
Extracted from session.py during modular refactoring.
"""
from __future__ import annotations

import subprocess
import threading
import uuid
from pathlib import Path
from typing import Optional, Tuple

from adapters import get_adapter
from host_config import (
    ADD_DIRS,
    DATA,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    HOME,
    WORKSPACE,
)


class _StandbyPool:
    """Keeps one pre-spawned, idle agy process warm so a brand-new session's
    first message can skip the ~7-9s cold-start tax (measured 2026-09-16 via
    isolated `agy --print` calls — a fixed per-process-spawn cost, independent
    of model/effort/ADD_DIRS; see docs/DEVLOG.md). Only used when the incoming
    session matches DEFAULT_MODEL with no effort override and no
    conversation_id yet (i.e. genuinely fresh) — anything else falls back to
    a normal cold spawn, since a standby's --model/--effort are fixed at
    spawn time and can't be changed after adoption.

    An unclaimed standby carries no --conversation flag like a stale probe
    leftover would, so it needs an explicit exemption from
    chatbot-ctl.sh's kill_orphan_agy() 90s no-conversation grace period —
    see standby.pid below, which that script checks and skips.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._conv_id: Optional[str] = None

    def _marker_path(self) -> Path:
        return DATA / "standby.pid"

    def try_take(self) -> Tuple[Optional[subprocess.Popen], Optional[str]]:
        with self._lock:
            proc = self._proc
            conv_id = self._conv_id
            self._proc = None
            self._conv_id = None
        if proc is not None and proc.poll() is None:
            try:
                self._marker_path().unlink(missing_ok=True)
            except Exception:
                pass
            return proc, conv_id
        return None, None

    def discard(self) -> bool:
        """Kill the warm standby (e.g. it authenticated as a since-replaced
        account). `_standby_maintenance_loop` warms a fresh one afterwards."""
        with self._lock:
            proc, self._proc, self._conv_id = self._proc, None, None
        try:
            self._marker_path().unlink(missing_ok=True)
        except Exception:
            pass
        if proc is None or proc.poll() is not None:
            return False
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return True

    def ensure_warm(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            adapter = get_adapter(DEFAULT_PROVIDER)
            conv_id = str(uuid.uuid4())
            args = adapter.build_args(DEFAULT_MODEL, "", conv_id, ADD_DIRS)
            env = adapter.build_env(HOME)
            try:
                self._proc = subprocess.Popen(
                    args,
                    cwd=str(WORKSPACE),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                )
                self._conv_id = conv_id
                try:
                    self._marker_path().write_text(str(self._proc.pid), encoding="utf-8")
                except Exception:
                    pass
            except Exception:
                self._proc = None
                self._conv_id = None


STANDBY_POOL = _StandbyPool()
