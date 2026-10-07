"""A delegated worker that stops answering is cut early (WORKER_STALL_v1). The runner used to wait out the whole
agent timeout (20 min) for a model stream that had stalled -- #462 made one call, then nothing for 18 min, twice. The
worker now runs under a watch: when its provider reports activity (AgentAdapter.last_activity, e.g. model calls in
agy's own log) and none came for STALL_SEC, it is stopped and reported like a timeout, so the runner moves to the
character's next brain. A provider with no activity signal is held to the overall timeout only: files changing or
not says nothing about a model reading or thinking. Standard library + the adapters; used by tools/worktree_runner.py.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Callable, Dict, List, Optional

STALL_SEC = int(os.environ.get("CHATBOT_WORKER_STALL_SEC", "600"))   # 2x the longest gap seen in 83 worker runs
POLL_SEC = 15


def activity_of(provider: str) -> Optional[Callable[[int, float], Optional[float]]]:
    """The provider's activity probe, or None."""
    try:
        from providers.adapters import AGENT_ADAPTERS
        adapter = AGENT_ADAPTERS.get(provider)
    except Exception:  # noqa: BLE001
        return None
    return adapter.last_activity if adapter is not None else None


def run(cmd: List[str], cwd=None, timeout: int = 120, env: Optional[Dict[str, str]] = None,
        stdin: Optional[str] = None, activity: Optional[Callable[[int, float], Optional[float]]] = None,
        stall_sec: int = STALL_SEC, poll_sec: float = POLL_SEC) -> tuple:
    """(returncode, stdout, stderr) like the runner's run_cmd; -1 with "timed out after Ns" or "stalled: ..." when
    the process was stopped."""
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace",
                                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL)
    except OSError as e:
        return -1, "", str(e)
    started, pending = time.time(), stdin
    while True:
        wait = max(0.05, min(poll_sec, started + timeout - time.time()))   # the timeout is kept to the second
        try:
            out, err = proc.communicate(input=pending, timeout=wait)
            return proc.returncode, out.strip(), err.strip()
        except subprocess.TimeoutExpired:
            pending = None                       # communicate() takes the input once
        now = time.time()
        why = "timed out after %ds" % timeout if now - started >= timeout else ""
        if not why and activity is not None:
            try:
                last = activity(proc.pid, started)
            except Exception:  # noqa: BLE001 -- a broken probe never stops the work
                last = None
            if last is not None and now - max(last, started) > stall_sec:
                why = "stalled: no model activity for %ds (quota, capacity or a hung stream)" % stall_sec
        if why:
            proc.kill()
            out, _err = proc.communicate()
            return -1, (out or "").strip(), why
