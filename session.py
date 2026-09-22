"""In-memory session registry, AgySession, and standby pool.

Extracted from server.py (monolith-split Phase 1). chatbot-ctl.sh guard_rlock
AST-scans this file for AgySession.lock = threading.RLock().
"""
from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from adapters import _persona_system_prompt, get_adapter
from instructions import build_instruction_bundle
from identity import display_name, user_title

try:  # turn observation is best effort: a missing core module must never stop the host
    import evolution
except Exception:  # noqa: BLE001
    evolution = None
from loop_guard import LoopGuard, extract_tool_steps, normalize
from host_config import (
    ADD_DIRS,
    AGY,
    ARTIFACTS_CACHE,
    DATA,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
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
    _conversation_db_path,
    _current_context_tokens,
    _handoff_prompt,
    _is_inquiry,
    _session_weight,
    _turn_billed,
)
from media_handler import (
    _append_images_markdown,
    _collect_new_images,
    _conversation_brain_dir,
    _rewrite_artifact_paths,
    _stage_image,
)

# A message sent while an agy turn is running is accepted at once and applied at the next
# tool-step boundary (steer). agy itself cannot take a message mid-turn: measured 2026-09-20,
# a second stdin line only QUEUES and runs after the current turn ends (agy.md A41).
STEER_MAX_WAIT_SEC = 90   # no boundary for this long (long reasoning, no tools): interrupt anyway
LOOP_STOP_AFTER_NOTICE = 3   # repeats that still continue after the agent was told to change course -> stop
LOOP_NOTICE = ("같은 도구 호출을 반복하고 있습니다 ({what}). 새 정보가 없으니 여기서 멈추고, 지금까지 알게 된 것을 세 줄로 정리한 뒤 "
               "접근을 바꾸세요 (큰 파일은 StartLine/EndLine으로 나눠 읽거나 grep으로 필요한 부분만 찾기). 이미 끝낸 단계는 처음부터 "
               "다시 하지 말고, 정말 막혔을 때만 {user}께 물어보세요.")
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
    parts = []
    lat = ctx.get("lat")
    lon = ctx.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        parts.append(f"위치 {lat:.4f}, {lon:.4f}")
    tz = ctx.get("timezone")
    if isinstance(tz, str) and tz.strip():
        parts.append(tz.strip()[:40])
    is_mobile = ctx.get("is_mobile")
    if is_mobile is True:
        parts.append("모바일")
    elif is_mobile is False:
        parts.append("데스크톱")
    dev = ctx.get("device")
    if isinstance(dev, str) and dev.strip() and dev.strip() not in ("모바일", "데스크톱"):
        parts.append(dev.strip()[:30])
    if not parts:
        return ""
    return "[클라이언트 환경: " + ", ".join(parts) + "]"


