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
# #868: a provider that reports activity but has written nothing naming this process by then never started (CLI start,
# login or transport); agy names its process within seconds of start
START_SEC = int(os.environ.get("CHATBOT_WORKER_START_SEC", "300"))
WORKING = "while working"   # in a timeout's reason: the agent was busy to the end (brain_limits: not unavailable)
POLL_SEC = 15
KEEPALIVE_SEC = 600   # #870: the runner's author lease (30 min) is renewed this often while an agent runs


def activity_of(provider: str) -> Optional[Callable[[int, float], Optional[float]]]:
    """The provider's activity probe, or None when it reports none (AgentAdapter.reports_activity)."""
    try:
        from providers.adapters import AGENT_ADAPTERS
        adapter = AGENT_ADAPTERS.get(provider)
    except Exception:  # noqa: BLE001
        return None
    return adapter.last_activity if adapter is not None and getattr(adapter, "reports_activity", False) else None


def run(cmd: List[str], cwd=None, timeout: int = 120, env: Optional[Dict[str, str]] = None,
        stdin: Optional[str] = None, activity: Optional[Callable[[int, float], Optional[float]]] = None,
        stall_sec: int = STALL_SEC, poll_sec: float = POLL_SEC, start_sec: int = START_SEC,
        keepalive: Optional[Callable[[], None]] = None, keepalive_sec: float = KEEPALIVE_SEC) -> tuple:
    """(returncode, stdout, stderr) like the runner's run_cmd; -1 with "timed out after Ns", "timed out after Ns
    while working (...)" (busy to the end: the work was too long, the brain is fine -- #868), "stalled: ..." or
    "stalled at start: ..." when the process was stopped."""
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace",
                                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL)
    except OSError as e:
        return -1, "", str(e)
    started, pending, last_seen = time.time(), stdin, None
    kept_at = started
    while True:
        wait = max(0.05, min(poll_sec, started + timeout - time.time()))   # the timeout is kept to the second
        try:
            out, err = proc.communicate(input=pending, timeout=wait)
            return proc.returncode, out.strip(), err.strip()
        except subprocess.TimeoutExpired:
            pending = None                       # communicate() takes the input once
        now = time.time()
        if keepalive is not None and now - kept_at >= keepalive_sec:   # an agent may now outlive the lease (#870)
            kept_at = now
            try:
                keepalive()
            except Exception:  # noqa: BLE001 -- the runner's own renew after the run reports a lost lease
                pass
        last = None
        if activity is not None:
            try:
                last = activity(proc.pid, started)
            except Exception:  # noqa: BLE001 -- a broken probe never stops the work
                last, last_seen = None, last_seen if last_seen is not None else started   # unknown: not "never started"
            if last is not None:
                last_seen = max(last, last_seen or last)
        why = ""
        if now - started >= timeout:
            busy = last_seen is not None and last_seen > started and now - last_seen <= stall_sec
            why = ("timed out after %ds %s (last model activity %ds ago)" % (timeout, WORKING, now - last_seen)
                   if busy else "timed out after %ds" % timeout)
        elif last is not None and now - max(last, started) > stall_sec:
            why = "stalled: no model activity for %ds (quota, capacity or a hung stream)" % stall_sec
        elif activity is not None and last_seen is None and now - started > start_sec:
            why = "stalled at start: nothing named this process after %ds (CLI start, login or transport)" % start_sec
        if why:
            proc.kill()
            out, _err = proc.communicate()
            return -1, (out or "").strip(), why
