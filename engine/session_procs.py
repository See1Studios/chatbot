"""Processes this server spawned (live pids, owned procs, who called a tool, recycle, reap, the standby
maintenance loop, starting a child, and reading its stdout and stderr). Split out of session.py the same way
session_registry.py was: session.py re-exports every function here, and AgentSession inherits SessionProcs, so
callers keep `from session import owned_agent_procs` and `sess._spawn`. Tests keep patching names on `session`.

Names tests patch on session (DATA, REG, STANDBY_POOL, DEFAULT_MODEL, ADD_DIRS, HOME, WORKSPACE,
owned_agent_procs, _atomic_write_text, _record_live_pids, _redact_line, _now) are read as `_s().name` on each
call, never copied at import. This module does not import session at load time. session.py imports this mixin
before AgentSession and re-exports the functions at the end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import i18n
from telemetry import obslog


def _s():
    """The session module. session.py imports this module before AgentSession and again at the end; the lookup
    runs only after that load has finished."""
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


class SessionProcs:
    """Starting the agent child and reading its stdout and stderr. AgentSession inherits this."""

    def _spawn(self, prompt: str = "") -> None:
        """`prompt` (Multi-Provider plan Phase 2): only meaningful for a
        one-shot exec provider (keeps_stdin_open=False) -- _send_direct()
        calls this directly with the turn's text instead of writing to a
        long-lived stdin, since that kind of CLI takes its prompt via argv/a
        file at spawn time and exits after the one turn."""
        host = _s()
        self.stop(notify=False)
        self._stop_requested = False
        self._resume_or_reseed()
        adopted, adopted_conv_id = None, None
        if not self.conversation_id and self.model == host.DEFAULT_MODEL and not self.effort and self.adapter.keeps_stdin_open:
            adopted, adopted_conv_id = host.STANDBY_POOL.try_take()
        self._adopted_standby = adopted is not None  # skill-observations 0009: tag turns
        # that came from a warm-standby-adopted process, to correlate against
        # the rare all-zero-usage-on-first-turn report if it recurs.
        if adopted is not None:
            self.proc = adopted
            if adopted_conv_id:
                self.conversation_id = adopted_conv_id
                self.save_meta()
            self._emit({"event": "system", "text": f"agy started model={self.model} (warm standby, skip-permissions, accept-edits, NAS)"})
        else:
            # mints_own_conversation_id() (Multi-Provider plan Phase 0.5/1):
            # agy needs a uuid pre-minted before its first spawn or it
            # auto-resumes some unrelated stale conversation of its own (see
            # the 2026-09-17 HISTORY entry) -- but claude does the opposite:
            # verified live (2026-09-17) that `--resume <id>` on an id claude
            # has never seen fails the turn outright ("No conversation found
            # with session ID: ..."), so a provider that mints its own id
            # must start with conversation_id empty and let normalize_line
            # capture the real one from the first turn's response.
            if not self.conversation_id and not self.adapter.mints_own_conversation_id():
                self.conversation_id = str(uuid.uuid4())
                self.save_meta()
            args = self.adapter.build_args(self.model, self.effort, self.conversation_id, host.ADD_DIRS, prompt=prompt)
            env = self.adapter.build_env(host.HOME)
            env["CHATBOT_LIVE_AGENT"] = "1"
            self.proc = subprocess.Popen(
                args,
                cwd=str(host.WORKSPACE),
                # A one-shot provider still needs a real pipe if it takes its
                # prompt via stdin-then-close (codex: close_stdin_after_prompt)
                # rather than a file (grok: neither flag set, DEVNULL is
                # correct since nothing is ever written to it).
                stdin=subprocess.PIPE if (self.adapter.keeps_stdin_open or self.adapter.close_stdin_after_prompt) else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                # CODEX_PROC_v1: new session so stop()/recycle can killpg the
                # whole tree (codex node wrapper + native child). Safe for
                # agy/claude/grok too.
                start_new_session=True,
            )
            prompt_path = getattr(self.adapter, "_last_prompt_path", None)
            if prompt_path:  # a one-shot provider's prompt file, removed when the child exits
                self.proc._prompt_file = prompt_path
                self.adapter._last_prompt_path = None
            self._emit({"event": "system", "text": f"{self.provider} started model={self.model} (skip-permissions, accept-edits, NAS)"})
        threading.Thread(target=self._read_stdout, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        host._record_live_pids()

    @staticmethod
    def _reported_conversation_id(obj: dict) -> Optional[str]:
        for src in (obj, obj.get("step_update"), obj.get("result")):
            if isinstance(src, dict):
                v = src.get("conversation_id")
                if isinstance(v, str) and len(v) >= 8:
                    return v
        return None

    def _adopt_conversation_id(self, cid: str) -> None:
        with self.lock:
            self.conversation_id = cid
        self.save_meta()
        self._emit({"event": "system", "text": f"conversation_id={cid}"})

    def _maybe_capture_conversation_id(self, obj: dict) -> None:
        if not self.adapter.mints_own_conversation_id():
            # agy: the uuid we pre-mint (see _spawn) is only an instruction to "start a fresh
            # conversation" -- agy has no such conversation, logs "not found, ignoring
            # --conversation flag", creates its OWN and reports that id in `init`, every
            # `step_update` and `result`. Until 2026-09-20 we kept the phantom id, so all 114
            # stored agy ids pointed at nothing and every respawn silently started an empty
            # conversation (measured). Adopt the reported id so the next --conversation resumes.
            reported = self._reported_conversation_id(obj)
            if reported and reported != self.conversation_id:
                self._adopt_conversation_id(reported)
            return
        if self.conversation_id:
            return
        sources = [obj]
        step = obj.get("step_update")
        if isinstance(step, dict):
            sources.append(step)
        result = obj.get("result")
        if isinstance(result, dict):
            sources.append(result)
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in ("conversation_id", "session_id", "id"):
                val = source.get(key)
                if isinstance(val, str) and len(val) >= 8 and not self.conversation_id:
                    # avoid capturing random short ids / step ids that aren't conversations
                    if key == "id" and source is obj and obj.get("event") not in (None, "result", "system"):
                        continue
                    self.conversation_id = val
                    self.save_meta()
                    self._emit({"event": "system", "text": f"conversation_id={val}"})
                    return

    def _resume_or_reseed(self) -> None:
        """Before every (re)spawn of a child. A CLI may resume `--conversation <id>` only if its
        store has that conversation (adapter.has_conversation); otherwise it starts an EMPTY one, which
        used to happen on every respawn (idle reap, swap, stop, crash) with nothing telling the
        agent -- so it lost its memory, persona and rules while the window still showed the
        whole chat (2026-09-20: "are you a different process?"). If the id is not in agy's store, drop it
        and re-seed the next message with the rules and a digest of the visible history."""
        if not self.conversation_id:
            return
        check = getattr(self.adapter, "has_conversation", None)
        if check is None or check(self.conversation_id) is not False:
            return  # present, or this provider cannot tell
        self.conversation_id = None  # _spawn mints a fresh id (which also keeps agy from auto-resuming an unrelated one)
        if any(h.get("role") in ("user", "assistant") and (h.get("text") or "").strip() for h in self.history):
            self._reseed_from_history()

    def _reseed_from_history(self) -> None:
        with self.lock:
            self.persona_injected = False
            self.persona_bundle_hash = ""
            if self.handoff_injected or not self.handoff_summary:  # a pending /continue handoff stays as is
                self.handoff_summary = self._host_history_digest()
                self.handoff_injected = False
        self.save_meta()
        self._emit({"event": "system", **i18n.msg("srv.reseeded")})

    def _read_stdout(self, proc: Optional[subprocess.Popen] = None) -> None:
        # Bound to ONE child. A steer/interrupt kills the child and respawns within milliseconds,
        # and _spawn() clears _stop_requested -- so without knowing which child this thread reads,
        # leftovers in the OLD pipe were processed as if they were the new turn, and the old
        # child's exit could switch the NEW turn's busy flag off.
        host = _s()
        proc = proc or self.proc
        assert proc and proc.stdout
        died_mid_turn = False
        try:
            for line in proc.stdout:
                if self._stop_requested or self.proc is not proc:
                    # Drain silently: an explicitly-killed process can still
                    # have output already sitting in the pipe buffer, and
                    # processing it here would emit/save it as if the turn
                    # had continued normally after the user asked to stop.
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    self._handle_stdout_line(line)
                except Exception as e:
                    obslog.exception("session.stdout_line_failed", e, sid=self.sid, provider=self.provider,
                                     dedup="%s|%s" % (self.sid, type(e).__name__), line=line[:300])
        finally:
            with self.lock:
                if self.busy and self.proc is proc:  # only if THIS child died mid-turn
                    self.busy = False
                    died_mid_turn = True
                    err_msg = i18n.msg("srv.agent_exited")
                    # Persist what streamed in before the child died -- the live view
                    # already finalizes this same draft into a normal bubble, so a
                    # reload silently erasing it would be a desync (SESSION_DESYNC_GAPFIX_v2).
                    draft = (self.current_text or "").strip()
                    if draft:
                        self.history.append({"role": "assistant", "text": draft, "ts": host._now()})
                    self.history.append({"role": "assistant", **err_msg, "notice": "error", "ts": host._now()})
                    self.save_meta()
                    self.current_text = ""
                    self._emit({"event": "error", **err_msg})
                    has_queued = bool(getattr(self, "msg_queue", []))
                    if has_queued:
                        threading.Thread(target=self._dispatch_queued, daemon=True).start()
            if died_mid_turn:
                self._finish_turn("process_died")
            try:
                rc = proc.poll()
                if rc is None:
                    rc = proc.wait(timeout=2)
            except Exception:
                rc = None
            try:
                obslog.event("agent.exit", lvl="warn" if died_mid_turn else "info", sid=self.sid,
                             provider=self.provider, agent_pid=getattr(proc, "pid", None), rc=rc,
                             died_mid_turn=died_mid_turn, requested=bool(self._stop_requested) or self.proc is not proc)
            except Exception:  # noqa: BLE001 -- logging must never disturb the reader
                pass
            host._record_live_pids()
            prompt_file = getattr(proc, "_prompt_file", None)
            if prompt_file:
                try:
                    Path(prompt_file).unlink(missing_ok=True)
                except Exception:
                    pass

    def _handle_stdout_line(self, line: str) -> None:
        """Provider-agnostic since Multi-Provider plan Phase 0: the actual
        protocol parsing (agy's stream-json shape today) lives in
        `self.adapter.normalize_line()`. This method only turns one raw
        stdout line into canonical events and hands them to `_handle_events`
        for the bookkeeping shared with the http transport."""
        events = self.adapter.normalize_line(self, line)
        self._handle_events(events)

    def _handle_events(self, events: List[dict]) -> None:
        """API-Provider plan: the busy/heavy-check/queued-dispatch
        bookkeeping that used to live only in `_handle_stdout_line` --
        extracted so `_run_http_turn` (transport_kind="http", no stdout line
        to parse, `stream_turn()` yields canonical events directly) shares
        the exact same post-processing as the CLI path instead of a second,
        driftable copy."""
        for ev_obj in events:
            self._emit(ev_obj)
        if any(ev_obj.get("event") in ("result", "error") for ev_obj in events):
            self.busy = False
            self._finish_turn("error" if any(e.get("event") == "error" for e in events) else "result")
            try:
                self._emit_heavy_if_needed()
            except Exception:
                pass
            # TURN_END_ORDER_v1: kill hung agy only after UI got the answer/error
            try:
                self._run_post_result_stop()
            except Exception as e:
                obslog.exception("turn.post_result_stop_failed", e, lvl="warn", sid=self.sid)
            with self.lock:
                has_queued = bool(getattr(self, "msg_queue", []))
            if has_queued:
                threading.Thread(target=self._dispatch_queued, daemon=True).start()

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            if _s()._redact_line(line):
                continue  # drop before storing: never appears in _stderr_tail or events
            self._stderr_tail.append(line[-500:])
            self._stderr_tail = self._stderr_tail[-30:]
            low = line.lower()
            # Surface jetski/sandbox denials as tool events for visibility
            if "jetski" in low or "sandbox" in low or "soft-denying" in low or "permission" in low:
                self._emit({"event": "tool", "text": line[:500], "title": "permission", "status": "stderr"})
            else:
                self._emit({"event": "stderr", "text": line[:500]})

    def ensure(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            self._spawn()