class AgySession:
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
            raise RuntimeError('AgySession.lock must be RLock, not Lock')
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
                ts_list = [h.get("ts") for h in self.history if isinstance(h.get("ts"), (int, float))]
                if ts_list:
                    self.last_activity = max(ts_list)
                elif self.meta_path.exists():
                    self.last_activity = self.meta_path.stat().st_mtime
            except Exception as e:
                ts = int(time.time())
                corrupt_path = self.meta_path.with_name(f"{self.meta_path.name}.corrupt-{ts}")
                print(f"WARN corrupt meta.json for {self.sid}: {e}; renaming to {corrupt_path.name}", file=sys.stderr)
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
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            try:
                _atomic_write_text(self.meta_path, json.dumps(payload, ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"WARN: save_meta failed for {self.sid}: {e}", flush=True)

    def _emit(self, event: dict) -> None:
        self.last_activity = _now()
        kind = event.get("event")
        if kind in ("tool", "system"):
            line = (event.get("title") or event.get("text") or "").strip()
            if line:
                self.last_progress = line[:240]
        elif kind in ("result", "error", "stopped"):
            self.last_progress = ""
        if kind in ("error", "stopped") or (kind == "interrupted" and event.get("reason") != "steer"):
            try:
                self._turn_marks.append((self._last_user_turn()[0], kind))
            except Exception:  # noqa: BLE001 -- observing must never disturb a turn
                pass
        if kind in PERSISTED_LOG_KINDS:
            self._append_log_event(event)
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
            )
            grok_prompt = getattr(self.adapter, "_last_prompt_path", None)
            if grok_prompt:
                self.proc._grok_prompt_file = grok_prompt
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
        """Before every (re)spawn of an agy child. agy resumes `--conversation <id>` only if
        it has that conversation; otherwise it ignores the flag and starts an EMPTY one, which
        used to happen on every respawn (idle reap, swap, stop, crash) with nothing telling the
        agent -- so it lost its memory, persona and rules while the window still showed the
        whole chat (2026-09-20: "너 다른 프로세스야?"). If the id is not in agy's store, drop it
        and re-seed the next message with the rules and a digest of the visible history."""
        if self.adapter.id != "agy" or not self.conversation_id:
            return
        db = _conversation_db_path(self.conversation_id)
        if db is not None and db.exists():
            return
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
        self._emit({"event": "system", "text": "에이전트가 이전 대화를 기억하지 못해서, 다음 메시지에 지침과 최근 대화 요약을 다시 넣습니다냥."})

    def _host_history_digest(self, max_turns: int = 8, per_turn: int = 700, total: int = 5000) -> str:
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
        return "(에이전트 프로세스가 다시 시작되어 기억이 이어지지 않았습니다. 아래는 화면 기록의 최근 대화입니다.)\n" + body

    # ---- runaway-turn protection (loop_guard.py) ------------------------------------------
    def _observe_agent_step(self, obj: dict) -> None:
        """Count finished tool calls; warn when a pattern repeats, stop the turn when it clearly
        loops. Independent of what the UI shows: the tool display de-duplicates repeats, which is
        exactly why the 2026-09-20 loop was invisible."""
        if self._stop_requested or self._loop_stopping:
            return
        calls = extract_tool_steps(obj)
        if calls and self.msg_queue:
            self._steer_at_boundary()  # a tool step just finished: the safe moment to take a waiting message
        for name, params, output in calls:
            v = self._loop_guard.observe(name, params, output)
            if v is None:
                continue
            if v.level == "warn":
                if self._can_notice_loop():
                    self._notice_loop(v, self._loop_evidence(v, params, output))
                    return
                if not self._loop_warned:
                    self._loop_warned = True
                    self._emit({"event": "system", "text": f"⚠ {v.text}. 계속 반복되면 자동으로 멈춥니다냥.",
                                "evidence": self._loop_evidence(v, params, output)})
            else:
                after = " (방향을 바꾸라고 알린 뒤에도 계속돼서)" if self._loop_noticed else ""
                self._auto_stop(
                    event={"event": "stopped", "text": f"같은 도구 호출이 반복돼 자동으로 중단했습니다냥{after} — {v.text}",
                           "evidence": self._loop_evidence(v, params, output)},
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
        self._emit({"event": "system", "text": f"⚠ {v.text}. 방향을 바꾸라고 알리고 이어서 진행합니다냥.",
                    "evidence": {**evidence, "action": "notice"}})
        threading.Thread(target=self._notice_loop_worker, args=(v.text,), daemon=True).start()

    def _notice_loop_worker(self, what: str) -> None:
        try:
            with self.lock:
                if not self.busy:
                    return  # the turn ended meanwhile
                rest = list(self.msg_queue)
            self.interrupt_current_turn(reason="loop")
            with self.lock:
                self.msg_queue[:] = rest
            self._send_direct(LOOP_NOTICE.format(what=what, user=user_title()), notice=True)
        except Exception as e:  # noqa: BLE001 -- a failed notice must not leave the turn hanging silently
            self._emit({"event": "error", "text": f"방향 전환 알림을 보내지 못했습니다냥: {e}"})
        finally:
            self._loop_stopping = False

    @staticmethod
    def _loop_evidence(v, params: Optional[dict], output) -> dict:
        """What the repeated call actually asked and got, kept in the event log: without the arguments
        (line range) and the output's size/ends there is no telling a truncated read from a model habit."""
        try:
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(output)
        text = "" if output is None else text
        return {"rule": v.rule, "count": v.count, "tool": v.tool,
                "params": json.dumps(normalize(params), ensure_ascii=False, default=str)[:300],
                "output_chars": len(text), "output_head": text[:120], "output_tail": text[-120:] if len(text) > 120 else ""}

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
        try:
            idx, text = self._last_user_turn()
            marks = [k for i, k in self._turn_marks if i == idx]
            self._turn_marks = []
            if evolution is None or outcome == "steer" or idx is None:
                return
            key = (idx, self.history[idx].get("ts"))
            if key == self._observed_turn_key:
                return
            self._observed_turn_key = key
            evolution.on_turn_end(ROOT, self._observation_root(), self.sid, self.provider, outcome, marks, text)
        except Exception:  # noqa: BLE001
            pass

    def _end_unfinished_turn(self, status: str, err: str, duration: float) -> None:
        """agy ended the turn without an answer (error/timeout). At the print timeout it does so
        with an EMPTY result while the agent keeps working unseen in the background, so the child
        is stopped too -- the next message respawns it and resumes the conversation."""
        why = f"status={status or '?'}" + (f", error={err}" if err else "") + f", {int(duration)}초"
        self._auto_stop(
            event={"event": "error", "text": f"에이전트가 답을 내기 전에 턴이 끝났습니다 ({why}). 남아서 돌 수 있는 작업은 멈췄어요 — 메시지를 보내면 이어서 합니다냥."},
            hint=f"직전 턴이 답을 내지 못하고 끝났습니다({why}). 하던 일을 이어서 하되, 같은 방식을 되풀이하지 말고 진행 상황을 짧게 정리해 알려 주세요.")

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

    def _tool_summary(self, obj: dict) -> Union[dict, List[dict], None]:
        """Surface tool activity with detailed arguments and results."""
        SKIP_TOOL_NOISE = {"", "tool", "step", "step_update", "unknown", "agent_response"}
        if not hasattr(self, "_last_tool_sig"):
            self._last_tool_sig = None

        # 1. Antigravity PLANNER_RESPONSE with tool_calls
        tool_calls = obj.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            events = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = str(tc.get("name") or "").strip()
                    args = tc.get("args") or tc.get("input") or {}
                    if not isinstance(args, dict):
                        args = {}
                    text = _format_tool_call(name, args)
                    if text and text != self._last_tool_sig:
                        self._last_tool_sig = text
                        detail_str = json.dumps(args, ensure_ascii=False, indent=2) if args else ""
                        ev_item = {"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": "calling"}
                        if detail_str and len(detail_str) > 2:
                            ev_item["detail"] = detail_str[:4000]
                        events.append(ev_item)
            if events:
                return events

        # 2. Antigravity GENERIC tool execution result
        if obj.get("type") == "GENERIC" and isinstance(obj.get("content"), str) and obj.get("content").strip():
            raw_content = obj["content"].strip()
            res_summary = _format_tool_result(raw_content)
            if res_summary and res_summary != self._last_tool_sig:
                self._last_tool_sig = res_summary
                ev_res = {"event": "tool", "text": res_summary[:600], "title": "result", "kind": "result", "status": "done"}
                if len(raw_content) > len(res_summary) or "\n" in raw_content:
                    ev_res["detail"] = raw_content[:4000]
                return ev_res

        # 3. step_update format
        step = obj.get("step_update")
        if isinstance(step, dict):
            stype = str(step.get("step_type") or step.get("type") or "").strip()
            if stype in ("agent_response",):
                return None
            title = (
                step.get("title")
                or step.get("name")
                or step.get("tool")
                or step.get("tool_name")
                or step.get("function")
                or ""
            )
            step_args = {}
            for nest in (step.get("tool_call"), step.get("toolUse"), step.get("args"), step.get("input")):
                if isinstance(nest, dict):
                    title = title or nest.get("name") or nest.get("tool") or nest.get("Name") or ""
                    tc = nest.get("toolCall")
                    if not title and isinstance(tc, dict):
                        title = tc.get("name") or ""
                    step_args.update(nest)
            title = str(title or "").strip()
            status = str(step.get("status") or step.get("state") or "").strip()

            blob = json.dumps(step, ensure_ascii=False)
            if "generate_image" in blob.lower() or "image" in title.lower():
                for src in self._collect_new_images(self.turn_started_at or None):
                    url = self._stage_image(src)
                    if url and url not in self.pending_images:
                        self.pending_images.append(url)
                        self._emit({"event": "image", "text": url, "url": url, "name": src.name})

            if title and title.lower() not in SKIP_TOOL_NOISE:
                args_dict = step_args if step_args else step
                text = _format_tool_call(title, args_dict)
            else:
                args_dict = {}
                text = ""
                for k in ("command", "CommandLine", "path", "query", "text", "summary", "description"):
                    val = step.get(k)
                    if isinstance(val, str) and val.strip():
                        text = val.strip()[:400]
                        break
                if not text and stype and stype.lower() not in SKIP_TOOL_NOISE:
                    text = stype
            if not text or text == self._last_tool_sig:
                return None
            self._last_tool_sig = text
            ev_step = {"event": "tool", "text": text[:600], "step_type": stype[:80], "title": title[:200] or stype[:80], "kind": "call", "status": status[:80]}
            if args_dict:
                d_str = json.dumps(args_dict, ensure_ascii=False, indent=2)
                if len(d_str) > 2:
                    ev_step["detail"] = d_str[:4000]
            return ev_step

        # 4. classic tool_use / tool_call / tool_result / tool_error
        ev = obj.get("event") or obj.get("type")
        if ev in ("tool_use", "tool_call"):
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            args = obj.get("args") or obj.get("input") or obj.get("parameters") or {}
            if not isinstance(args, dict):
                args = {}
            text = _format_tool_call(name, args) if args else f"{name}"
            if not text or text.lower() in SKIP_TOOL_NOISE:
                return None
            if text == self._last_tool_sig:
                return None
            self._last_tool_sig = text
            ev_call = {"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": str(ev)}
            if args:
                d_str = json.dumps(args, ensure_ascii=False, indent=2)
                if len(d_str) > 2:
                    ev_call["detail"] = d_str[:4000]
            return ev_call

        if ev in ("tool_result", "tool_error"):
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            content = obj.get("output") or obj.get("content") or obj.get("result") or ""
            raw_str = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
            res_text = _format_tool_result(raw_str) if raw_str else f"{ev}: {name or 'done'}"
            if res_text == self._last_tool_sig:
                return None
            self._last_tool_sig = res_text
            ev_res = {"event": "tool", "text": res_text[:600], "title": name[:200] or "result", "kind": "result", "status": str(ev)}
            if raw_str and (len(raw_str) > len(res_text) or "\n" in raw_str):
                ev_res["detail"] = raw_str[:4000]
            return ev_res

        # 5. nested message tool_use / tool_result blocks
        msg = obj.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list):
                events = []
                for part in content:
                    if isinstance(part, dict):
                        ptype = part.get("type")
                        if ptype == "tool_use":
                            name = str(part.get("name") or "").strip()
                            args = part.get("input") or {}
                            text = _format_tool_call(name, args if isinstance(args, dict) else {})
                            if text and text != self._last_tool_sig:
                                self._last_tool_sig = text
                                ev_tu = {"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": "tool_use"}
                                if isinstance(args, dict) and args:
                                    ev_tu["detail"] = json.dumps(args, ensure_ascii=False, indent=2)[:4000]
                                events.append(ev_tu)
                        elif ptype == "tool_result":
                            res = str(part.get("content") or part.get("output") or "")
                            text = _format_tool_result(res) if res else "↳ tool_result: 완료"
                            if text and text != self._last_tool_sig:
                                self._last_tool_sig = text
                                ev_tr = {"event": "tool", "text": text[:600], "title": "result", "kind": "result", "status": "tool_result"}
                                if res and (len(res) > len(text) or "\n" in res):
                                    ev_tr["detail"] = res[:4000]
                                events.append(ev_tr)
                if events:
                    return events
        return None


    def _rewrite_artifact_paths(self, text: str) -> str:
        return _rewrite_artifact_paths(self.sid, self.conversation_id, text)

    def _conversation_brain_dir(self) -> Optional[Path]:
        return _conversation_brain_dir(self.conversation_id)

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
                    print(f"ERROR in _read_stdout line processing for {self.sid}: {e}", flush=True)
        finally:
            with self.lock:
                if self.busy and self.proc is proc:  # only if THIS child died mid-turn
                    self.busy = False
                    died_mid_turn = True
                    self._emit({"event": "error", "text": "에이전트 프로세스가 종료되었습니다냥."})
                    has_queued = bool(getattr(self, "msg_queue", []))
                    if has_queued:
                        threading.Thread(target=self._dispatch_queued, daemon=True).start()
            if died_mid_turn:
                self._finish_turn("process_died")
            _record_live_pids()
            prompt_file = getattr(proc, "_grok_prompt_file", None)
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
        냥피디 answered in flat, personaless tone on OmniRoute without it. No tool_calls/tool-result reconstruction (that's Phase 2, once
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
        system_text = _persona_system_prompt()
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
            text = h.get("text") or ""
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
        text = f"⏱️ 응답이 {minutes}분 넘게 안 와서 자동으로 중단했어요냥. 다시 시도해 주세요."
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
        return getattr(a, "id", "") == "agy" and getattr(a, "transport_kind", "") == "process" and bool(getattr(a, "keeps_stdin_open", False))

    def _queue_steer(self, text: str, client_mid: str) -> None:
        with self.lock:
            if not self.msg_queue:
                self._steer_since = _now()
            self.msg_queue.append((text, client_mid))
            n = len(self.msg_queue)
        self._emit({"event": "steer_queued", "queue_len": n,
                    "text": "새 지시를 받았어요 — 지금 진행 중인 단계가 끝나면 바로 반영합니다냥."})
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

    def _steer_worker(self) -> None:
        try:
            with self.lock:
                if not self.msg_queue or not self.busy:
                    return  # the turn ended meanwhile: the normal end-of-turn dispatch delivers it
                text, mid = self.msg_queue.pop(0)
                rest = list(self.msg_queue)
            self.interrupt_current_turn(reason="steer")   # stops the child; it also clears the queue
            with self.lock:
                self.msg_queue[:] = rest                    # later messages wait for the next boundary
                self._steer_since = _now() if rest else 0.0
            self._loop_hint = STEER_HINT
            self._send_direct(text, mid)                   # respawns with --conversation <real id>: memory intact
        finally:
            self._steering = False

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

    def _run_btw(self, query: str) -> None:
        query = (query or "").strip()
        if not query:
            self._emit({"event": "btw", "query": "", "text": f"{user_title()}, `/btw <질문 내용>` 형태로 궁금한 점을 적어주세요냥!"})
            return
        self._emit({"event": "btw_start", "query": query})
        context_snippets = []
        with self.lock:
            is_active = bool(self.busy and self._proc_alive())
            cur_tool = getattr(self, "_last_tool_sig", "") or ""
            recent_hist = [f"{h.get('role')}: {str(h.get('text') or '')[:120]}" for h in self.history[-4:] if h.get("role") in ("user", "assistant")]
        if is_active:
            if cur_tool:
                context_snippets.append(f"[현재 백그라운드 진행 중인 메인 작업: {cur_tool}]")
            else:
                context_snippets.append("[현재 백그라운드에서 메인 작업 추론/수행 중]")
        else:
            context_snippets.append("[현재 백그라운드에서 실행 중인 메인 작업이 없습니다. 이전 작업은 완료되었거나 대기/중단 상태입니다.]")
        if recent_hist:
            context_snippets.append("[최근 대화 맥락:\n" + "\n".join(recent_hist) + "]")

        prompt = _btw_prompt(query, is_active, context_snippets)
        cmd = [
            AGY, "-p", prompt,
            "--output-format", "stream-json",
            "--model", "gemini-3.8-flash-low",
            "--dangerously-skip-permissions",
        ]
        ans = "답변을 가져오지 못했습니다냥."
        usage = None
        duration_seconds = None
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("event") == "result":
                            r = obj.get("result") or {}
                            ans = str(r.get("response") or "").strip() or ans
                            usage = r.get("usage")
                            duration_seconds = r.get("duration_seconds")
                            break
                    except Exception:
                        pass
                if ans == "답변을 가져오지 못했습니다냥." and res.stdout.strip():
                    ans = res.stdout.strip()
            else:
                ans = _redact_text(res.stderr) or ans
        except subprocess.TimeoutExpired:
            ans = "간이 질문 응답 시간이 초과되었습니다냥."
        except Exception as e:
            ans = f"간이 질문 처리 중 오류가 발생했습니다: {e}"

        with self.lock:
            item = {"role": "btw", "query": query, "text": ans, "ts": _now()}
            if usage:
                item["usage"] = usage
            if duration_seconds is not None:
                item["duration_seconds"] = duration_seconds
            self.history.append(item)
            self.save_meta()
        out = {"event": "btw", "query": query, "text": ans, "ts": item["ts"]}
        if usage:
            out["usage"] = usage
        if duration_seconds is not None:
            out["duration_seconds"] = duration_seconds
        self._emit(out)

    def weight(self) -> dict:
        soft_tokens, hard_tokens = self.adapter.soft_hard_tokens(self.model)
        return _session_weight(self.history, self.conversation_id, soft_tokens, hard_tokens)

    def get_handover_summary(self, max_turns: int = 8, use_cache: bool = True) -> str:
        """Extract a lean handoff memo for the next session.

        Prefers agy's own native `/compact`, resumed against this session's
        real conversation_id via --conversation -- it sees the full
        history/tool state (not just the last N text turns) and empirically
        produces more detailed, accurate summaries than the custom prompt
        below (2026-09-16: verified it recalls exact figures/decisions
        correctly). Confirmed safe to run while this session's own
        persistent agy process is still alive on the same conversation_id
        (isolated concurrent-access test: no hang, no corruption, live
        process stayed healthy afterward) -- note this does NOT reduce the
        conversation's actual resent-context cost (verified separately),
        it's used here purely as a better summary source. Falls back to the
        lightweight custom-prompt dialogue summary when there's no
        conversation_id yet, or the native call fails/times out (a heavy
        session's full history can take a while for agy to compact).
        """
        if use_cache and getattr(self, "_cached_summary", ""):
            return self._cached_summary

        base = ""
        cid = getattr(self, "conversation_id", None)
        # agy's own /compact is agy-specific -- a claude/grok/codex session's
        # conversation_id is that CLI's own id space, not one of agy's
        # conversation dbs. Calling agy with it doesn't error (agy just
        # creates a fresh, empty conversation at that path and "compacts"
        # nothing), it just wastes up to the 45s timeout before falling
        # through to the dialogue-summary fallback below anyway -- caught
        # while wiring up the frontend selector, skip straight to the
        # fallback for any provider that isn't agy instead of wasting the
        # attempt.
        if cid and self.provider == "agy":
            try:
                res = subprocess.run(
                    [AGY, "-p", "/compact", "--conversation", cid,
                     "--model", "gemini-3.8-flash-low", "--dangerously-skip-permissions"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=45,
                )
                base = res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else ""
            except Exception:
                base = ""

        if not base:
            base = self._dialogue_summary_fallback(max_turns)

        # Append the last real exchange verbatim alongside the compacted
        # summary above -- a summary can lose exact wording/details from
        # what was *just* discussed right before a handoff; the raw last
        # turn gives the new session a high-fidelity anchor on top of the
        # compressed long-range context (실장님 제안, 2026-09-17).
        full = self._with_last_exchange(base)
        if use_cache:
            self._cached_summary = full
        return full

    def _with_last_exchange(self, base: str) -> str:
        turns = [h for h in self.history if h.get("role") in ("user", "assistant")]
        if not turns:
            return base
        last = turns[-1]
        prev = turns[-2] if len(turns) >= 2 else None
        lines = []
        if prev and prev.get("role") == "user":
            lines.append(f"{user_title()}: {str(prev.get('text') or '')[:1200]}")
        if last.get("role") == "assistant":
            lines.append(f"{display_name()}: {str(last.get('text') or '')[:1200]}")
        elif last.get("role") == "user" and not prev:
            lines.append(f"{user_title()}: {str(last.get('text') or '')[:1200]}")
        if not lines:
            return base
        return (base or "").rstrip() + "\n\n[마지막으로 주고받은 대화 원문]\n" + "\n".join(lines) + "\n"

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

        cmd = [
            AGY, "-p", prompt,
            "--model", "gemini-3.8-flash-low",
            "--dangerously-skip-permissions",
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=12,
            )
            summary = res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else ""
            if summary:
                return summary
        except Exception:
            pass

        # Deterministic fallback if subprocess fails or times out
        user_turns = [h.get("text") for h in self.history if h.get("role") == "user"]
        asst_turns = [h.get("text") for h in self.history if h.get("role") == "assistant"]
        last_u = str(user_turns[-1] if user_turns else "")[:120]
        last_a = str(asst_turns[-1] if asst_turns else "")[:120]
        return f"- 최근 {user_title()} 지시: {last_u}\n- 최근 답변 요약: {last_a}"

    def _precompute_summary(self) -> None:
        if getattr(self, "_summary_generating", False) or getattr(self, "_cached_summary", ""):
            return
        self._summary_generating = True
        try:
            self.get_handover_summary()
        finally:
            self._summary_generating = False

    def _emit_heavy_if_needed(self, force: bool = False) -> dict:
        w = self.weight()
        level = w.get("level") or "ok"
        if level in ("soft", "hard") and not getattr(self, "_cached_summary", ""):
            threading.Thread(target=self._precompute_summary, daemon=True).start()
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

    def _rotate_to_fresh_session(self, text: str, reason: str = "heavy", client_mid: str = "", client_context: Optional[Dict[str, Any]] = None) -> "AgySession":
        """Sticky rotate: reuse successor_session_id when usable; else create once and remember with handover."""
        if reason == "inactivity":
            msg = (
                "이전 대화 이후 시간이 경과하여 이전 맥락을 인계받아 새 세션으로 이어갑니다냥 ✦ (이전 대화는 보존됩니다)"
            )
        else:
            msg = (
                "세션이 길어져서 이전 맥락을 인계받아 새 채팅으로 전환합니다. 이전 세션 데이터는 그대로 보존됩니다냥 ✦"
            )
        succ_id = getattr(self, "successor_session_id", "") or ""
        if succ_id and self._successor_usable(succ_id):
            new_sess = REG.get(succ_id)
        else:
            summary = self.get_handover_summary()
            new_sess = REG.create(
                model=self.model,
                effort=self.effort,
                predecessor_sid=self.sid,
                handoff_summary=summary,
                # same fix as continue_to_successor(): without it the successor starts as agy
                # with this provider's model name (e.g. claude "sonnet") and the turn dies with
                # "invalid model selection" (2026-09-21, also seen with grok-4.6)
                provider=self.provider,
            )
            self.successor_session_id = new_sess.sid
            try:
                self.save_meta()
            except Exception:
                pass
            if evolution is not None:
                evolution.record_candidate(self._observation_root(), "rotation", self.sid, self.provider, {"outcome": reason})
        # client_mid lets the sending tab's own SSE handler recognize this
        # rotation as one it already knows about (the /message HTTP response
        # itself carries the same info) and skip re-rendering -- without
        # this, both the SSE event (emitted here, before the slow successor
        # spawn/send below) and the POST response (arriving after) independently
        # re-entered the new session, and the SSE one (missing the user's
        # own just-typed text) usually rendered first, making the message
        # look like it vanished (실장님: "내가 말을 하면 바로 새 세션으로
        # 넘어가면서 내가 한 말을 또 해야 되는 상황이 생겨").
        self._emit({
            "event": "session_rotate",
            "text": msg,
            "reason": reason,
            "new_session_id": new_sess.sid,
            "weight": self.weight(),
            "handoff_summary": getattr(new_sess, "handoff_summary", ""),
            "client_mid": client_mid,
        })
        try:
            self.stop(notify=False)
        except Exception:
            pass
        if client_context:
            new_sess._send_direct(text, client_mid, client_context=client_context)
        else:
            new_sess._send_direct(text, client_mid)
        return new_sess

    def send(self, text: str, client_mid: str = "", client_context: Optional[Dict[str, Any]] = None):
        """Return None (same session) or AgySession if hard-rotated to a fresh session."""
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")

        if text.startswith("/btw ") or text.startswith("/btw\n") or text == "/btw":
            query = text[4:].strip()
            threading.Thread(target=self._run_btw, args=(query,), daemon=True).start()
            return None

        # Soft warn anytime; hard rotate before appending more to bloated conversation.
        # Skip rotate for doctor probes and queued follow-ups while busy.
        w = self._emit_heavy_if_needed()
        is_probe = text.strip().startswith("[doctor-probe]")
        if (w.get("level") == "hard") and (not is_probe) and (not self.busy):
            return self._rotate_to_fresh_session(text, reason="heavy", client_mid=client_mid, client_context=client_context)

        # Inactivity auto-rotate: if session had prior conversation and was inactive > INACTIVITY_ROTATE_SEC
        user_or_asst_turns = [h for h in self.history if h.get("role") in ("user", "assistant")]
        time_since_active = _now() - getattr(self, "last_activity", _now())
        if len(user_or_asst_turns) >= 2 and (time_since_active >= INACTIVITY_ROTATE_SEC) and (not is_probe) and (not self.busy):
            return self._rotate_to_fresh_session(text, reason="inactivity", client_mid=client_mid, client_context=client_context)

        with self.lock:
            is_proc_alive = self._proc_alive()
            if self.busy and not is_proc_alive:
                self.busy = False
            if self.busy:
                if _is_inquiry(text):
                    threading.Thread(target=self._run_btw, args=(text,), daemon=True).start()
                    return None
                if self._can_steer_at_boundary():
                    # agy cannot take a message mid-turn (it only queues it until the turn ends),
                    # and cutting the turn loses the work in flight. So: accept now, let the
                    # current tool step finish, then stop cleanly and resume the SAME
                    # conversation with this message (_steer_worker). Nothing already done is lost.
                    self._queue_steer(text, client_mid)
                    return None
                # Providers without that (one-shot CLIs, HTTP): interrupt the running process/
                # stream, keep the partial answer, and run the new instruction immediately --
                # but tell the agent the earlier work was paused, not cancelled.
                self._loop_hint = STEER_HINT
                self.interrupt_current_turn()

        if client_context:
            self._send_direct(text, client_mid, client_context=client_context)
        else:
            self._send_direct(text, client_mid)
        return None

    def _send_direct(self, text: str, client_mid: str = "", client_context: Optional[Dict[str, Any]] = None,
                     notice: bool = False) -> None:
        """`notice=True`: `text` is a host note to the agent (a loop notice), not something the user said --
        it is neither shown as their message nor kept in history, and it does not start a new user turn."""
        # Multi-Provider plan Phase 2: a one-shot exec provider (grok, and any
        # future codex-style adapter) needs its prompt known BEFORE spawning
        # (baked into argv/a prompt file), so ensure()-then-write-to-stdin
        # doesn't apply -- stdin_content must be finalized first either way,
        # then the two provider shapes fork at the bottom of this method.
        if self.adapter.keeps_stdin_open:
            self.ensure()
            assert self.proc and self.proc.stdin

        stdin_content = f"[시스템 안내] {text}" if notice else text
        rules_prefix = ""  # instruction bundle, prepended AFTER the handoff wrap below
        with self.lock:
            # Instruction bundle (instructions.py), injected above the adapter
            # layer so every provider gets the same text the same way; native
            # AGENTS.md/CLAUDE.md/skill auto-discovery is not relied on.
            #   - first turn of a conversation            -> inject
            #   - static layers changed (charter/persona/skills) -> re-inject as an update
            #   - resumed session that has a flag but no stored hash (pre-hash
            #     sessions) -> adopt the current hash silently, no duplicate
            # The HTTP transport is stateless and already sends the bundle as
            # the system message on every request, so a user-turn preamble
            # would only duplicate it there.
            bundle = build_instruction_bundle()
            btext, bhash = bundle["text"], bundle["hash"]
            if btext:
                if not getattr(self, "persona_injected", False):
                    header = "아래는 이 챗봇의 페르소나·운영 규칙이다. 첫 턴에만 주입된다."
                elif getattr(self, "persona_bundle_hash", "") and self.persona_bundle_hash != bhash:
                    header = "규칙이 갱신되었다. 아래 내용이 지금부터의 규칙이다. 이전 규칙과 다르면 아래를 따른다."
                else:
                    header = ""
                    if not getattr(self, "persona_bundle_hash", ""):
                        self.persona_bundle_hash = bhash
                if header:
                    if self.adapter.transport_kind != "http":
                        rules_prefix = (
                            f"[시스템 안내] {header} 규칙대로 행동하되 이 안내 자체를 언급하지 마라.\n\n"
                            f"{btext}\n\n"
                            f"---\n\n"
                        )
                    self.persona_injected = True
                    self.persona_bundle_hash = bhash
        with self.lock:
            if not notice and not getattr(self, "handoff_injected", False) and getattr(self, "handoff_summary", ""):
                pred = getattr(self, "predecessor_session_id", "") or ""
                # A real cross-session rotation (/continue, heavy-session
                # auto-rotate) always sets predecessor_session_id alongside
                # handoff_summary (see REG.create() below); an in-place
                # provider swap (maybe_swap_provider()) sets handoff_summary
                # on the SAME session, with no predecessor id to show, so the
                # label reads as "직전 대화" instead of a session id nobody
                # asked to see.
                label = f"이전 세션({pred[:8]})" if pred else "직전 대화"
                # Explicit framing, not just labeled sections -- without a
                # direct instruction, the model (esp. the fast/small models
                # this rotates onto) sometimes treated the handoff summary
                # itself as the thing to respond to/discuss, rather than
                # background for the actual instruction below it, so a task
                # given right as a session rotated came back ignored with an
                # off-topic reply about the summary instead (실장님: "일을
                # 시켰는데 세션이 전환되면서 내가 시킨 일을 잊어버리고 딴
                # 소리를 하고 있어"). agy's own /compact summary style (the
                # preferred summary source) isn't written with a "here's the
                # pending task" framing the way our custom fallback prompt
                # is, so this needs to hold regardless of which produced it.
                stdin_content = (
                    f"[시스템 안내] {label}에서 맥락을 인계받아 이어갑니다. "
                    f"아래 '인계 맥락'은 참고용 배경 정보일 뿐입니다 — 그 내용을 요약하거나 "
                    f"그 자체에 대해 코멘트하지 마세요. 지금 실제로 답하거나 수행해야 할 것은 "
                    f"오직 그 아래 '{user_title()}의 현재 메시지'뿐입니다.\n\n"
                    f"[{label} 인계 맥락 — 참고용 배경]\n"
                    f"{self.handoff_summary}\n"
                    f"--------------------------------------------------\n"
                    f"[{user_title()}의 현재 메시지 — 지금 답하거나 수행해야 할 것]\n"
                    f"{text}"
                )
                self.handoff_injected = True
                self._emit({
                    "event": "system",
                    "text": f"{label} 맥락을 인계받아 대화를 시작했습니다냥 ✦",
                })

        if client_context:
            ctx_line = format_client_context(client_context)
            if ctx_line:
                stdin_content = f"{ctx_line}\n\n{stdin_content}"

        if self._loop_hint:  # the previous turn was stopped automatically; tell the agent once
            stdin_content = f"[시스템 안내] {self._loop_hint}\n\n{stdin_content}"
            self._loop_hint = ""

        # Order on the wire: rules -> handoff context -> the current message.
        # (The handoff block above rebuilds stdin_content from `text`, so the
        # rules must be prepended after it, not before -- doing it before
        # silently dropped the bundle on every rotation / provider-swap turn.)
        if rules_prefix:
            stdin_content = rules_prefix + stdin_content

        self._loop_guard.reset()
        self._loop_warned = False
        if notice:
            self._loop_guard.tighten(LOOP_STOP_AFTER_NOTICE)  # the resumed turn stops sooner if it keeps repeating
        else:
            self._loop_guard.relax()
            self._loop_noticed = False
        with self.lock:
            self.current_text = ""
            self.turn_started_at = _now()
            self.pending_images = []
            ts = _now()
            if not notice:
                self.history.append({"role": "user", "text": text, "ts": ts})
            self.last_activity = _now()
            self.save_meta()

        # Other devices must see the question before any delta. HTTP/one-shot
        # turns used to start their worker thread first; the tablet then
        # drew the answer and only later appended the question underneath.
        if not notice:
            self._emit({"event": "user_ack", "text": text, "ts": ts, "client_mid": client_mid})

        if self.adapter.keeps_stdin_open:
            with self.lock:
                self.busy = True
            payload = self.adapter.format_stdin(stdin_content)
            with self.lock:
                self.proc.stdin.write(payload)
                self.proc.stdin.flush()
        elif self.adapter.transport_kind == "http":
            # API-Provider plan: no process/stdin at all -- the whole turn
            # (request + streaming read + history append) runs in its own
            # background thread, the same shape as the one-shot-exec branch
            # below minus everything process-specific. busy=True is set here
            # (not inside the thread) so a caller that checks session.busy
            # immediately after send() returns sees the correct state even
            # if the thread hasn't started running yet.
            with self.lock:
                self.busy = True
                self._turn_seq += 1
                turn_seq = self._turn_seq
            # _spawn() (process transport) resets this at the start of every
            # turn; http transport never calls _spawn() at all, so without
            # this reset here a single past stop() would latch
            # _stop_requested=True forever and _run_http_turn would silently
            # drop every future turn's events (mirroring the "drain silently
            # after stop" behavior below, which is only supposed to apply to
            # THIS turn).
            self._stop_requested = False
            threading.Thread(target=self._run_http_turn, args=(stdin_content,), daemon=True).start()
            threading.Thread(target=self._http_turn_watchdog, args=(turn_seq,), daemon=True).start()
        else:
            # One-shot exec: the prompt goes into the spawn itself (grok's
            # --prompt-file), not a stdin write on an already-running
            # process -- _spawn() kills whatever this session's previous
            # (already-exited, since one-shot turns finish and exit on their
            # own) process was and starts the next one. busy=True MUST be
            # set only after _spawn() returns, not before -- _spawn() calls
            # self.stop() internally first (to kill any leftover process),
            # and stop() unconditionally resets busy=False; setting it True
            # beforehand just got silently clobbered back to False here,
            # so the API reported busy:false while grok was still actually
            # running (caught live 2026-09-17: a real turn came back with
            # busy:false and no reply yet).
            self._spawn(prompt=stdin_content)
            with self.lock:
                self.busy = True
            # format_stdin() empty (grok) means nothing more to do; a
            # non-empty return is for a future codex-style provider that
            # still wants its prompt on stdin post-spawn (close_stdin_after_
            # prompt=True), not currently exercised by any adapter here.
            payload = self.adapter.format_stdin(stdin_content)
            if payload and self.proc and self.proc.stdin:
                with self.lock:
                    self.proc.stdin.write(payload)
                    self.proc.stdin.flush()
                    if self.adapter.close_stdin_after_prompt:
                        try:
                            self.proc.stdin.close()
                        except Exception:
                            pass

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
            self._emit({"event": "stopped", "text": f"{what} 바꿔서 진행 중이던 작업을 중단했습니다냥."})

    def maybe_swap_model(self, model: str) -> None:
        """If `model` names a different model than this session is currently
        running, switch to it and stop the live process so the next send()
        respawns under the new model."""
        if model and model != self.model:
            self.model = model
            self._stop_for_swap("모델을")

    def maybe_swap_provider(self, provider: str) -> None:
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
        (실장님: "도중에 바뀌면 다시 해줘야하는 게 있을 것 같네" -- confirmed
        real, 2026-09-18). Reuse the same handoff_summary/handoff_injected
        relay _send_direct() already does for /continue rotations, computed
        here (before conversation_id/provider are overwritten, since
        get_handover_summary() needs the OLD ones to decide whether agy's
        native /compact applies) -- use_cache=False because, unlike a
        rotation (which retires the session), this session object stays
        alive afterward, so caching here would feed a stale summary to a
        later heavy-session rotation's own prewarm check."""
        if provider and provider != self.provider:
            summary = self.get_handover_summary(use_cache=False)
            self.provider = provider
            self.adapter = get_adapter(provider)
            self.conversation_id = None
            self.model = ""
            self.handoff_summary = summary
            self.handoff_injected = False
            # New provider = new conversation that has never seen the persona
            # rules; without this reset it would run persona-less (2026-09-19).
            self.persona_injected = False
            self.persona_bundle_hash = ""
            self._stop_for_swap("제공자를")
            self.save_meta()

    def continue_to_successor(self, model: str, sticky: bool) -> dict:
        """Hand this session off to a successor, for the /continue route.

        sticky=True (used by the client's auto-redirect-on-open for a "hard"
        session) reuses an already-usable successor_session_id instead of
        always forking a fresh one. Without this, every browser tab/window
        that happened to load the same hard session before any of them
        finished handing off would each mint its own orphan successor, so N
        open windows meant N disconnected new chats and the old context
        never settled on one continuation (실장님 보고: 창을 여러 개 열면
        각자 다른 새 세션이 뜨고 예전 내용이 안 보임). The manual "이어하기"
        button intentionally keeps the old always-fork behavior (sticky
        False) -- that's a deliberate cost-reset the user asks for
        explicitly.

        Returns a dict with new_sess/summary/reused, ready to fold into the
        route's JSON response.
        """
        model = model or self.model
        reused = False
        with self.lock:
            succ_id = getattr(self, "successor_session_id", "") or ""
            if sticky and succ_id and self._successor_usable(succ_id):
                new_sess = REG.get(succ_id)
                summary = getattr(self, "handoff_summary", "") or ""
                reused = True
            else:
                summary = self.get_handover_summary()
                new_sess = REG.create(
                    model=model,
                    effort=self.effort,
                    predecessor_sid=self.sid,
                    handoff_summary=summary,
                    # Multi-Provider plan: without this, /continue always
                    # created the successor as agy regardless of what
                    # provider the predecessor was actually running --
                    # caught while wiring up the frontend selector, not by a
                    # live test of this specific path.
                    provider=self.provider,
                )
                self.successor_session_id = new_sess.sid
                try:
                    self.save_meta()
                except Exception:
                    pass
        return {"new_sess": new_sess, "summary": summary, "reused": reused}

    def interrupt_current_turn(self, reason: str = "interrupted") -> None:
        """Interrupt an in-flight turn (process or HTTP stream) safely, preserving partial text in history."""
        self._stop_requested = True
        proc = self.proc
        http_resp = self._http_resp
        with self.lock:
            if hasattr(self, "msg_queue"):
                self.msg_queue.clear()
            self.busy = False
            # If there was partial assistant text generated so far, preserve it in history
            cur = (self.current_text or "").strip()
            if cur:
                mark = (f"*(🧭 {user_title()}의 새 지시를 반영하려고 여기서 잠시 멈췄습니다냥)*" if reason == "steer"
                        else "*(🧭 같은 호출이 반복돼 여기서 잠시 멈추고 방향을 바꾸도록 알렸습니다냥)*" if reason == "loop"
                        else f"*(⚡ {user_title()}의 새 지시로 이전 작업이 중단되었습니다냥)*")
                annotated = self._rewrite_artifact_paths(cur) + "\n\n" + mark
                self.history.append({"role": "assistant", "text": annotated, "ts": _now(), "interrupted": True})
            self.current_text = ""
            self.save_meta()

        if proc:
            # Let adapter try graceful interrupt first (e.g. SIGINT)
            interrupted = False
            try:
                interrupted = bool(self.adapter.interrupt(proc))
            except Exception:
                pass
            if not interrupted:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass
            self.proc = None
        if http_resp:
            try:
                http_resp.close()
            except Exception:
                pass
            self._http_resp = None
        self._emit({"event": "interrupted", "reason": reason,
                    "text": ("새 지시를 반영하는 중이에요 — 하던 작업은 이어서 합니다냥 ✦" if reason == "steer"
                             else "방향을 바꾸도록 알리는 중이에요 — 하던 작업은 이어서 합니다냥 ✦" if reason == "loop"
                             else f"진행 중인 작업이 {user_title()}의 새 지시로 전환되었습니다냥 ✦")})
        self._finish_turn("steer" if reason in ("steer", "loop") else "interrupted")
        _record_live_pids()

    def stop(self, notify: bool = True) -> None:
        # Set before killing the process -- a just-terminated agy process can
        # still have already-flushed output sitting in its stdout pipe, and
        # _read_stdout()'s loop would otherwise keep reading and emitting
        # that (including what looks like a genuine "result" event, with
        # stale/reused usage stats) after the user explicitly asked to stop,
        # making it look like stop did nothing or a new answer appeared
        # right after (실장님: "작성 중인 상태에서 중지같은 게 안되네").
        self._stop_requested = True
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
            try:
                proc.terminate()
                proc.wait(timeout=3)
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
            self._emit({"event": "stopped", "text": f"{user_title()}의 요청으로 작업이 중지되었습니다냥."})
            if was_busy:
                self._finish_turn("stopped")
        _record_live_pids()

    def to_public(self) -> dict:
        billed_tokens = _billed_tokens(self.history)
        context_tokens = _current_context_tokens(self.history)
        output_tokens = 0
        thinking_tokens = 0
        cache_read_tokens = 0
        for h in self.history:
            u = h.get("usage")
            if isinstance(u, dict):
                output_tokens += int(u.get("output_tokens") or 0)
                thinking_tokens += int(u.get("thinking_tokens") or 0)
                cache_read_tokens += int(u.get("cache_read_tokens") or 0)

        really_busy = bool(self.busy and self._proc_alive())
        draft = (self.current_text or "") if really_busy else ""
        if len(draft) > 120000:
            draft = draft[-120000:]
        out = {
            "id": self.sid,
            "provider": self.provider,
            "model": self.model,
            "effort": self.effort,
            "conversation_id": self.conversation_id,
            "busy": really_busy,
            "queue_len": len(getattr(self, "msg_queue", [])),
            "alive": self._proc_alive(),
            "current_text": draft,
            "turn_started_at": float(self.turn_started_at or 0) if really_busy else 0,
            "last_progress": (getattr(self, "last_progress", "") or "") if really_busy else "",
            "history": self.history[-40:],
            "updated_at": self.meta_path.stat().st_mtime if self.meta_path.exists() else self.last_activity,
            "class": "NAS agent (VibeCat-class)",
            "weight": self.weight(),
            "add_dirs": [d for d in ADD_DIRS if Path(d).exists()],
            "usage": {
                "context_tokens": context_tokens,
                "billed_tokens": billed_tokens,
                "total_tokens": billed_tokens,
                "input_tokens": context_tokens,
                "output_tokens": output_tokens,
                "thinking_tokens": thinking_tokens,
                "cache_read_tokens": cache_read_tokens,
            },
        }
        if not out["alive"] and self._stderr_tail:
            out["debug_stderr_tail"] = [l for l in self._stderr_tail[-15:] if not _redact_line(l)]
        w = out.get("weight") or {}
        succ = getattr(self, "successor_session_id", "") or ""
        if succ:
            out["successor_session_id"] = succ
            if (w.get("level") or "") == "hard":
                out["redirect_session_id"] = succ
        pred = getattr(self, "predecessor_session_id", "") or ""
        if pred:
            out["predecessor_session_id"] = pred
            out["has_handover"] = bool(getattr(self, "handoff_summary", ""))
            out["handoff_summary"] = getattr(self, "handoff_summary", "")
        return out

    def _append_log_event(self, event: dict) -> None:
        try:
            entry = dict(event)
            entry.setdefault("ts", _now())
            path = self.meta_path.parent / "events.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_log(self) -> List[dict]:
        """Durable per-session activity log (see PERSISTED_LOG_KINDS/_emit),
        newest first -- same shape/pagination story as get_artifacts()."""
        path = self.meta_path.parent / "events.jsonl"
        if not path.exists():
            return []
        out = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            return []
        out.sort(key=lambda e: e.get("ts") or 0, reverse=True)
        return out

    def get_artifacts(self) -> List[dict]:
        exts_img = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
        exts_doc = {".md", ".txt", ".json", ".pdf", ".html", ".csv", ".yaml", ".yml"}
        exts_code = {".py", ".js", ".ts", ".gd", ".sh", ".sql", ".css"}

        roots = []
        bdir = self._conversation_brain_dir()
        if bdir:
            roots.append(bdir)
            roots.append(bdir / ".tempmediaStorage")
        ws_artifacts = WORKSPACE / "artifacts"
        persona_root = DATA / "persona"
        persona_gallery = persona_root / "gallery"
        roots.append(ws_artifacts)
        roots.append(ARTIFACTS_CACHE)  # legacy/shared assets not tied to one session
        roots.append(persona_gallery)

        # First cut (2026-09-18) only walked self.sid + predecessor_session_id,
        # on the theory that images just needed to survive a /continue or
        # heavy-session auto-rotate. 실장님 corrected that framing: "아티팩트
        # 탭은 모든 디바이스 모든 세션 공통인데" -- the tab is meant to be one
        # shared gallery across every session/device, not scoped to whichever
        # conversation happens to be open. So scan every session's own
        # artifacts/ folder, not just this session's ancestor chain.
        session_artifact_roots: Dict[Path, str] = {}
        for meta_path in SESSIONS.glob("*/meta.json"):
            sid = meta_path.parent.name
            adir = meta_path.parent / "artifacts"
            session_artifact_roots[adir] = sid
            roots.append(adir)

        found = []
        seen_sizes = set()
        seen_names = set()

        # Only agy's raw generation cache (bdir and its subfolders) needs
        # _stage_image's copy-out-of-cache treatment. Everything else found
        # below is already sitting in a stable, directly-servable location --
        # calling _stage_image on it would copy it AGAIN into this session's
        # own folder on every single gallery view (caught 2026-09-16: viewing
        # an empty session's artifact tab silently vacuumed every image out
        # of sessions/_shared/ into that session's own artifacts/ folder).
        brain_source_roots = {r for r in (bdir, bdir / ".tempmediaStorage" if bdir else None) if r}

        for root in roots:
            if not root or not Path(root).exists():
                continue
            try:
                for fp in Path(root).rglob("*"):
                    if not fp.is_file() or fp.name.startswith("."):
                        continue
                    if any(part.startswith(".") for part in fp.parts[:-1]):
                        continue
                    suffix = fp.suffix.lower()
                    if suffix not in exts_img and suffix not in exts_doc and suffix not in exts_code:
                        continue
                    try:
                        sz = fp.stat().st_size
                    except OSError:
                        continue
                    if sz in seen_sizes and sz > 5000:
                        continue
                    if fp.name in seen_names:
                        continue
                    seen_sizes.add(sz)
                    seen_names.add(fp.name)

                    kind = "image" if suffix in exts_img else ("document" if suffix in exts_doc else "code")
                    if kind == "image" and root in brain_source_roots:
                        url = self._stage_image(fp)
                    elif root in session_artifact_roots:
                        owner_sid = session_artifact_roots[root]
                        url = f"/artifacts/{owner_sid}/{fp.relative_to(root).as_posix()}"
                    elif root == ARTIFACTS_CACHE or root == ws_artifacts:
                        url = f"/artifacts/{fp.relative_to(root).as_posix()}"
                    elif root == persona_gallery:
                        url = "/persona/" + fp.relative_to(persona_root).as_posix()
                    else:
                        url = f"/artifacts/{fp.name}"

                    if sz >= 1024 * 1024:
                        sz_str = f"{sz / (1024 * 1024):.1f} MB"
                    elif sz >= 1024:
                        sz_str = f"{sz / 1024:.0f} KB"
                    else:
                        sz_str = f"{sz} B"

                    mtime = fp.stat().st_mtime
                    found.append({
                        "name": fp.name,
                        "stem": fp.stem,
                        "kind": kind,
                        "ext": suffix.lstrip("."),
                        "size": sz,
                        "size_human": sz_str,
                        "url": url or f"/artifacts/{fp.name}",
                        "mtime": mtime,
                        "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
                    })
            except Exception:
                continue

        found.sort(key=lambda x: x["mtime"], reverse=True)
        return found


_LIVE_SID_RE = re.compile(r"^\d{8}-\d{6}-")


def _live_sid(sid: str) -> bool:
    """Production session ids are YYYYMMDD-HHMMSS-xxxxxx. Leftover names like
    nonexistent-sid-test sort after those and must not become 'active'."""
    return bool(sid and _LIVE_SID_RE.match(sid))


def _probe_meta(meta: dict) -> bool:
    hist = meta.get("history") or []
    if len(hist) > 2:
        return False
    sample = " ".join(str(h.get("text") or "") for h in hist)
    return "[doctor-probe]" in sample or "[diag]" in sample


class Registry:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sessions: Dict[str, AgySession] = {}

    def create(
        self,
        model: str = DEFAULT_MODEL,
        effort: str = "",
        predecessor_sid: str = "",
        handoff_summary: str = "",
        provider: str = DEFAULT_PROVIDER,
    ) -> AgySession:
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        sess = AgySession(sid, model=model, effort=effort, provider=provider)
        sess.predecessor_session_id = predecessor_sid
        sess.handoff_summary = handoff_summary
        sess.handoff_injected = False
        sess.save_meta()
        with self.lock:
            self.sessions[sid] = sess
        return sess

    def delete(self, sid: str) -> bool:
        """Stops any live process, drops the in-memory session, and removes
        sessions/<sid>/ entirely -- meta.json AND artifacts/ together, since
        they live in one folder by design (see 2026-09-16/17 consolidation).
        Returns False if the session doesn't exist on disk. Raises if the
        directory is still there afterward -- ignore_errors=True previously
        made this silently report success even when removal failed."""
        sid = _safe_session_id(sid)
        sess_dir = SESSIONS / sid
        meta_path = sess_dir / "meta.json"
        if not meta_path.exists():
            return False
        with self.lock:
            sess = self.sessions.pop(sid, None)
        if sess is not None:
            try:
                sess.stop(notify=False)
            except Exception:
                pass
        shutil.rmtree(sess_dir, ignore_errors=True)
        if sess_dir.exists():
            raise RuntimeError(f"삭제 실패: {sess_dir} 디렉터리가 여전히 남아있습니다")
        return True

    def peek(self, sid: str) -> Optional[AgySession]:
        """Return the session if it exists in memory or on disk; None otherwise.
        Unlike get(), never creates a new session — safe for all GET routes."""
        try:
            sid = _safe_session_id(sid)
        except ValueError:
            return None
        with self.lock:
            if sid in self.sessions:
                return self.sessions[sid]
        # Check disk: a session folder with a meta.json qualifies.
        if (SESSIONS / sid / "meta.json").exists():
            return self.get(sid)
        return None

    def get(self, sid: str) -> AgySession:
        sid = _safe_session_id(sid)
        with self.lock:
            if sid in self.sessions:
                return self.sessions[sid]
            sess = AgySession(sid)
            self.sessions[sid] = sess
            return sess

    def list(self) -> List[dict]:
        items = []
        for p in sorted(SESSIONS.glob("*/meta.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:40]:
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
                hist = meta.get("history") or []
                items.append({
                    "id": meta.get("id") or p.parent.name,
                    "model": meta.get("model"),
                    # epoch-seconds float, matching AgySession.to_public()'s
                    # updated_at (both derived from the same meta.json's
                    # mtime) -- previously this returned meta.json's own
                    # "updated_at" ISO string field instead, a different
                    # format from the same-named field on every other
                    # session endpoint, which is why the client needed a
                    # _scrollbackEpochMs() normalizer to compare the two.
                    "updated_at": p.stat().st_mtime,
                    "preview": (hist[-1:].pop().get("text", "")[:80] if hist else ""),
                    "turns": len(hist),
                })
            except Exception:
                continue
        return items

    def get_active(self) -> AgySession:
        """Live conversation: newest session id, then the successor-chain tip.

        Session ids are YYYYMMDD-HHMMSS-xxxxxx so lexicographic max is
        chronological latest. list() is still mtime-sorted (recency for the
        sessions tab). Opening a past session must not steal 'active'.
        """
        with self.lock:
            best_id = ""
            for p in SESSIONS.glob("*/meta.json"):
                try:
                    meta = json.loads(p.read_text(encoding="utf-8"))
                    if _probe_meta(meta):
                        continue
                    sid = str(meta.get("id") or p.parent.name or "")
                    if not _live_sid(sid):
                        continue
                    if not best_id or sid > best_id:
                        best_id = sid
                except Exception:
                    continue
            if not best_id:
                return self.create()
            sess = self.get(best_id)
            seen = {best_id}
            for _ in range(40):
                succ = getattr(sess, "successor_session_id", "") or ""
                if not succ or succ in seen or not sess._successor_usable(succ):
                    return sess
                seen.add(succ)
                sess = self.get(succ)
            return sess


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
        (DATA / "live_pids.json").write_text(json.dumps(pids), encoding="utf-8")
    except Exception:
        pass


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
                        sess._emit({"event": "error", "text": "에이전트 프로세스가 종료되었습니다냥."})
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
                    else:
                        live_pids.append(sess.proc.pid)
                else:
                    live_pids.append(sess.proc.pid)

    for sess in died:
        sess._finish_turn("process_died")
    try:
        (DATA / "live_pids.json").write_text(json.dumps(live_pids), encoding="utf-8")
    except Exception:
        pass

