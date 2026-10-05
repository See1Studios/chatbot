"""In-memory session registry, AgentSession, and standby pool.

Extracted from server.py (monolith-split Phase 1). chatbot-ctl.sh guard_rlock
AST-scans this file for AgentSession.lock = threading.RLock().
"""
from __future__ import annotations

import json
import math
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from providers.adapters import _persona_system_prompt, get_adapter
from private_engine import tension_meta, tension_step
from instructions import build_instruction_bundle
from identity import display_name, user_title

try:  # turn observation is best effort: a missing core module must never stop the host
    import evolution
except Exception:  # noqa: BLE001
    evolution = None
import obslog
import write_guard
from turn_watchdog import TurnWatchdog
from session_view import SessionView   # split/C: what a session shows (reads SESSIONS, ADD_DIRS... from here)
from session_turn import SessionTurn   # split/C: running a turn (reads REG, boot_notice... from here)
from loop_guard import LoopGuard, extract_tool_steps
import personal_turn
from host_config import (
    ADD_DIRS,
    ARTIFACTS_CACHE,
    DATA,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    ONESHOT_PROVIDER,
    HOME,
    INACTIVITY_ROTATE_SEC,
    PERSISTED_LOG_KINDS,
    ROOT,
    SESSIONS,
    WORKSPACE,
    _now,
)
from tool_format import _format_tool_call, _format_tool_result
from artifact_manager import (
    _atomic_write_text,
    _safe_artifact_rel,
    _safe_session_id,
)
from standby_pool import (
    STANDBY_POOL,
    _StandbyPool,
)
from session_weights import (
    _billed_tokens,
    _btw_prompt,
    _current_context_tokens,
    _handoff_prompt,
    _is_inquiry,
    _session_weight,
    _turn_billed,
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
_OBS_FORWARD = {"error", "stopped", "interrupted", "session_rotate", "session_heavy", "steer_queued", "system"}

STEER_MAX_WAIT_SEC = 90   # no boundary for this long (long reasoning, no tools): interrupt anyway
boot_notice = lambda sess: ""  # server.py hook: "[시스템 안내]" restart line, once per session per boot
LOOP_STOP_AFTER_NOTICE = 3   # repeats that still continue after the agent was told to change course -> stop
LOOP_NOTICE = ("같은 도구 호출을 반복하고 있습니다 ({what}). 새 정보가 없으니 여기서 멈추고, 지금까지 알게 된 것을 세 줄로 정리한 뒤 "
               "접근을 바꾸세요 (큰 파일은 StartLine/EndLine으로 나눠 읽거나 grep으로 필요한 부분만 찾기). 이미 끝낸 단계는 처음부터 "
               "다시 하지 말고, 정말 막혔을 때만 {user}께 물어보세요.")
BUDGET_NOTICE = ("This turn is over its budget ({what}): everything read is sent to the model again on every later "
                 "call. If this is a large code change, sum up what you found and hand it over with delegate; "
                 "otherwise stop here and answer with what you have. To read more, find the place with grep and "
                 "read only that range (StartLine/EndLine).")
STEER_HINT = ("직전 작업은 이 메시지를 반영하려고 도구 단계 사이에서 잠시 멈췄을 뿐, 취소된 것이 아닙니다. 이 메시지가 취소·변경을 "
              "분명히 요구하지 않는다면 하던 작업을 이어서 하면서 이 메시지의 지시를 반영하세요. 이미 끝낸 단계를 처음부터 다시 하지 마세요.")


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


def _standby_maintenance_loop() -> None:
    while True:
        try:
            STANDBY_POOL.ensure_warm()
        except Exception:
            pass
        try:
            _reap_sessions()
        except Exception:
            pass
        time.sleep(15)


def format_client_context(ctx: Optional[Dict[str, Any]]) -> str:
    if not isinstance(ctx, dict) or not ctx:
        return ""
    _num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    p = []
    lat, lon, acc = ctx.get("lat"), ctx.get("lon"), ctx.get("accuracy")
    if _num(lat) and _num(lon):
        p.append(f"위치 {lat:.4f}, {lon:.4f}" + (f" ±{int(acc)}m" if _num(acc) and acc > 0 else ""))
    tz = ctx.get("timezone")
    if isinstance(tz, str) and tz.strip():
        p.append(tz.strip()[:40])
    if ctx.get("is_mobile") is True:
        p.append("모바일")
    elif ctx.get("is_mobile") is False:
        p.append("데스크톱")
    if isinstance(dev := ctx.get("device"), str) and (d := dev.strip()) and d not in ("모바일", "데스크톱"):
        p.append(d[:30])
    batt = ctx.get("battery")
    if _num(batt):
        p.append(f"배터리{max(0, min(100, int(batt)))}%" + ("충전중" if ctx.get("charging") is True else ""))  # l10n-ok
    if isinstance(net := ctx.get("net_type"), str) and (n := net.strip()):
        p.append(f"네트워크:{n[:20]}")  # l10n-ok
    elif ctx.get("online") is True:
        p.append("온라인")  # l10n-ok
    elif ctx.get("online") is False:
        p.append("오프라인")  # l10n-ok
    resumed = ctx.get("resumed")
    if resumed is True:
        p.append("복귀")  # l10n-ok
    elif _num(resumed) and 0 < resumed < 100_000_000:
        p.append(f"복귀({int(resumed)}s 만에)")  # l10n-ok
    if isinstance(vis := ctx.get("visibility"), str) and (v := vis.strip()) and v != "visible":
        p.append("백그라운드")  # l10n-ok
    elif ctx.get("focused") is False:
        p.append("비활성탭")  # l10n-ok
    return "[클라이언트 환경: " + ", ".join(p) + "]" if p else ""


class AgentSession(SessionTurn, SessionView, TurnWatchdog):
    def __init__(self, sid: str, model: str = DEFAULT_MODEL, effort: str = "", provider: str = DEFAULT_PROVIDER):
        self.sid = sid
        self.provider = provider or DEFAULT_PROVIDER
        self.adapter = get_adapter(self.provider)
        # DEFAULT_MODEL names an agy/Gemini model -- only fall back to it for
        # agy itself; any other provider's adapter already treats an empty
        # model as "let the CLI pick its own default" (see build_args()).
        self.model = model or (DEFAULT_MODEL if self.provider == DEFAULT_PROVIDER else "")
        self.effort = effort or ""
        self.conversation_id: Optional[str] = None
        self.proc: Optional[subprocess.Popen] = None
        self._http_resp = None  # API-Provider plan: in-flight urlopen() response for transport_kind="http" adapters -- stop() closes this to cancel a streaming turn, since there's no self.proc to terminate()
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
        self.turn_started_at = 0.0
        self.pending_images: List[str] = []
        self._stderr_tail: List[str] = []
        # meta.json + artifacts/ live together under one per-session folder
        # (2026-09-16: previously a flat sessions/<sid>.json plus a wholly
        # separate artifacts/ tree keyed by conversation_id -- moved to this
        # so a session's own history and everything it generated travel
        # together as one self-contained unit).
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
        self._turn_marks: List[Tuple[Optional[int], str]] = []  # (user-turn index, kind) of error/stopped/interrupted events
        self._observed_turn_key = None  # the user turn already handed to evolution.on_turn_end
        self._turn_seq = 0  # bumped each http-transport turn so a stale watchdog can't stop a later turn
        self._loop_guard = LoopGuard()  # repeated-tool-call detector (loop_guard.py); reset every turn
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
                self.character = str(meta.get("character") or "")
                self.mode = meta.get("mode") if meta.get("mode") in ("private", "room") else "work"   # room: evt/E
                self.private_digested_ts = float(meta.get("private_digested_ts") or 0)
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
                "character": getattr(self, "character", "") or "",
                "mode": getattr(self, "mode", "work") or "work",
                "private_digested_ts": getattr(self, "private_digested_ts", 0.0) or 0.0,
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
                line = "쿼터·오류 확인 중…"
            if line:
                self.last_progress = line[:240]
            # SILENT_HANG_v1: tool start/result/progress heartbeats reset the idle
            # clock (not only assistant text). Long tools are fine while progress
            # continues. error_message is owned by QUOTA_FAILFAST — do not re-arm.
            if not is_err_msg:
                self._touch_turn_activity()
        elif kind in ("delta", "thinking"):
            # SILENT_HANG_v1: streaming assistant text -- or the brain's streamed reasoning -- resets the idle clock
            self._touch_turn_activity()
        elif kind in ("result", "error", "stopped"):
            self.last_progress = ""
            # QUOTA_FAILFAST_v1: real terminal event — cancel pending failfast
            self._cancel_error_message_failfast()
            # SILENT_HANG_v1: turn ended — cancel idle watchdog
            self._cancel_silent_hang()
        if (kind in ("error", "stopped") and event.get("notice") != "warn") or (kind == "interrupted" and event.get("reason") != "steer"):
            try:
                self._turn_marks.append((self._last_user_turn()[0], kind))
            except Exception:  # noqa: BLE001 -- observing must never disturb a turn
                pass
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
                elif text.startswith("⚠"):
                    obslog.event("turn.loop_notice", lvl="warn", sid=self.sid, provider=self.provider, msg=text[:300])
                elif text.startswith("턴 종료"):
                    obslog.event("turn.quiet_close", lvl="warn", sid=self.sid, provider=self.provider, msg=text[:300])
                return
            lvl = "warn" if kind in ("error", "session_heavy") else "info"
            extra = {k: event.get(k) for k in ("reason", "level", "queue_len", "new_session_id", "weight") if event.get(k) is not None}
            obslog.event("session." + kind, lvl=lvl, sid=self.sid, provider=self.provider, model=self.model,
                         msg=text[:500], **extra)
        except Exception:  # noqa: BLE001
            pass

    def _spawn(self, prompt: str = "") -> None:
        """`prompt` (Multi-Provider plan Phase 2): only meaningful for a
        one-shot exec provider (keeps_stdin_open=False) -- _send_direct()
        calls this directly with the turn's text instead of writing to a
        long-lived stdin, since that kind of CLI takes its prompt via argv/a
        file at spawn time and exits after the one turn."""
        self.stop(notify=False)
        self._stop_requested = False
        self._resume_or_reseed()
        adopted, adopted_conv_id = None, None
        if not self.conversation_id and self.model == DEFAULT_MODEL and not self.effort and self.adapter.keeps_stdin_open:
            adopted, adopted_conv_id = STANDBY_POOL.try_take()
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
            # the 2026-09-17 DEVLOG entry) -- but claude does the opposite:
            # verified live (2026-09-17) that `--resume <id>` on an id claude
            # has never seen fails the turn outright ("No conversation found
            # with session ID: ..."), so a provider that mints its own id
            # must start with conversation_id empty and let normalize_line
            # capture the real one from the first turn's response.
            if not self.conversation_id and not self.adapter.mints_own_conversation_id():
                self.conversation_id = str(uuid.uuid4())
                self.save_meta()
            args = self.adapter.build_args(self.model, self.effort, self.conversation_id, ADD_DIRS, prompt=prompt)
            env = self.adapter.build_env(HOME)
            env["CHATBOT_LIVE_AGENT"] = "1"
            self.proc = subprocess.Popen(
                args,
                cwd=str(WORKSPACE),
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
        _record_live_pids()

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
        whole chat (2026-09-20: "너 다른 프로세스야?"). If the id is not in agy's store, drop it
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
        self._emit({"event": "system", "text": "에이전트가 이전 대화를 기억하지 못해서, 다음 메시지에 지침과 최근 대화 요약을 다시 넣습니다."})

    def _host_history_digest(self, max_turns: int = 8, per_turn: int = 700, total: int = 5000,
                             header: str = "(에이전트 프로세스가 다시 시작되어 기억이 이어지지 않았습니다. 아래는 화면 기록의 최근 대화입니다.)") -> str:
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
        for name, params, _ in calls:
            write_guard.check(self, name, params, ROOT)
        if calls and self.msg_queue:
            self._steer_at_boundary()  # a tool step just finished: the safe moment to take a waiting message
        for name, params, output in calls:
            v = self._loop_guard.observe(name, params, output)
            if v is None:
                continue
            if v.level == "warn":
                if self._can_notice_loop():
                    self._notice_loop(v, write_guard.loop_evidence(v, params, output))
                    return
                if not self._loop_warned:
                    self._loop_warned = True
                    goes_on = "계속되면" if v.rule == "budget" else "계속 반복되면"   # l10n-ok
                    self._emit({"event": "system", "text": f"⚠ {v.text}. {goes_on} 자동으로 멈춥니다.",
                                "evidence": write_guard.loop_evidence(v, params, output)})
            elif v.rule == "budget":
                self._auto_stop(
                    event={"event": "stopped", "text": f"이번 턴이 예산을 넘어 자동으로 중단했습니다 — {v.text}",   # l10n-ok
                           "evidence": write_guard.loop_evidence(v, params, output)},
                    hint=f"The last turn went over its budget ({self._loop_guard.calls} tool calls, "
                         f"{self._loop_guard.read_bytes // 1000} KB read) and was stopped. Do not read the same way "
                         f"again: sum up what you know, hand a large code change over with delegate, or ask how to go on.")
                return
            else:
                after = " (방향을 바꾸라고 알린 뒤에도 계속돼서)" if self._loop_noticed else ""
                self._auto_stop(
                    event={"event": "stopped", "text": f"같은 도구 호출이 반복돼 자동으로 중단했습니다{after} — {v.text}",
                           "evidence": write_guard.loop_evidence(v, params, output)},
                    hint=f"직전 턴이 같은 작업을 반복하다({v.text}) 자동 중단됐습니다. 같은 방식을 되풀이하지 말고, 접근을 바꾸거나 "
                         f"(큰 파일은 범위를 나눠 읽기·grep 같은 검색 도구·요약 후 질문) 지금까지의 진행 상황을 짧게 정리해 어떻게 할지 물어보세요.")
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
        self._emit({"event": "system", "text": f"⚠ {v.text}. 방향을 바꾸라고 알리고 이어서 진행합니다.",
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
            self._emit({"event": "error", "text": f"방향 전환 알림을 보내지 못했습니다: {e}"})
        finally:
            self._loop_stopping = False

    def _observation_root(self) -> Path:
        # Derived from where this session's own files live (<data>/sessions/<sid>/meta.json), so a
        # test or a second instance with its own data directory never writes into another's.
        return self.meta_path.parent.parent.parent / "workspace" / "skill-observations"

    def _last_user_turn(self) -> Tuple[Optional[int], str]:
        """(index, text) of the newest user message that has actually been sent, else (None, "")."""
        for i in range(len(self.history) - 1, -1, -1):
            h = self.history[i]
            if h.get("role") == "user" and not h.get("queued"):
                return i, str(h.get("text") or "")
        return None, ""

    def _finish_turn(self, outcome: str = "result") -> None:
        """Every way a turn can end (result/error event, stop, steer, interrupt, child died, auto-stop)
        calls this once; the observation logic itself lives in evolution.on_turn_end. Best effort: it
        takes no lock, does one small file append, and never raises. A user turn is handed over once,
        so two paths ending the same turn do not record it twice. `outcome == "steer"` (the user adding
        an instruction mid-turn) only clears the marks."""
        self._cached_summary = ""  # handover cache stale after new content
        self._obs_turn_end(outcome)
        write_guard.turn_end(self, ROOT, outcome)   # TREE_WATCH_v1
        try:
            idx, text = self._last_user_turn()
            marks = [k for i, k in self._turn_marks if i == idx]
            self._turn_marks = []
            if evolution is None or outcome == "steer" or idx is None:
                return
            key = (idx, self.history[idx].get("ts"))
            if key == self._observed_turn_key or personal_turn.is_marked(self.meta_path.parent.parent, self.sid, key[1]):
                return   # once per turn; a personal turn is never an observation candidate (PERSONAL_TURN_v1)
            self._observed_turn_key = key
            evolution.on_turn_end(ROOT, self._observation_root(), self.sid, self.provider, outcome, marks, text)
        except Exception:  # noqa: BLE001
            pass

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
                          standby=bool(getattr(self, "_adopted_standby", False)))
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
        why = f"status={status or '?'}" + (f", error={err}" if err else "") + f", {int(duration)}초"
        self._loop_hint = (
            f"에이전트가 답을 내기 전에 턴이 끝났습니다({why}). "
            "남은 작업은 멈췄고, 다음 메시지부터 이어서 합니다."
        )
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
        but skips the Korean error notice when finalize_turn already persisted notice:error.
        """
        why = f"status={status or '?'}" + (f", error={err}" if err else "") + f", {int(duration)}초"
        hint = f"에이전트가 답을 내기 전에 턴이 끝났습니다({why}). 남은 작업은 멈췄고, 다음 메시지부터 이어서 합니다."
        if emit_error:
            self._auto_stop(
                event={"event": "error", "text": f"에이전트가 답을 내기 전에 턴이 끝났습니다 ({why}). 남아서 돌 수 있는 작업은 멈췄어요 — 메시지를 보내면 이어서 합니다."},
                hint=hint,
            )
        else:
            # Quiet close: system only, no second error notice.
            self._auto_stop(
                event={"event": "system", "text": f"턴 종료 ({why})"},
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

    def _read_stdout(self, proc: Optional[subprocess.Popen] = None) -> None:
        # Bound to ONE child. A steer/interrupt kills the child and respawns within milliseconds,
        # and _spawn() clears _stop_requested -- so without knowing which child this thread reads,
        # leftovers in the OLD pipe were processed as if they were the new turn, and the old
        # child's exit could switch the NEW turn's busy flag off.
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
                    err_text = "에이전트 프로세스가 종료되었습니다."
                    # Persist what streamed in before the child died -- the live view
                    # already finalizes this same draft into a normal bubble, so a
                    # reload silently erasing it would be a desync (SESSION_DESYNC_GAPFIX_v2).
                    draft = (self.current_text or "").strip()
                    if draft:
                        self.history.append({"role": "assistant", "text": draft, "ts": _now()})
                    self.history.append({"role": "assistant", "text": err_text, "notice": "error", "ts": _now()})
                    self.save_meta()
                    self.current_text = ""
                    self._emit({"event": "error", "text": err_text})
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
            _record_live_pids()
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

    def _history_to_openai_messages(self, last_user_override: Optional[str] = None) -> List[dict]:
        """API-Provider plan Phase 1: role/text replay of self.history, plus
        a leading `role:"system"` message from `_persona_system_prompt()`
        (fixed 2026-09-18 -- this used to have none at all). Process
        providers get the same bundle as a first-turn preamble from
        _send_direct(); OpenAIDialectAdapter is a stateless HTTP call, so the
        system message is its only persistent channel -- confirmed live that
        The persona answered in flat, personaless tone on OmniRoute without it. No tool_calls/tool-result reconstruction (that's Phase 2, once
        the tool loop exists and needs its own turns represented here too).
        Queued messages not yet sent (`queued: True`) are intentionally
        skipped -- they aren't part of the conversation the model has "seen" yet.

        `last_user_override`: self.history stores the raw display text, but
        _send_direct() may have built a handoff-wrapped `stdin_content` for
        the just-appended user turn (provider swap / session rotation --
        same mechanism the CLI adapters get via format_stdin(stdin_content)).
        Swapping it in here only for the final history entry keeps the
        wire-sent turn consistent with what CLI providers actually receive,
        without persisting the wrapper text into history itself."""
        msgs: List[dict] = []
        system_text = _persona_system_prompt(getattr(self, "mode", "work"), getattr(self, "character", ""), self.history)
        if system_text:
            msgs.append({"role": "system", "content": system_text})
        # Bare HTTP call has no CLI runtime telling the model what it
        # actually is (agy/claude/grok/codex get this for free from their
        # own process context) -- without it, "너는 무슨 모델이니" on an
        # omniroute session got answered by guessing/pattern-matching the
        # AGENTS.md harness list, which reads DEFAULT_PROVIDER=agy most
        # prominently and answered "Antigravity(agy)" even while this
        # session's actual provider/model was omniroute/auto-best-free
        # (live-observed 2026-09-18, session 20260918-193213-e30f27).
        msgs.append({
            "role": "system",
            "content": f"[런타임 정보] 이 세션의 실제 백엔드는 provider={self.provider}, model={self.model}.",
        })
        last_idx = len(self.history) - 1
        for i, h in enumerate(self.history):
            role = h.get("role")
            if role not in ("user", "assistant"):
                continue
            if h.get("queued"):
                continue
            text = _as_named_now(h.get("text") or "", h.get("ts"))   # NAME_CHANGE_v1: older talk, today's names
            if i == last_idx and role == "user" and last_user_override is not None:
                text = last_user_override
            if not text:
                continue
            msgs.append({"role": role, "content": text})
        return msgs

    def _run_http_turn(self, stdin_content: str, seq: Optional[int] = None) -> None:
        """API-Provider plan: transport_kind="http" counterpart to
        _spawn()+_read_stdout() -- runs in its own background thread (see
        _send_direct()), no process/stdin/stdout involved at all."""
        if seq is None:
            seq = self._turn_seq
        messages = self._history_to_openai_messages(last_user_override=stdin_content)
        try:
            for ev in self.adapter.stream_turn(self, messages, seq=seq):
                if self._turn_seq != seq or self._stop_requested:
                    break
                self._handle_events([ev])
        except Exception as e:
            if self._turn_seq == seq and not self._stop_requested:
                self._handle_events([{"event": "error", "text": f"API 호출 실패: {e}"}])

    def _http_turn_watchdog(self, seq: int) -> None:
        """Force-stops an http-transport turn that runs past
        OpenAIDialectAdapter.HTTP_TURN_TIMEOUT_SEC -- see that constant's
        comment (server.py, near MAX_TOOL_HOPS) for why _stream_once()'s
        own per-read timeout doesn't catch this on its own (OmniRoute
        keepalive deltas reset it indefinitely, so a stalled upstream call
        can hang forever with session.busy stuck True and no OS process for
        chatbot-ctl.sh's orphan-killer to ever see). `seq` pins this
        watchdog to the exact turn that spawned it so it can't fire against
        a later turn that reused this session after this one already
        finished normally."""
        timeout_sec = getattr(self.adapter, "HTTP_TURN_TIMEOUT_SEC", 180)
        time.sleep(timeout_sec)
        with self.lock:
            if self.adapter.transport_kind != "http" or self._turn_seq != seq or not self.busy:
                return
        self.stop(notify=False)
        minutes = timeout_sec // 60
        text = f"⏱️ 응답이 {minutes}분 넘게 안 와서 자동으로 중단했어요. 다시 시도해 주세요."
        with self.lock:
            self.history.append({"role": "assistant", "text": text, "ts": _now()})
            self.save_meta()
        self._emit({"event": "error", "text": text})

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            if _redact_line(line):
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

    def _dispatch_queued(self) -> None:
        time.sleep(0.35)
        with self.lock:
            if not getattr(self, "msg_queue", []):
                return
            next_text, next_mid = self.msg_queue.pop(0)
        self._send_direct(next_text, next_mid)

    # ---- steer: apply a message that arrived mid-turn at the next tool-step boundary -----------
    def _can_steer_at_boundary(self) -> bool:
        a = self.adapter
        return bool(getattr(a, "supports_steer", False)) and getattr(a, "transport_kind", "") == "process" and bool(getattr(a, "keeps_stdin_open", False))

    def _queue_steer(self, text: str, client_mid: str) -> None:
        with self.lock:
            if not self.msg_queue:
                self._steer_since = _now()
            self.msg_queue.append((text, client_mid))
            n = len(self.msg_queue)
        self._emit({"event": "steer_queued", "queue_len": n,
                    "text": "새 지시를 받았어요 — 지금 진행 중인 단계가 끝나면 바로 반영합니다."})
        timer = threading.Timer(STEER_MAX_WAIT_SEC, self._steer_at_boundary, kwargs={"forced": True})
        timer.daemon = True
        timer.start()

    def _steer_at_boundary(self, forced: bool = False) -> None:
        """Called at every finished tool step (and by a timer as the fallback). If a message is
        waiting and the turn is still running, hand it to a worker thread -- never stop the child
        from the thread that reads its stdout."""
        with self.lock:
            if self._steering or not self.msg_queue or not self.busy:
                return
            if forced and _now() - self._steer_since < STEER_MAX_WAIT_SEC - 1:
                return  # a newer turn's message; its own timer will come
            self._steering = True
        threading.Thread(target=self._steer_worker, daemon=True).start()

    def _proc_alive(self) -> bool:
        """"Is the turn actually still running" -- for process-transport
        adapters that's a real OS process; an http-transport adapter
        (API-Provider plan) never has self.proc at all, so self.busy IS the
        only liveness signal for it (set True right before the streaming
        call starts, False when stream_turn() yields its result/error, or
        when stop() cancels it). Centralized here so the four call sites
        that used to inline `self.proc and self.proc.poll() is None` don't
        each need their own transport_kind branch."""
        if self.adapter.transport_kind != "process":
            return self.busy
        return bool(self.proc and self.proc.poll() is None)

    def weight(self) -> dict:
        soft_tokens, hard_tokens = self.adapter.soft_hard_tokens(self.model)
        return _session_weight(self.history, self.conversation_id, soft_tokens, hard_tokens)

    @staticmethod
    def _native_compact(provider: str, cid: str) -> str:
        """That provider's own summary of conversation `cid` (adapter hook; "" when it has none)."""
        try:
            return get_adapter(provider).native_compact(cid)
        except Exception:  # noqa: BLE001
            return ""

    def _refine_swap_handoff(self, gen: int, old_provider: str, cid: Optional[str]) -> None:
        """SWAP_ASYNC_HANDOFF_v1: replace the instant swap handoff with a model-made summary -- agy's
        /compact of the OLD conversation when there is one, else the dialogue summary -- unless the
        handoff was already sent or another swap happened meanwhile."""
        t0 = time.monotonic()
        base = self._native_compact(old_provider, cid) if cid else ""
        if not base:
            base = self._dialogue_summary_fallback()
        with self.lock:
            stale = getattr(self, "_swap_gen", 0) != gen or self.handoff_injected
            if base and not stale:
                self.handoff_summary = self._with_last_exchange(base)
        if base and not stale:
            self.save_meta()
        obslog.event("session.handoff_refined", sid=self.sid, provider=self.provider,
                     dur_s=round(time.monotonic() - t0, 1), used=bool(base and not stale),
                     reason="ok" if base and not stale else ("stale" if stale else "compact_failed"))

    def _recent_turns(self, max_turns: int, max_hops: int = 10) -> List[dict]:
        """The last `max_turns` user/assistant turns of this conversation, oldest first: this session's, then back
        along predecessor_session_id. Sessions here are often 2-8 turns long, so one session alone was not enough
        (#613). Read-only; a missing or broken predecessor ends the walk."""
        turns = [h for h in self.history if h.get("role") in ("user", "assistant")]
        pred, seen = str(getattr(self, "predecessor_session_id", "") or ""), {self.sid}
        while len(turns) < max_turns and pred and pred not in seen and len(seen) <= max_hops:
            seen.add(pred)
            try:
                meta = json.loads((SESSIONS / pred / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                break
            turns = [h for h in (meta.get("history") or []) if isinstance(h, dict)
                     and h.get("role") in ("user", "assistant")] + turns
            pred = str(meta.get("predecessor_session_id") or "")
        return turns[-max_turns:]

    def _with_last_exchange(self, base: str, *, max_turns: int = 8, max_chars: int = 3000) -> str:
        """Append recent verbatim exchanges to *base* (the compressed summary).

        Preserves up to *max_turns* recent user/assistant turns (3~4 exchanges), across the session chain, within
        *max_chars*, so the successor session gets a high-fidelity anchor of recent conversation on top of the
        compressed long-range context.
        """
        recent = self._recent_turns(max_turns)
        if not recent:
            return base
        chosen: List[str] = []
        total = 0
        for h in reversed(recent):
            role = h.get("role")
            label = user_title() if role == "user" else display_name()
            text = str(h.get("text") or "")[:1200]
            line = f"{label}: {text}"
            if total + len(line) > max_chars and chosen:
                break
            chosen.append(line)
            total += len(line)
        if not chosen:
            return base
        lines = list(reversed(chosen))
        prefix = f"{base.rstrip()}\n\n" if (base or "").strip() else ""
        return f"{prefix}[최근 주고받은 대화 원문]\n" + "\n".join(lines) + "\n"

    def _dialogue_summary_fallback(self, max_turns: int = 8) -> str:
        """Lightweight custom-prompt summary of the last N dialogue turns --
        used when native /compact isn't available yet or fails/times out."""
        dialogue = []
        with self.lock:
            for h in self.history:
                role = h.get("role")
                text = str(h.get("text") or "").strip()
                if not text:
                    continue
                if role in ("user", "assistant"):
                    dialogue.append(f"{role}: {text[:250]}")
                elif role == "btw":
                    dialogue.append(f"user(btw): {str(h.get('query') or '')[:100]} -> {text[:150]}")

        if not dialogue:
            return ""
        if len(dialogue) <= 1:
            return dialogue[0]

        recent_dialogue = dialogue[-max_turns:]
        dialogue_blob = "\n".join(recent_dialogue)

        prompt = _handoff_prompt(dialogue_blob)

        r = _oneshot(prompt, 12)
        if r and r.get("text"):
            return r["text"]

        # Deterministic fallback when no provider answered
        user_turns = [h.get("text") for h in self.history if h.get("role") == "user"]
        asst_turns = [h.get("text") for h in self.history if h.get("role") == "assistant"]
        last_u = str(user_turns[-1] if user_turns else "")[:120]
        last_a = str(asst_turns[-1] if asst_turns else "")[:120]
        return f"- 최근 {user_title()} 지시: {last_u}\n- 최근 답변 요약: {last_a}"

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
                "text": w.get("message_ko") or "세션이 길어져서 느려질 수 있어요. 새 채팅을 권장합니다",
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

    def _send_direct(self, text: str, client_mid: str = "", client_context: Optional[Dict[str, Any]] = None,
                     notice: bool = False, event_type: str = "") -> None:
        """`notice=True`: `text` is a host note to the agent (a loop notice), not something the user said --
        it is neither shown as their message nor kept in history, and it does not start a new user turn.
        A turn that fails to start (spawn error, dead pipe) never leaves busy stuck; the caller gets the error."""
        try:
            self._start_turn(text, client_mid, client_context, notice, event_type)
        except Exception:
            with self.lock:
                self.busy = False
            self._finish_turn("error")
            raise

    def _stop_for_swap(self, what: str) -> None:
        """Stop the live process because the provider/model is being swapped.

        A swap is not a user-requested stop, so it must not print "작업이
        중지되었습니다" -- that notice appeared, twice per switch (provider, then
        model), every time someone clicked through the provider tray just to
        look at another provider's usage, even with nothing running. Only say
        something when a turn really was in flight, and say what happened;
        emitting "stopped" then is also what resets the UI's busy state."""
        was_busy = self.busy
        self.stop(notify=False)
        if was_busy:
            self._emit({"event": "stopped", "text": f"{what} 바꿔서 진행 중이던 작업을 중단했습니다."})

    def _remember_brain_choice(self) -> None:
        """Keep a user provider/model pick for this character and mode. The card stays the default."""
        cid = getattr(self, "character", "") or ""
        mode = getattr(self, "mode", "") or "work"
        if mode not in ("work", "private") or not cid:
            return
        try:
            import characters
            card = characters.load(cid)
            default = (characters.brains(card, mode) or [{}])[0]
            same = ((self.provider or "") == (default.get("provider") or "")
                     and (self.model or "") == (default.get("model") or ""))
            if same:
                characters.write_brain_override(cid, mode, None)
            else:
                characters.write_brain_override(cid, mode, {
                    "provider": self.provider, "model": self.model or "", "effort": self.effort or ""})
        except Exception:  # noqa: BLE001
            return

    def maybe_swap_model(self, model: str, remember: bool = True) -> None:
        """If `model` names a different model than this session is currently
        running, switch to it and stop the live process so the next send()
        respawns under the new model."""
        if model and model != self.model:
            self.model = model
            self._stop_for_swap("모델을")
            self.save_meta()
            if remember:
                self._remember_brain_choice()

    def maybe_swap_provider(self, provider: str, remember: bool = True) -> None:
        """If `provider` names a different CLI backend than this session is
        currently running, switch adapters and stop the live process --
        unlike a model swap, this ALSO clears conversation_id, since a
        session id from one CLI is meaningless to another (agy's
        --conversation uuid, claude/grok/codex's own self-minted session ids
        are all different id spaces). Call before maybe_swap_model() so a
        model name meant for the new provider isn't evaluated against the
        old one first.

        Clearing conversation_id means the next spawn starts with no
        --resume -- a brand-new CLI conversation that has never seen this
        session's history, even though self.history (and the UI) carries
        right on. Without a handoff, that new process would answer the very
        next message with zero awareness anything was discussed before
        (operator: "도중에 바뀌면 다시 해줘야하는 게 있을 것 같네" -- confirmed
        real, 2026-09-18). Reuse the same handoff_summary/handoff_injected
        relay _send_direct() already does for /continue rotations, computed
        here (before conversation_id/provider are overwritten, since
        get_handover_summary() needs the OLD ones to decide whether agy's
        native /compact applies) -- use_cache=False because, unlike a
        rotation (which retires the session), this session object stays
        alive afterward, so caching here would feed a stale summary to a
        later heavy-session rotation's own prewarm check."""
        if provider and provider != self.provider:
            # SWAP_ASYNC_HANDOFF_v1: never block the request on a model call (agy /compact or the
            # dialogue summary took 10-17 s and the UI gave up: log:rid:67b6f94c05ea). Hand over
            # the visible history now; a background thread swaps in the model-made summary.
            old_provider, old_cid = self.provider, self.conversation_id
            summary = self.get_handover_summary(use_cache=False, native=False)
            self._swap_gen = getattr(self, "_swap_gen", 0) + 1
            gen = self._swap_gen
            self.provider = provider
            self.adapter = get_adapter(provider)
            self.conversation_id = None
            self.model = self.effort = ""   # both belong to the old brain (grok effort=low broke agy -high, 09-30)
            self.handoff_summary = summary
            self.handoff_injected = False
            # New provider = new conversation that has never seen the persona
            # rules; without this reset it would run persona-less (2026-09-19).
            self.persona_injected = False
            self.persona_bundle_hash = ""
            self._stop_for_swap("제공자를")
            self.save_meta()
            if remember:
                self._remember_brain_choice()
            if self.history:
                threading.Thread(target=self._refine_swap_handoff, args=(gen, old_provider, old_cid), daemon=True).start()

    def stop(self, notify: bool = True) -> None:
        # Set before killing the process -- a just-terminated agy process can
        # still have already-flushed output sitting in its stdout pipe, and
        # _read_stdout()'s loop would otherwise keep reading and emitting
        # that (including what looks like a genuine "result" event, with
        # stale/reused usage stats) after the user explicitly asked to stop,
        # making it look like stop did nothing or a new answer appeared
        # right after (operator: "작성 중인 상태에서 중지같은 게 안되네").
        self._stop_requested = True
        self._cancel_silent_hang()
        was_busy = self.busy
        proc = self.proc
        self.proc = None
        http_resp = self._http_resp
        self._http_resp = None
        with self.lock:
            if hasattr(self, "msg_queue"):
                self.msg_queue.clear()
            self.busy = False
        if proc:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            # CODEX_PROC_v1: if we spawned with start_new_session, proc is the
            # session leader (pgid==pid) — kill the whole group so a codex
            # native child cannot outlive the node wrapper. If pgid!=pid
            # (legacy child from before this fix), fall back to terminate()
            # so we never SIGTERM the chatbot server's own process group.
            try:
                import signal as _signal
                pgid = os.getpgid(proc.pid)
                if pgid == proc.pid:
                    os.killpg(pgid, _signal.SIGTERM)
                else:
                    proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                # CODEX_PROC_v1: escalate the same way -- killpg when we're the session
                # leader, so an unresponsive-to-SIGTERM codex native child doesn't
                # outlive the node wrapper here either (mirrors adapters.py's
                # _fetch_codex_rate_limits cleanup).
                try:
                    if pgid == proc.pid:
                        os.killpg(pgid, _signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=1)
                    except Exception:
                        pass
        if http_resp:
            # API-Provider plan: no process to terminate -- closing the
            # in-flight urlopen() response's socket is what unblocks
            # stream_turn()'s `for raw_line in resp:` read loop in its
            # background thread, the http-transport equivalent of
            # proc.terminate() above.
            try:
                http_resp.close()
            except Exception:
                pass
        if notify:
            self._emit({"event": "stopped", "text": f"{user_title()}의 요청으로 작업이 중지되었습니다."})
            if was_busy:
                self._finish_turn("stopped")
        _record_live_pids()

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
from session_registry import (  # noqa: E402
    Registry, _LIVE_SID_RE, _META_INDEX, _META_INDEX_LOCK, _character_id, _first_brain, _live_sid, _meta_summaries,
    _meta_summary, _meta_touched, _probe_meta, migrate_session_characters,
)

REG = Registry()


def _record_live_pids() -> None:
    try:
        pids = []
        if "STANDBY_POOL" in globals() and STANDBY_POOL._proc and STANDBY_POOL._proc.poll() is None:
            pids.append(STANDBY_POOL._proc.pid)
        if "REG" in globals():
            try:
                with REG.lock:
                    sessions = list(REG.sessions.values())
                for s in sessions:
                    with s.lock:
                        if s.proc and s.proc.poll() is None:
                            pids.append(s.proc.pid)
            except Exception:
                pass
        _atomic_write_text(DATA / "live_pids.json", json.dumps(pids))
    except Exception:
        pass



def _as_named_now(text: str, ts) -> str:
    """NAME_CHANGE_v1: talk from before a character was renamed, with today's names (character_names.as_of)."""
    try:
        import character_names
        return character_names.as_of(text, ts)
    except Exception:  # noqa: BLE001 -- a name note must never stop a turn
        return text

def owned_agent_procs() -> Dict[int, dict]:
    """pid -> {owner, sid, busy} for every live process this server spawned
    (standby + session children), for accounts.snapshot(). Reads `s.proc`
    without taking `s.lock` on purpose -- a single reference read, and this
    runs on a GET handler where lock re-entry has deadlocked before (see
    docs/EMERGENCY.md)."""
    out: Dict[int, dict] = {}
    with STANDBY_POOL._lock:
        p = STANDBY_POOL._proc
        if p is not None and p.poll() is None:
            out[p.pid] = {"owner": "standby"}
    with REG.lock:
        sessions = list(REG.sessions.values())
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
    me = os.getpid()
    pid = platform_compat.tcp_socket_pid(client_port, server_port, sorted(platform_compat.child_pids({me})))
    if pid is None:
        return "", ""
    argv = platform_compat.proc_cmdline(pid)
    name = os.path.basename(argv[0]) if argv else ""
    if pid == me:
        return (claimed if claimed and REG.peek(claimed) is not None else ""), "host"
    owned = {p: v["sid"] for p, v in owned_agent_procs().items() if v.get("sid")}
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
    recycled, skipped = [], []
    owned = owned_agent_procs()
    for pid in pids:
        info = owned.get(pid)
        if not info:
            continue
        if info["owner"] == "standby":
            if STANDBY_POOL.discard():
                recycled.append(pid)
            continue
        if info.get("busy"):
            skipped.append(pid)
            continue
        with REG.lock:
            sess = REG.sessions.get(info["sid"])  # not REG.get(): that creates
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
    now = _now()
    live_pids = []
    with STANDBY_POOL._lock:
        if STANDBY_POOL._proc is not None and STANDBY_POOL._proc.poll() is None:
            live_pids.append(STANDBY_POOL._proc.pid)

    with REG.lock:
        sessions = list(REG.sessions.values())

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
                        sess._emit({"event": "error", "text": "에이전트 프로세스가 종료되었습니다."})
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
                        with REG.lock:
                            REG.sessions.pop(sess.sid, None)
                    else:
                        live_pids.append(sess.proc.pid)
                else:
                    live_pids.append(sess.proc.pid)

    for sess in died:
        sess._finish_turn("process_died")
    try:
        _atomic_write_text(DATA / "live_pids.json", json.dumps(live_pids))
    except Exception:
        pass


