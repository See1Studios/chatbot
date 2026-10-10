"""In-memory session registry and AgentSession.

Extracted from server.py (monolith-split Phase 1). Processes this server spawned live in session_procs.py:
the functions are re-exported here, and starting a child, reading its pipes, and stopping it is the SessionProcs mixin.
Provider and model swap, the HTTP turn, the steer queue, and sending a turn directly live on the turn mixin; the handoff text lives on the view mixin.
chatbot-ctl.sh guard_rlock AST-scans this file for AgentSession.lock = threading.RLock().
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from providers.adapters import get_adapter
from providers.adapters import _persona_system_prompt  # noqa: F401 -- the turn mixin reads _s()._persona_system_prompt
from private_engine import tension_meta
from instructions import build_instruction_bundle  # noqa: F401 -- session_turn reads it as _s().build_instruction_bundle (tests swap it here)
from identity import display_name, user_title

import i18n
from telemetry import obslog
import quota_state  # QUOTA_STATE_v1 qfr/D
import regenerate  # REGENERATE_v1
import write_guard
from turn_watchdog import TurnWatchdog
from session_view import SessionView   # split/C: what a session shows (reads SESSIONS, ADD_DIRS... from here)
from session_turn import SessionTurn   # split/C: running a turn, and swapping the provider or model (reads REG, get_adapter... from here)
from session_procs import SessionProcs  # starting the child and reading its pipes (patched names go through _s())
from loop_guard import LoopGuard, extract_tool_steps, is_read_only
from host_config import (
    ADD_DIRS,  # noqa: F401 -- session_procs reads it as _s().ADD_DIRS
    DATA,  # noqa: F401 -- tests retarget session.DATA; session_procs reads it as _s().DATA
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    ONESHOT_PROVIDER,
    HOME,  # noqa: F401 -- session_procs reads it as _s().HOME
    PERSISTED_LOG_KINDS,
    ROOT,
    SESSIONS,
    WORKSPACE,  # noqa: F401 -- session_procs reads it as _s().WORKSPACE
    _now,
)
import repo_layout
# WRITE_GUARD_REPO_v1: tickets name repo-relative paths (`engine/x.py`); the write guard compares against the repo
# root, not the engine folder (after the layout move a claimed engine file read as `x.py` and was never covered).
REPO_ROOT = repo_layout.REPO
from artifact_manager import (
    _atomic_write_text,
    _safe_artifact_rel,
    _safe_session_id,
)
from standby_pool import (
    STANDBY_POOL,  # noqa: F401 -- tests retarget session.STANDBY_POOL; session_procs reads it as _s().STANDBY_POOL
)
from session_weights import (
    _handoff_prompt,  # noqa: F401 -- the view mixin reads _session()._handoff_prompt; tests call session._handoff_prompt
    _session_weight,
)
from media_handler import (
    _append_images_markdown,
    _collect_new_images,
    _artifact_dirs,
    _rewrite_artifact_paths,
    _stage_image,
)

# A message sent while an agy turn is running is accepted at once and applied at the next
# tool-step boundary (steer). agy itself cannot take a message mid-turn: measured 2026-09-20,
# a second stdin line only QUEUES and runs after the current turn ends (agy.md A41).
# Session event kinds copied into logs/events.jsonl (OBSLOG_v1, see _obs_forward).
LOOP_NOTICE_KEYS = {"srv.loop_warn", "srv.budget_warn", "srv.loop_noticed", "srv.unticketed_tree"}   # turn.loop_notice
_OBS_FORWARD = {"error", "stopped", "interrupted", "session_rotate", "session_heavy", "steer_queued", "system"}

STEER_MAX_WAIT_SEC = 90   # no boundary for this long (long reasoning, no tools): interrupt anyway
boot_notice = lambda sess: ""  # server.py hook: the "[Host note]" restart line, once per session per boot
LOOP_STOP_AFTER_NOTICE = 3   # repeats that still continue after the agent was told to change course -> stop
LOOP_NOTICE = ("You are repeating the same tool call ({what}). It brings nothing new: stop here, sum up what you have "
               "learned in three lines, then change approach (read a large file in parts with StartLine/EndLine, or find "
               "only the part you need with grep). Do not redo finished steps from the start; ask {user} only when truly stuck.")
BUDGET_NOTICE = ("This turn is over its budget ({what}): everything read is sent to the model again on every later "
                 "call. If this is a large code change, sum up what you found and hand it over with delegate; "
                 "otherwise stop here and answer with what you have. To read more, find the place with grep and "
                 "read only that range (StartLine/EndLine).")
CONTEXT_LOG_KEEP = 6   # what went into the agent, newest last, for the status tab (CONTEXT_PANEL_v1)
STEER_HINT = ("The last work only paused between tool steps to take this message; it was not cancelled. Unless this "
              "message clearly asks to cancel or change it, carry on with that work while following this message. Do not "
              "redo finished steps from the start.")


_SENSITIVE_STDERR_KEYS = ("token", "authorization", "bearer", "api_key", "refresh")


def _redact_line(line: str) -> bool:
    """Return True when the line contains a sensitive credential and should be
    dropped (i.e. never stored, never emitted)."""
    low = (line or "").lower()
    return any(k in low for k in _SENSITIVE_STDERR_KEYS)


def _redact_text(text: str) -> str:
    """Filter sensitive credential lines from multi-line text (e.g. proc.stderr)."""
    if not text:
        return ""
    clean = [l for l in text.splitlines() if not _redact_line(l)]
    return "\n".join(clean).strip()


def _oneshot(prompt: str, timeout: float):
    """A single prompt on the configured oneshot provider (adapter hook, PROVIDER_NEUTRAL_v1)."""
    try:
        return get_adapter(ONESHOT_PROVIDER).oneshot(prompt, timeout)
    except Exception as e:  # noqa: BLE001
        return {"text": "", "usage": None, "duration_seconds": None, "error": str(e)}


def format_client_context(ctx: Optional[Dict[str, Any]]) -> str:
    """The page's device facts as one English note for the agent (agent-facing text is English)."""
    if not isinstance(ctx, dict) or not ctx:
        return ""
    _num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    p = []
    lat, lon, acc = ctx.get("lat"), ctx.get("lon"), ctx.get("accuracy")
    if _num(lat) and _num(lon):
        p.append(f"location {lat:.4f}, {lon:.4f}" + (f" ±{int(acc)}m" if _num(acc) and acc > 0 else ""))
    tz = ctx.get("timezone")
    if isinstance(tz, str) and tz.strip():
        p.append(tz.strip()[:40])
    if ctx.get("is_mobile") is True:
        p.append("mobile")
    elif ctx.get("is_mobile") is False:
        p.append("desktop")
    if isinstance(dev := ctx.get("device"), str) and (d := dev.strip()) and d not in ("mobile", "desktop"):
        p.append(d[:30])
    batt = ctx.get("battery")
    if _num(batt):
        p.append(f"battery {max(0, min(100, int(batt)))}%" + (" charging" if ctx.get("charging") is True else ""))
    if isinstance(net := ctx.get("net_type"), str) and (n := net.strip()):
        p.append(f"network:{n[:20]}")
    elif ctx.get("online") is True:
        p.append("online")
    elif ctx.get("online") is False:
        p.append("offline")
    resumed = ctx.get("resumed")
    if resumed is True:
        p.append("back")
    elif _num(resumed) and 0 < resumed < 100_000_000:
        p.append(f"back after {int(resumed)}s")
    if isinstance(vis := ctx.get("visibility"), str) and (v := vis.strip()) and v != "visible":
        p.append("in the background")
    elif ctx.get("focused") is False:
        p.append("tab not focused")
    return "[Client: " + ", ".join(p) + "]" if p else ""


