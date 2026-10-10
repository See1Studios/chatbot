"""In-memory session registry and AgentSession.

Extracted from server.py (monolith-split Phase 1). Processes this server spawned live in session_procs.py:
the functions are re-exported here, and starting a child, reading its pipes, and stopping it is the SessionProcs mixin.
Provider and model swap, the HTTP turn, the steer queue, sending a turn directly, ending a turn, the session's weight, and a repeated tool call live on the turn mixin; the handoff text, the restart digest, image paths, and the events sent to the screen live on the view mixin.
Reading and writing meta.json lives on the registry mixin. chatbot-ctl.sh guard_rlock AST-scans this file for AgentSession.lock = threading.RLock().
"""
from __future__ import annotations

import math
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple

from providers.adapters import get_adapter
from providers.adapters import _persona_system_prompt  # noqa: F401 -- the turn mixin reads _s()._persona_system_prompt
from private_engine import tension_meta
from instructions import build_instruction_bundle  # noqa: F401 -- session_turn reads it as _s().build_instruction_bundle (tests swap it here)
from identity import display_name, user_title  # noqa: F401 -- the view mixin reads _session().display_name and _session().user_title

import i18n  # noqa: F401 -- the view mixin reads _session().i18n
from telemetry import obslog  # noqa: F401 -- the registry mixin reads _s().obslog
import quota_state  # noqa: F401 -- QUOTA_STATE_v1 qfr/D; the turn mixin reads _s().quota_state
import regenerate  # noqa: F401 -- REGENERATE_v1; the turn mixin reads _s().regenerate
import write_guard  # noqa: F401 -- the turn mixin reads _s().write_guard
from turn_watchdog import TurnWatchdog
from session_view import SessionView   # split/C: what a session shows (reads SESSIONS, ADD_DIRS... from here)
from session_turn import SessionTurn   # split/C: running a turn, and swapping the provider or model (reads REG, get_adapter... from here)
from session_procs import SessionProcs  # starting the child and reading its pipes (patched names go through _s())
from loop_guard import LoopGuard
from loop_guard import extract_tool_steps, is_read_only  # noqa: F401 -- the turn mixin reads _s().extract_tool_steps and _s().is_read_only
from host_config import (
    ADD_DIRS,  # noqa: F401 -- session_procs reads it as _s().ADD_DIRS
    DATA,  # noqa: F401 -- tests retarget session.DATA; session_procs reads it as _s().DATA
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    ONESHOT_PROVIDER,
    HOME,  # noqa: F401 -- session_procs reads it as _s().HOME
    PERSISTED_LOG_KINDS,  # noqa: F401 -- the view mixin reads _session().PERSISTED_LOG_KINDS
    ROOT,
    SESSIONS,
    STATE_DIR,  # noqa: F401
    WORKSPACE,  # noqa: F401 -- session_procs reads it as _s().WORKSPACE
    _now,
    state_path,  # noqa: F401 -- session_procs reads it as _s().state_path
)
import repo_layout
# WRITE_GUARD_REPO_v1: tickets name repo-relative paths (`engine/x.py`); the write guard compares against the repo
# root, not the engine folder (after the layout move a claimed engine file read as `x.py` and was never covered).
REPO_ROOT = repo_layout.REPO
from artifact_manager import (
    _atomic_write_text,  # noqa: F401 -- server.py and the registry mixin read it from session
    _safe_artifact_rel,
    _safe_session_id,
)
from standby_pool import (
    STANDBY_POOL,  # noqa: F401 -- tests retarget session.STANDBY_POOL; session_procs reads it as _s().STANDBY_POOL
)
from session_weights import (
    _handoff_prompt,  # noqa: F401 -- the view mixin reads _session()._handoff_prompt; tests call session._handoff_prompt
    _session_weight,  # noqa: F401 -- the turn mixin reads _s()._session_weight
)
from media_handler import (
    _append_images_markdown,  # noqa: F401 -- the view mixin reads _session()._append_images_markdown
    _collect_new_images,  # noqa: F401 -- the view mixin reads _session()._collect_new_images
    _artifact_dirs,  # noqa: F401 -- the view mixin reads _session()._artifact_dirs
    _rewrite_artifact_paths,  # noqa: F401 -- the view mixin reads _session()._rewrite_artifact_paths
    _stage_image,  # noqa: F401 -- the view mixin reads _session()._stage_image
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


from session_registry import SessionMeta  # noqa: E402 -- meta.json load and save; Registry's defaults read names bound above


class AgentSession(SessionTurn, SessionView, TurnWatchdog, SessionProcs, SessionMeta):
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

# REGISTRY_SPLIT_v1: the registry, the newest-session lookup, the meta.json summary cache, and reading and
# writing one session's meta.json live in session_registry.py; re-exported here so callers keep
# `from session import REG, Registry`.
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
