"""Processes this server spawned (live pids, owned procs, who called a tool, recycle, reap, and the standby
maintenance loop). Split out of session.py the same way session_registry.py was: session.py re-exports every name
here, so callers keep `from session import owned_agent_procs` and tests keep patching names on `session`.

Names tests patch on session (DATA, REG, STANDBY_POOL, owned_agent_procs, _atomic_write_text, _now) are read as
`_s().name` on each call, never copied at import. This module does not import session at load time.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Dict, Tuple

import i18n


def _s():
    """The session module (already loaded: it imports this one at its end)."""
    return sys.modules["session"]


def _standby_maintenance_loop() -> None:
    while True:
        try:
            _s().STANDBY_POOL.ensure_warm()
        except Exception:
            pass
        try:
            _s()._reap_sessions()
        except Exception:
            pass
        time.sleep(15)


def _record_live_pids() -> None:
    """LOCK_ORDER_v1: runs under the caller's session lock (spawn, stop), so it never takes another session's: two
    spawning at once deadlocked, and the handoff pass and reaper with them (#728)."""
    try:
        host = _s()
        pids = []
        pool = getattr(host, "STANDBY_POOL", None)
        if pool is not None and pool._proc and pool._proc.poll() is None:
            pids.append(pool._proc.pid)
        reg = getattr(host, "REG", None)
        if reg is not None:
            try:
                with reg.lock:
                    sessions = list(reg.sessions.values())
                for s in sessions:
                    proc = s.proc
                    if proc and proc.poll() is None:
                        pids.append(proc.pid)
            except Exception:
                pass
        host._atomic_write_text(host.DATA / "live_pids.json", json.dumps(pids))
    except Exception:
        pass


def owned_agent_procs() -> Dict[int, dict]:
    """pid -> {owner, sid, busy} for every live process this server spawned
    (standby + session children), for accounts.snapshot(). Reads `s.proc`
    without taking `s.lock` on purpose -- a single reference read, and this
    runs on a GET handler where lock re-entry has deadlocked before (see
    OPERATIONS.md)."""
    host = _s()
    out: Dict[int, dict] = {}
    with host.STANDBY_POOL._lock:
        p = host.STANDBY_POOL._proc
        if p is not None and p.poll() is None:
            out[p.pid] = {"owner": "standby"}
    with host.REG.lock:
        sessions = list(host.REG.sessions.values())
    for s in sessions:
        proc = s.proc
        if proc is not None and proc.poll() is None:
            out[proc.pid] = {"owner": "session", "sid": s.sid, "busy": bool(s.busy)}
    return out


def caller_session(client_port: int, server_port: int, claimed: str = "") -> Tuple[str, str]:
    """Which session made a tool call (inbox/0): the process holding the client side of the TCP connection
    client_port -> server_port, walked up its ancestry to an agent process this server spawned. That is an OS fact the
    model cannot forge (a shell it runs is still that agent's descendant). The host's own process -- an HTTP brain
    calling tools from here -- names its session in `claimed`. Returns (session id or "", the process's name)."""
    import platform_compat
    host = _s()
    me = os.getpid()
    pid = platform_compat.tcp_socket_pid(client_port, server_port, sorted(platform_compat.child_pids({me})))
    if pid is None:
        return "", ""
    argv = platform_compat.proc_cmdline(pid)
    name = os.path.basename(argv[0]) if argv else ""
    if pid == me:
        return (claimed if claimed and host.REG.peek(claimed) is not None else ""), "host"
    owned = {p: v["sid"] for p, v in host.owned_agent_procs().items() if v.get("sid")}
    hop = pid
    for _ in range(32):
        if hop in owned:
            return owned[hop], name
        hop = platform_compat.parent_pid(hop)
        if not hop or hop <= 1 or hop == me:
            break
    return "", name


def recycle_agents(pids: set) -> dict:
    """Stop the given chatbot-owned agent processes so they respawn with the
    current login. Idle session children are stopped without notice (the next
    message respawns with the same --conversation, so context is kept); busy
    ones are skipped, never killed mid-turn. The standby is discarded."""
    host = _s()
    recycled, skipped = [], []
    owned = host.owned_agent_procs()
    for pid in pids:
        info = owned.get(pid)
        if not info:
            continue
        if info["owner"] == "standby":
            if host.STANDBY_POOL.discard():
                recycled.append(pid)
            continue
        if info.get("busy"):
            skipped.append(pid)
            continue
        with host.REG.lock:
            sess = host.REG.sessions.get(info["sid"])  # not REG.get(): that creates
        if sess is None:
            skipped.append(pid)
            continue
        try:
            sess.stop(notify=False)
            recycled.append(pid)
        except Exception:
            skipped.append(pid)
    return {"recycled": recycled, "skipped_busy": skipped}


def _reap_sessions() -> None:
    host = _s()
    now = host._now()
    live_pids = []
    with host.STANDBY_POOL._lock:
        if host.STANDBY_POOL._proc is not None and host.STANDBY_POOL._proc.poll() is None:
            live_pids.append(host.STANDBY_POOL._proc.pid)

    with host.REG.lock:
        sessions = list(host.REG.sessions.values())

    died = []
    for sess in sessions:
        with sess.lock:
            if sess.proc is not None:
                ret = sess.proc.poll()
                if ret is not None:
                    sess.proc = None
                    if sess.busy:
                        sess.busy = False
                        died.append(sess)
                        sess._emit({"event": "error", **i18n.msg("srv.agent_exited")})
                        has_queued = bool(getattr(sess, "msg_queue", []))
                        if has_queued:
                            threading.Thread(target=sess._dispatch_queued, daemon=True).start()
                elif not sess.busy:
                    idle_sec = now - getattr(sess, "last_activity", now)
                    if idle_sec > 900:  # 15 minutes of inactivity while not busy
                        proc = sess.proc
                        sess.proc = None
                        try:
                            if proc.stdin:
                                proc.stdin.close()
                            proc.terminate()
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                proc.kill()
                                proc.wait(timeout=1)
                            except Exception:
                                pass
                        # Evict from registry so the object can be GC'd.
                        with host.REG.lock:
                            host.REG.sessions.pop(sess.sid, None)
                    else:
                        live_pids.append(sess.proc.pid)
                else:
                    live_pids.append(sess.proc.pid)

    for sess in died:
        sess._finish_turn("process_died")
    try:
        host._atomic_write_text(host.DATA / "live_pids.json", json.dumps(live_pids))
    except Exception:
        pass