class AgentSession(SessionTurn, SessionView, TurnWatchdog, SessionProcs):
    def __init__(self, sid: str, model: str = DEFAULT_MODEL, effort: str = "", provider: str = DEFAULT_PROVIDER):
        self.sid = sid
        self.provider = provider or DEFAULT_PROVIDER
        self.adapter = get_adapter(self.provider)
        # DEFAULT_MODEL names an agy/Gemini model -- only fall back to it for agy
        self.model = model or (DEFAULT_MODEL if self.provider == DEFAULT_PROVIDER else "")
        self.effort = effort or ""
        self.conversation_id: Optional[str] = None
        self.proc: Optional[subprocess.Popen] = None
        self._http_resp = None  # in-flight urlopen() response for transport_kind="http"
        self.subscribers: List["queue.Queue[dict]"] = []
        self.lock = threading.RLock()  # DEADLOCK GUARD: must stay RLock — ensure()->_spawn()->stop() nests
        if type(self.lock) is type(threading.Lock()):  # pragma: no cover
            raise RuntimeError('AgentSession.lock must be RLock, not Lock')
        self.created_at = _now()
        self.last_activity = self.created_at
        self.history: List[dict] = []
        self.busy = False
        self.msg_queue: List[Tuple[str, str]] = []
        self.current_text = ""
        self.last_progress = ""
        self.last_progress_key, self.last_progress_vars = "", {}
        self.turn_started_at = 0.0
        self._turn_t0: Optional[float] = None
        self.ttft_ms: Optional[float] = None
        self.pending_images: List[str] = []
        self._stderr_tail: List[str] = []
        # meta.json + artifacts/ live together under one per-session folder
        self.meta_path = SESSIONS / sid / "meta.json"
        self._heavy_warned_level = ""  # '', soft, hard — avoid spam
        self.successor_session_id = ""  # sticky rotate target
        self.predecessor_session_id = ""  # previous session ID if continued/rotated
        self.handoff_summary = ""  # concise handover summary from predecessor
        self.handoff_injected = False  # True once prepended to first agy stdin payload
        self.persona_injected = False  # True once the instruction bundle was prepended to a turn (all providers)
        self.persona_bundle_hash = ""  # instructions.py hash of the static layers last injected
        # SESSION_SPLIT_v1 (plan doc §12): whose conversation this is and in which mode. character "" = the chatbot
        # itself; mode "private" = a private session (its own conversation, private rules and memory, no work tools)
        self.character = ""
        self.mode = "work"
        self.private_digested_ts = 0.0  # private sessions: turns up to this time are already in private memory
        self.tension_stage, self.recent_choices = tension_meta({})  # PRIVATE_TENSION_v1: private stage 1..4, used choices
        self.refusal_mitigation = False  # GEMINI_REFUSAL_MITIGATION_TEST_v1 (#249): opt-in Gemini refusal layer
        self._cached_summary = ""  # memoized handover summary for zero-delay rotate
        self._summary_generating = False
        self._stop_requested = False  # True after an explicit stop() until the next _spawn()
        self._turn_seq = 0  # bumped each http-transport turn so a stale watchdog can't stop a later turn
        self._loop_guard = LoopGuard()  # repeated-tool-call detector (loop_guard.py); reset every turn
        self._regen = None  # REGENERATE_v1: a take in flight
        self._turn_effects = False  # REGENERATE_v1: did more than read
        self._loop_hint = ""  # one-shot note prepended to the next message after an automatic stop
        self._loop_stopping = False
        self._loop_warned = False  # one on-screen warning per turn is enough
        self._loop_noticed = False  # the agent was already told once this user turn to change course
        self._steering = False  # a steer (interrupt at a step boundary + resume) is in progress
        self._steer_since = 0.0  # when the oldest still-queued message arrived
        self._load_meta()

    @property
    def is_private(self) -> bool:
        return getattr(self, "mode", "work") == "private"

    def _load_meta(self) -> None:
        if self.meta_path.exists():
            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                self.conversation_id = meta.get("conversation_id")
                self.provider = meta.get("provider") or self.provider
                self.adapter = get_adapter(self.provider)  # re-resolve -- __init__'s default may not match a saved session
                self.model = meta.get("model") or self.model
                self.effort = meta.get("effort") or self.effort
                self.history = meta.get("history") or []
                self.successor_session_id = str(meta.get("successor_session_id") or "")
                self.predecessor_session_id = str(meta.get("predecessor_session_id") or "")
                self.handoff_summary = str(meta.get("handoff_summary") or "")
                self.handoff_injected = bool(meta.get("handoff_injected", False))
                self.persona_injected = bool(meta.get("persona_injected", False))
                self.persona_bundle_hash = str(meta.get("persona_bundle_hash") or "")
                self.context_layer_hashes = meta.get("context_layer_hashes")   # CONTEXT_REFRESH_v1; None: adopt
                self.context_log = list(meta.get("context_log") or [])[-CONTEXT_LOG_KEEP:]   # CONTEXT_PANEL_v1
                self.character = str(meta.get("character") or "")
                self.mode = meta.get("mode") if meta.get("mode") in ("private", "room") else "work"   # room: evt/E
                self.private_digested_ts = float(meta.get("private_digested_ts") or 0)
                self._regen_restore = str(meta.get("regen_restore") or "")   # #883: a harder take survives a restart
                self.tension_stage, self.recent_choices = tension_meta(meta)
                self.refusal_mitigation = bool(meta.get("refusal_mitigation", False))  # #249 opt-in
                ts_list = [h.get("ts") for h in self.history if isinstance(h.get("ts"), (int, float))]
                if ts_list:
                    self.last_activity = max(ts_list)
                elif self.meta_path.exists():
                    self.last_activity = self.meta_path.stat().st_mtime
            except Exception as e:
                ts = int(time.time())
                corrupt_path = self.meta_path.with_name(f"{self.meta_path.name}.corrupt-{ts}")
                obslog.exception("session.meta_corrupt", e, lvl="warn", sid=self.sid, renamed_to=corrupt_path.name)
                try:
                    self.meta_path.replace(corrupt_path)
                except Exception:
                    pass

    def save_meta(self) -> None:
        with self.lock:
            payload = {
                "id": self.sid,
                "provider": self.provider,
                "model": self.model,
                "effort": self.effort,
                "conversation_id": self.conversation_id,
                "history": self.history[-80:],
                "successor_session_id": getattr(self, "successor_session_id", "") or "",
                "predecessor_session_id": getattr(self, "predecessor_session_id", "") or "",
                "handoff_summary": getattr(self, "handoff_summary", "") or "",
                "handoff_injected": getattr(self, "handoff_injected", False),
                "persona_injected": getattr(self, "persona_injected", False),
                "persona_bundle_hash": getattr(self, "persona_bundle_hash", "") or "",
                "context_layer_hashes": getattr(self, "context_layer_hashes", None),
                "context_log": list(getattr(self, "context_log", []) or [])[-CONTEXT_LOG_KEEP:],
                "character": getattr(self, "character", "") or "",
                "mode": getattr(self, "mode", "work") or "work",
                "private_digested_ts": getattr(self, "private_digested_ts", 0.0) or 0.0,
                "regen_restore": getattr(self, "_regen_restore", "") or "",
                "tension_stage": getattr(self, "tension_stage", 1), "recent_choices": list(getattr(self, "recent_choices", [])),
                "refusal_mitigation": bool(getattr(self, "refusal_mitigation", False)),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            try:
                _atomic_write_text(self.meta_path, json.dumps(payload, ensure_ascii=False, indent=2))
                _meta_touched(self.meta_path)
            except Exception as e:
                obslog.exception("session.save_meta_failed", e, sid=self.sid)

    def _emit(self, event: dict) -> None:
        self.last_activity = _now()
        kind = event.get("event")
        if kind in ("tool", "system"):
            # QUOTA_ERR_DEDUP_v1: agy surfaces quota as step_type/title error_message
            step = str(event.get("step_type") or event.get("title") or "").strip()
            line = (event.get("title") or event.get("text") or "").strip()
            is_err_msg = step == "error_message" or line == "error_message"
            if is_err_msg:
                line = i18n.text("srv.checking_quota")
            if line:
                self.last_progress = line[:240]
                self.last_progress_key, self.last_progress_vars = ("srv.checking_quota" if is_err_msg else ""), {}   # I18N_v1
            # SILENT_HANG_v1: tool start/result/progress heartbeats reset the idle
            # clock (not only assistant text). Long tools are fine while progress
            # continues. error_message is owned by QUOTA_FAILFAST — do not re-arm.
            if not is_err_msg:
                self._touch_turn_activity()
        elif kind in ("delta", "thinking"):
            # SILENT_HANG_v1: streaming assistant text -- or the brain's streamed reasoning -- resets the idle clock
            self._touch_turn_activity()
        if kind in ("delta", "thinking") or (kind == "result" and event.get("text")):
            if getattr(self, "ttft_ms", None) is None and getattr(self, "_turn_t0", None) is not None:
                self.ttft_ms = round((time.time() - self._turn_t0) * 1000, 1)
        if kind in ("result", "error", "stopped"):
            self.last_progress = ""
            self.last_progress_key, self.last_progress_vars = "", {}
            # QUOTA_FAILFAST_v1: real terminal event — cancel pending failfast
            self._cancel_error_message_failfast()
            # SILENT_HANG_v1: turn ended — cancel idle watchdog
            self._cancel_silent_hang()
        if kind in PERSISTED_LOG_KINDS:
            self._append_log_event(event)
        if kind in _OBS_FORWARD:
            self._obs_forward(kind, event)
        dead = []
        with self.lock:
            for q in list(self.subscribers):
                try:
                    q.put_nowait(event)
                except Exception:
                    # Full or broken subscriber (typical: backgrounded mobile
                    # tab whose TCP is stalled). Drop it so a stuck phone
                    # cannot silently eat the next 1000 events.
                    dead.append(q)
            for q in dead:
                try:
                    self.subscribers.remove(q)
                except ValueError:
                    pass

    def _obs_forward(self, kind: str, event: dict) -> None:
        """OBSLOG_v1: copy the session events that describe health (not content) into the global
        log, tagged with sid/provider, so one stream shows service and session state together."""
        try:
            text = str(event.get("text") or "")
            if kind == "system":
                if " started model=" in text:
                    obslog.event("agent.spawn", sid=self.sid, provider=self.provider, model=self.model,
                                 agent_pid=getattr(self.proc, "pid", None), standby="warm standby" in text)
                elif event.get("key") in LOOP_NOTICE_KEYS:   # by key, never by the words
                    obslog.event("turn.loop_notice", lvl="warn", sid=self.sid, provider=self.provider, msg=text[:300])
                elif event.get("key") == "srv.turn_closed":
                    obslog.event("turn.quiet_close", lvl="warn", sid=self.sid, provider=self.provider, msg=text[:300])
                return
            lvl = "warn" if kind in ("error", "session_heavy") else "info"
            extra = {k: event.get(k) for k in ("reason", "level", "queue_len", "new_session_id", "weight") if event.get(k) is not None}
            obslog.event("session." + kind, lvl=lvl, sid=self.sid, provider=self.provider, model=self.model,
                         msg=text[:500], **extra)
        except Exception:  # noqa: BLE001
            pass

    def _host_history_digest(self, max_turns: int = 8, per_turn: int = 700, total: int = 5000,
                             header: str = "(The agent process restarted and its memory did not carry over. Below is the recent talk from the screen record.)") -> str:
        """The visible history, trimmed -- no model call, so it is instant and free."""
        me, ut = display_name(), user_title()
        rows = []
        for h in self.history:
            role, text = h.get("role"), (h.get("text") or "").strip()
            if role not in ("user", "assistant") or not text:
                continue
            text = re.sub(r"\n{3,}", "\n\n", text)
            rows.append(f"{ut if role == 'user' else me}: " + (text[:per_turn] + " …" if len(text) > per_turn else text))
        body = "\n".join(rows[-max_turns:])
        if len(body) > total:
            body = "…" + body[-total:]
        return header + "\n" + body

    # ---- runaway-turn protection (loop_guard.py) ------------------------------------------
    def _observe_agent_step(self, obj: dict) -> None:
        """Count finished tool calls; warn when a pattern repeats, stop the turn when it clearly
        loops. Independent of what the UI shows: the tool display de-duplicates repeats, which is
        exactly why the 2026-09-20 loop was invisible."""
        if self._stop_requested or self._loop_stopping:
            return
        calls = extract_tool_steps(obj)
        phases = getattr(self, "_turn_phases", None)
        if calls and phases is not None and phases.get("first_tool_ms") is None and getattr(self, "_turn_t0", None):
            phases["first_tool_ms"] = round((time.time() - self._turn_t0) * 1000, 1)   # telemetry tl/D
        for name, params, _ in calls:
            write_guard.check(self, name, params, REPO_ROOT)
            if not (is_read_only(name) or str((params or {}).get("action") or "") in regenerate.READ_ACTIONS):
                self._turn_effects = True   # REGENERATE_v1 D3
        if calls and self.msg_queue:
            self._steer_at_boundary()  # a tool step just finished: the safe moment to take a waiting message
        for name, params, output in calls:
            v = self._loop_guard.observe(name, params, output)
            if v is None:
                continue
            if v.rule == "budget":
                self._budget_hit_at = time.time()   # HANDOFF_PARTIAL_v1: a handoff ending in it is partial
            if v.level == "warn":
                if self._can_notice_loop():
                    self._notice_loop(v, write_guard.loop_evidence(v, params, output))
                    return
                if not self._loop_warned:
                    self._loop_warned = True
                    self._emit({"event": "system", **i18n.msg("srv.budget_warn" if v.rule == "budget" else "srv.loop_warn", verdict=v.msg),
                                "evidence": write_guard.loop_evidence(v, params, output)})
            elif v.rule == "budget":
                self._auto_stop(
                    event={"event": "stopped", **i18n.msg("srv.budget_stopped", verdict=v.msg),
                           "evidence": write_guard.loop_evidence(v, params, output)},
                    hint=f"The last turn went over its budget ({self._loop_guard.calls} tool calls, "
                         f"{self._loop_guard.read_bytes // 1000} KB read) and was stopped. Do not read the same way "
                         f"again: sum up what you know, hand a large code change over with delegate, or ask how to go on.")
                return
            else:
                self._auto_stop(
                    event={"event": "stopped", **i18n.msg("srv.loop_stopped_after_notice" if self._loop_noticed else "srv.loop_stopped", verdict=v.msg),
                           "evidence": write_guard.loop_evidence(v, params, output)},
                    hint=f"The last turn repeated the same work ({v.text}) and was stopped. Do not do it the same way again: "
                         f"change approach (read a large file in parts, use a search tool such as grep, or sum up and ask), "
                         f"briefly sum up where things stand and ask how to go on.")
                return

    def _can_notice_loop(self) -> bool:
        """Once per user turn, on agy only (the one provider that can be resumed with its memory intact),
        and never over a message the user already has waiting -- that one is delivered by the steer path."""
        with self.lock:
            return (not self._loop_noticed and not self.msg_queue and not self._steering and self.busy
                    and self._can_steer_at_boundary())

    def _notice_loop(self, v, evidence: dict) -> None:
        """A repeat crossed its warning threshold: tell the agent to change course instead of only warning
        the operator. Same interrupt-at-a-step-boundary-and-resume as a steer, so nothing done is lost."""
        with self.lock:
            if self._loop_stopping or self._loop_noticed:
                return
            self._loop_stopping = True
            self._loop_noticed = True
        self._emit({"event": "system", **i18n.msg("srv.loop_noticed", verdict=v.msg),
                    "evidence": {**evidence, "action": "notice"}})
        g = self._loop_guard   # the agent reads English numbers; v.text is the operator's line
        what = "%d tool calls, %d KB read" % (g.calls, g.read_bytes // 1000) if v.rule == "budget" else v.text
        threading.Thread(target=self._notice_loop_worker, args=(what, v.rule), daemon=True).start()

    def _notice_loop_worker(self, what: str, rule: str = "") -> None:
        rest = None
        try:
            with self.lock:
                if not self.busy:
                    return  # the turn ended meanwhile
                rest = list(self.msg_queue)
                self.msg_queue.clear()
            self.interrupt_current_turn(reason="loop", clear_queue=False)
            with self.lock:
                self.msg_queue[:] = rest + list(self.msg_queue)
                rest = None
            note = BUDGET_NOTICE.format(what=what) if rule == "budget" else LOOP_NOTICE.format(what=what, user=user_title())
            self._send_direct(note, notice=True)
        except Exception as e:  # noqa: BLE001 -- a failed notice must not leave the turn hanging silently
            if rest is not None:
                with self.lock:
                    self.msg_queue[:] = rest + list(self.msg_queue)
            self._emit({"event": "error", **i18n.msg("srv.loop_notice_failed", error=e)})
        finally:
            self._loop_stopping = False

    def _finish_turn(self, outcome: str = "result") -> None:
        """Every way a turn can end (result/error event, stop, steer, interrupt, child died, auto-stop) calls this
        once: the turn's log line, the write guard, the low-quota note, regenerate's bookkeeping. Never raises."""
        self._cached_summary = ""  # handover cache stale after new content
        self._obs_turn_end(outcome)
        write_guard.turn_end(self, REPO_ROOT, outcome)   # TREE_WATCH_v1
        if outcome == "result":
            quota_state.warn_low(self)   # qfr/D: a brain running low is said once, before it runs out
        if getattr(self, "_pending_push_react", False):
            import event_react
            event_react.notify_turn_end(self, outcome)
        regenerate.after_turn(self, outcome)   # REGENERATE_v1

    def _obs_turn_end(self, outcome: str) -> None:
        """OBSLOG_v1 turn.end: once per turn (keyed by turn_started_at), with duration and the
        agent's recent stderr when the turn did not end in a normal result."""
        try:
            started = float(getattr(self, "turn_started_at", 0) or 0)
            if outcome == "steer" or getattr(self, "_obs_turn_logged", None) == started:
                return
            self._obs_turn_logged = started
            ok = outcome == "result"
            fields = dict(sid=self.sid, provider=self.provider, model=self.model, outcome=outcome,
                          dur_s=round(_now() - started, 1) if started else None,
                          ttft_ms=getattr(self, "ttft_ms", None),
                          standby=bool(getattr(self, "_adopted_standby", False)))
            fields.update(self._turn_meters(started))   # telemetry tl/D
            if not ok:
                tail = list(getattr(self, "_stderr_tail", []) or [])[-8:]
                if tail:
                    fields["stderr_tail"] = tail
                hint = (getattr(self, "_err_msg_hint", "") or "").strip()
                if hint:
                    fields["error_hint"] = hint[:300]
            obslog.event("turn.end", lvl="info" if ok or outcome in ("stopped", "interrupted") else "warn", **fields)
        except Exception:  # noqa: BLE001 -- logging must never disturb a turn
            pass

    _TOKEN_FIELDS = (("input_tokens", "tok_in"), ("output_tokens", "tok_out"), ("thinking_tokens", "tok_think"),
                     ("cache_read_tokens", "tok_cache_read"), ("total_tokens", "tok_total"))

    def _turn_meters(self, started: float) -> Dict[str, Any]:
        """telemetry tl/D: this turn's tool calls and read KB (the loop guard counts them and resets at the next turn)
        and its tokens -- the adapters' canonical usage on the answers it added (normalize_usage), summed. Numbers only;
        a provider that reports no usage leaves the token fields out."""
        out: Dict[str, Any] = {}
        g = getattr(self, "_loop_guard", None)
        if g is not None:
            out["tool_calls"] = int(g.calls)
            out["read_kb"] = int(g.read_bytes // 1000)
        sums: Dict[str, int] = {}
        for h in reversed(self.history or []):
            ts = h.get("ts")
            if isinstance(ts, (int, float)) and started and ts < started - 1:
                break
            u = h.get("usage") if h.get("role") == "assistant" else None
            if isinstance(u, dict):
                for src, dst in self._TOKEN_FIELDS:
                    if isinstance(u.get(src), (int, float)):
                        sums[dst] = sums.get(dst, 0) + int(u[src])
        out.update(sums)
        for k, v in (getattr(self, "_turn_phases", None) or {}).items():   # prep_ms, spawn_ms, first_tool_ms
            if isinstance(v, (int, float)):
                out[k] = v
        return out

    # TURN_END_ORDER_v1: stop child only after terminal events are flushed.
    def _request_post_result_stop(self, status: str, err: str, duration: float) -> None:
        self._post_result_stop = {
            "status": status or "",
            "err": err or "",
            "duration": float(duration or 0),
        }

    def _run_post_result_stop(self) -> None:
        info = getattr(self, "_post_result_stop", None)
        self._post_result_stop = None
        if not info:
            return
        status = info.get("status") or ""
        err = info.get("err") or ""
        duration = float(info.get("duration") or 0)
        why = f"status={status or '?'}" + (f", error={err}" if err else "") + f", {int(duration)}s"
        self._loop_hint = f"The turn ended before the agent answered ({why}). The rest of the work stopped; it goes on from the next message."
        with self.lock:
            if self._loop_stopping:
                return
            self._loop_stopping = True
        # No user-facing emit — answer/error notice already flushed.
        threading.Thread(target=self._auto_stop_worker, daemon=True).start()

    def _end_unfinished_turn(self, status: str, err: str, duration: float, emit_error: bool = True) -> None:
        """agy ended the turn without an answer (error/timeout). At the print timeout it does so
        with an EMPTY result while the agent keeps working unseen in the background, so the child
        is stopped too -- the next message respawns it and resumes the conversation.

        QUOTA_ERR_DEDUP_v1: emit_error=False still stops the child (and sets the loop hint)
        but skips the error notice when finalize_turn already persisted notice:error.
        """
        why = f"status={status or '?'}" + (f", error={err}" if err else "") + f", {int(duration)}s"
        hint = f"The turn ended before the agent answered ({why}). The rest of the work stopped; it goes on from the next message."
        if emit_error:
            self._auto_stop(
                event={"event": "error", **i18n.msg("srv.turn_ended_early", why=why)},
                hint=hint,
            )
        else:
            # Quiet close: system only, no second error notice.
            self._auto_stop(
                event={"event": "system", **i18n.msg("srv.turn_closed", why=why)},
                hint=hint,
            )

    def _auto_stop(self, event: dict, hint: str) -> None:
        with self.lock:
            if self._loop_stopping:
                return
            self._loop_stopping = True
        self._loop_hint = hint
        self._emit(event)
        threading.Thread(target=self._auto_stop_worker, daemon=True).start()

    def _auto_stop_worker(self) -> None:
        try:
            self.stop(notify=False)
        finally:
            self._finish_turn("auto_stop")
            self._loop_guard.reset()
            self._loop_warned = False
            self._loop_stopping = False

    def _rewrite_artifact_paths(self, text: str) -> str:
        return _rewrite_artifact_paths(self.sid, self.conversation_id, text)

    def _artifact_dirs(self) -> List[Path]:
        """The provider's own folders for this conversation (media_handler registry)."""
        return _artifact_dirs(self.conversation_id)

    def _collect_new_images(self, since_ts: Optional[float] = None) -> list:
        return _collect_new_images(self.conversation_id, self.last_activity, since_ts)

    def _stage_image(self, src: Path) -> Optional[str]:
        return _stage_image(self.sid, src)

    def _append_images_markdown(self, text: str, since_ts: Optional[float] = None) -> str:
        return _append_images_markdown(self.sid, self.conversation_id, self.last_activity, text, since_ts)

    def weight(self) -> dict:
        soft_tokens, hard_tokens = self.adapter.soft_hard_tokens(self.model)
        return _session_weight(self.history, self.conversation_id, soft_tokens, hard_tokens)

    def _emit_heavy_if_needed(self, force: bool = False) -> dict:
        w = self.weight()
        level = w.get("level") or "ok"
        # NO_PRECOMPUTE_v1 (token-economy T10): no handover summary ahead of time. Every turn stales it (#613), so a
        # heavy session ran a full-context /compact after each turn (~150k tokens each, 2026-10-05) for a rotation
        # that mostly never came; the rotation makes its summary when it happens.
        if level == "ok":
            return w
        if force or self._heavy_warned_level != level:
            self._heavy_warned_level = level
            self._emit({
                "event": "session_heavy",
                "level": level,
                **(i18n.msg(w["message_key"], **(w.get("message_vars") or {})) if w.get("message_key") else i18n.msg("srv.session_heavy")),
                "weight": w,
            })
        return w

    def _successor_usable(self, sid: str) -> bool:
        """True if sid resolves to a non-hard session with meta on disk."""
        sid = (sid or "").strip()
        if not sid or sid == self.sid:
            return False
        try:
            meta_path = SESSIONS / sid / "meta.json"
            if not meta_path.exists():
                return False
            succ = REG.get(sid)
            w = succ.weight() if hasattr(succ, "weight") else {}
            if (w.get("level") or "ok") == "hard":
                return False
            return True
        except Exception:
            return False

    def _append_log_event(self, event: dict) -> None:
        try:
            entry = dict(event)
            entry.setdefault("ts", _now())
            path = self.meta_path.parent / "events.jsonl"
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

# REGISTRY_SPLIT_v1: the registry, the newest-session lookup and the meta.json summary cache live in
# session_registry.py; re-exported here so callers keep `from session import REG, Registry`.
from session_registry import Registry, _meta_touched, migrate_session_characters  # noqa: E402,F401

REG = Registry()


def _as_named_now(text: str, ts) -> str:
    """NAME_CHANGE_v1: talk from before a character was renamed, with today's names (character_names.as_of)."""
    try:
        import character_names
        return character_names.as_of(text, ts)
    except Exception:  # noqa: BLE001 -- a name note must never stop a turn
        return text


# Processes this server spawned (live pids, owned procs, caller, recycle, reap, standby maintenance) live in
# session_procs.py; re-exported here so callers keep `from session import owned_agent_procs`.
# Starting a child, reading its pipes, and stopping it is the SessionProcs mixin, imported above the class.
from session_procs import (  # noqa: E402
    _record_live_pids,
    _reap_sessions,
    _standby_maintenance_loop,
    caller_session,
    owned_agent_procs,
    recycle_agents,
)
