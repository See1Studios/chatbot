"""Antigravity (agy) CLI adapter and where agy keeps a conversation's media. Callers import from adapters (ADAPTER_SPLIT_v1)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time

from pathlib import Path
from typing import Any, Dict, List, Optional

import i18n
from host_config import AGENT_PATH_PREFIX, AGY, MODELS, WORKSPACE
from providers.adapter_base import AgentAdapter, _redact_err, cached_model_list, quota_view_of
from tool_format import _format_tool_call, _format_tool_result
import media_handler as _media


# agy ends a turn with an EMPTY result when this elapses -- and the agent may keep working unseen.
AGY_PRINT_TIMEOUT_SEC = int(os.environ.get("CHATBOT_AGY_TURN_TIMEOUT_SEC") or 8 * 60)   # a host may set it (the drill's sandbox)

_AGY_MODELS_CACHE = {"ts": 0.0, "models": []}



# An agy model id that ends in a level already carries its effort; a separate --effort then conflicts (2026-09-30).
_MODEL_NAMES_EFFORT = re.compile(r"-(?:minimal|low|medium|high|xhigh)$")


_SUBAGENT_ID = re.compile(r'conversationId\\?"?\s*:\s*\\?"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})')


_LOG_CONVERSATION = re.compile(r"\] (?:Created|Streaming) conversation ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def _log_conversation(path) -> str:
    """The conversation an agy process works on, as its own log names it ("Created conversation <id>", or
    "Streaming conversation <id>" for a resumed one); "" until it has one. The id comes early, so the head is read."""
    try:
        with open(str(path), "rb") as f:
            head = f.read(1 << 20).decode("utf-8", "replace")
    except OSError:
        return ""
    found = _LOG_CONVERSATION.findall(head)
    return found[-1] if found else ""


def _brain_activity(conversation_id: str) -> Optional[float]:
    """The newest write to a conversation's records -- its store (`conversations/<id>.db`, written every step) and its
    transcript, which agy does not keep for every conversation -- and to those of the subagents it started (their ids
    are in the parent transcript's "Created the following subagents" steps). None when it has no records."""
    from providers import accounts
    root = Path(accounts.AGY_LOG_DIR).parent

    def transcript(cid: str) -> Path:
        return root / "brain" / cid / ".system_generated" / "logs" / "transcript.jsonl"

    def newest_of(cid: str) -> Optional[float]:
        times = []
        for p in (root / "conversations" / (cid + ".db"), root / "conversations" / (cid + ".db-wal"), transcript(cid)):
            try:
                times.append(p.stat().st_mtime)
            except OSError:
                continue
        return max(times) if times else None

    newest = newest_of(conversation_id)
    if newest is None:
        return None
    try:
        with open(str(transcript(conversation_id)), "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 262144))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return newest
    for cid in set(_SUBAGENT_ID.findall(tail)) - {conversation_id}:
        newest = max(newest, newest_of(cid) or 0)
    return newest

def _parse_version(name: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", name)]
    return tuple(nums) if nums else (0,)


def _resolve_agy_model(model: str, known: List[str]) -> str:
    """Resolve a requested model identifier or family to an available agy model."""
    if not model or not known:
        return model
    for k in known:
        if k == model or k.lower() == model.lower():
            return k
    norm = model.lower()
    target_words = [w for w in ("claude", "gemini", "gpt", "opus", "sonnet", "haiku", "flash", "pro") if w in norm]
    if not target_words:
        return model
    want_effort = "high"
    if "medium" in norm:
        want_effort = "medium"
    elif any(x in norm for x in ("low", "minimal")):
        want_effort = "low"

    candidates = [k for k in known if all(w in k.lower() for w in target_words)]
    if not candidates:
        series_words = [w for w in target_words if w in ("opus", "sonnet", "haiku", "flash", "pro")]
        if series_words:
            candidates = [k for k in known if all(w in k.lower() for w in series_words)]
    if not candidates:
        return model

    effort_prio = {"high": 3, "medium": 2, "low": 1}

    def rank(name: str):
        ver = _parse_version(name)
        eff = 0
        for e_name, p in effort_prio.items():
            if f"-{e_name}" in name.lower():
                eff = p
                break
        exact_eff = 1 if want_effort and f"-{want_effort}" in name.lower() else 0
        return (ver, exact_eff, eff)

    candidates.sort(key=rank, reverse=True)
    return candidates[0]


class AgyAdapter(AgentAdapter):
    id = "agy"
    keeps_stdin_open = True
    subagents = True
    subagent_hint = " (invoke_subagent; Model \"flash\" is enough to read and check)"
    supports_steer = True
    ONESHOT_MODEL = "gemini-3.8-flash-low"

    def resolve_model(self, model: str) -> str:
        return _resolve_agy_model(model, self.known_models())

    def last_activity(self, pid: int, started: float, conversation_id: str = "") -> Optional[float]:
        """When the agent last did something. With `conversation_id` (a live session): the newest write to that
        conversation's transcript or to the transcript of a subagent it started (SUBAGENT_ACTIVITY_v1: a parent
        prints nothing while its subagents work, and the turn was closed as silent -- 2026-10-05, 4 hangs and 8
        notices on one session in 40 minutes). Otherwise the last model call (`streamGenerateContent`) in the agy log of
        process `pid` -- its conversation's transcripts when the log names one (WORKER_ACTIVITY_v1: agy 1.2.16 no longer
        logs model calls), else its `streamGenerateContent` lines; `started` while it has done nothing; None when no log
        names that pid yet. 83 worker runs to 2026-09-30 never went more
        than 303 s between calls; a stalled stream went 18 min (#462)."""
        if conversation_id:
            seen = _brain_activity(conversation_id)
            if seen:
                return seen
        from providers import accounts
        path = accounts.agy_log_for(pid, started)
        if path is None:
            return None
        cid = _log_conversation(path)   # WORKER_ACTIVITY_v1: a delegated worker has no session, but its log names its
        if cid:                         # conversation (#692: the probe said "nothing since start", a long worker was cut)
            seen = _brain_activity(cid)
            return max(seen, started) if seen else started
        try:
            with open(str(path), "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return None
        hits = re.findall(r"^[IWE](\d{2})(\d{2}) (\d{2}):(\d{2}):(\d{2})\S* +\d+ \S+\] URL: \S+streamGenerateContent", tail, re.M)
        if not hits:
            return started
        mo, day, h, mi, sec = (int(x) for x in hits[-1])
        year = time.localtime(started).tm_year
        return time.mktime((year, mo, day, h, mi, sec, 0, 0, -1))

    def has_conversation(self, conversation_id: Optional[str]) -> Optional[bool]:
        """agy resumes `--conversation <id>` only if its store has it; otherwise it silently starts
        an empty one."""
        if not conversation_id:
            return False
        from session_weights import _conversation_db_path
        db = _conversation_db_path(conversation_id)
        return bool(db is not None and db.exists())

    def find_executable(self) -> str:
        return AGY

    def oneshot(self, prompt: str, timeout: float = 20.0) -> Optional[Dict[str, Any]]:
        """`agy -p` with stream-json output: the `result` event carries the answer and usage."""
        out: Dict[str, Any] = {"text": "", "usage": None, "duration_seconds": None, "error": ""}
        cmd = [self.find_executable(), "-p", prompt, "--output-format", "stream-json",
               "--model", self.ONESHOT_MODEL, "--dangerously-skip-permissions"]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            out["error"] = "timeout"
            return out
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)
            return out
        if res.returncode != 0 or not res.stdout.strip():
            out["error"] = (res.stderr or "").strip()[-2000:] or "exit %s" % res.returncode
            return out
        for line in res.stdout.splitlines():
            try:
                obj = json.loads(line.strip())
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("event") == "result":
                r = obj.get("result") or {}
                out.update(text=str(r.get("response") or "").strip(), usage=r.get("usage"),
                           duration_seconds=r.get("duration_seconds"))
                break
        if not out["text"]:
            out["text"] = res.stdout.strip()
        return out

    def native_compact(self, conversation_id: Optional[str], timeout: float = 45.0) -> str:
        """agy's own `/compact` of that conversation: sees the full history and tool state."""
        if not conversation_id:
            return ""
        try:
            res = subprocess.run(
                [self.find_executable(), "-p", "/compact", "--conversation", conversation_id,
                 "--model", self.ONESHOT_MODEL, "--dangerously-skip-permissions"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
            return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else ""
        except Exception:  # noqa: BLE001
            return ""

    def known_models(self) -> List[str]:
        return cached_model_list(_AGY_MODELS_CACHE, self._fetch_models) or MODELS

    def _fetch_models(self) -> List[str]:
        res = subprocess.run([self.find_executable(), "models"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, timeout=10)
        if res.returncode != 0 and isinstance(res.returncode, int):
            return []
        models: List[str] = []
        for line in (res.stdout or "").splitlines():
            line = line.strip()
            if not line or line.startswith("Fetching"):
                continue
            model_name = line.split("\t")[0].strip()
            if model_name and model_name not in models:
                models.append(model_name)
        return models

    def build_args(self, model: str, effort: str, conversation_id: Optional[str], add_dirs: List[str], prompt: str = "") -> List[str]:
        model = self.resolve_model(model)
        args = [
            self.find_executable(),
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--print-timeout", f"{AGY_PRINT_TIMEOUT_SEC}s",
            "--dangerously-skip-permissions",
            "--mode", "accept-edits",
            "--model", model,
        ]
        # Skills / AGENTS.md should expand; do NOT disable slash commands by default
        for d in add_dirs:
            if Path(d).exists():
                args.extend(["--add-dir", d])
        if effort and not _MODEL_NAMES_EFFORT.search(model or ""):   # "gemini-3.8-flash-high" + --effort low: agy refuses
            args.extend(["--effort", effort])
        if conversation_id:
            args.extend(["--conversation", conversation_id])
        return args

    def build_env(self, home: Path) -> dict:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{AGENT_PATH_PREFIX}:{env.get('PATH','')}"
        mcp_cfg = WORKSPACE / ".gemini" / "config" / "mcp_config.json"
        if mcp_cfg.exists():
            env["AGY_WORKSPACE"] = str(WORKSPACE)
        return env

    def format_stdin(self, content: str) -> str:
        return json.dumps({"event": "user", "message": {"content": content}}, ensure_ascii=False) + "\n"

    def _tool_info_events(self, session: "AgentSession", obj: dict) -> List[dict]:
        """A tool step (docs/providers/agy.md A37: `step_update{step_type:"tool", state:ACTIVE→DONE,
        tool_info:{name, parameters, output}}`) as canonical tool events: the call once its parameters are
        known, the result once DONE. ACTIVE and DONE repeat the call, so each is sent once per step."""
        step = obj.get("step_update")
        info = step.get("tool_info") if isinstance(step, dict) else None
        if not isinstance(info, dict):
            return []
        name = str(info.get("name") or step.get("tool_name") or "").strip()
        params = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}
        done = str(step.get("state") or "") == "DONE"
        # Once per STEP, not per last key: steps interleave (3 ACTIVE, 4 ACTIVE, 3 DONE), and a DONE without its
        # parameters names the call differently from its ACTIVE -- either made a second call card (review of #505).
        seen = session.__dict__.setdefault("_tool_info_seen", {})
        events: List[dict] = []
        call = _format_tool_call(name, params) if params else ""
        if not call and done:
            call = name
        sk = step.get("step_index")
        mark = seen.setdefault(("step", sk) if sk is not None else ("call", call or name), set())
        if len(seen) > 64:                      # a long turn: forget the oldest steps
            for old in list(seen)[:len(seen) - 64]:
                seen.pop(old, None)
        if call and "call" not in mark:
            mark.add("call")
            ev = {"event": "tool", "text": call[:600], "title": name[:200], "kind": "call", "status": "calling"}
            if params:
                ev["detail"] = json.dumps(params, ensure_ascii=False, indent=2)[:4000]
            events.append(ev)
        if done and "result" not in mark:
            mark.add("result")
            out = info.get("output")
            out = out if isinstance(out, str) else ("" if out is None else json.dumps(out, ensure_ascii=False))
            summary = _format_tool_result(out or "\n")   # no output: tool_format's own "done" line
            ev = {"event": "tool", "text": summary[:600], "title": name[:200], "kind": "result", "status": "done"}
            if len(out.strip()) > len(summary) or "\n" in out.strip():
                ev["detail"] = out[:4000]
            events.append(ev)
        return events

    @staticmethod
    def _note_call(session: "AgentSession", obj: dict) -> None:
        """The conversation id, and CONTEXT_METRIC_v1: one model call's prompt (new + cached). The result's usage
        sums every call of the turn, which read as a 240-500k "context" for a 50-90k one and rotated sessions for
        nothing (10/04)."""
        session._maybe_capture_conversation_id(obj)
        step = obj.get("step_update")
        if isinstance(step, dict) and isinstance(step.get("usage"), dict):
            u = step["usage"]
            session._call_context = int(u.get("input_tokens") or 0) + int(u.get("cache_read_tokens") or 0)

    @staticmethod
    def _turn_usage(session: "AgentSession", res_obj: dict) -> Optional[dict]:
        """This turn's usage, with the last call's prompt as `context_tokens` (CONTEXT_METRIC_v1).
        TURN_USAGE_v1: agy reports the conversation's running total, not the turn's (measured 2026-10-05: 42,941 then
        57,662 = 42,941 + the one call of a "ping" turn; and 2.1M input on the first turn of a fresh process resuming a
        long conversation), so the turn's share is the total minus the one recorded with the conversation's previous
        turn (`running_total` in its usage, kept in the history so a restart does not lose it). A turn that ran to the print timeout is marked
        (`_turn_timed_out`): its text is whatever was said before the wait, not an answer. Timed by the engine's
        clock: agy's own duration_seconds is the conversation's running total as well (54.4 s, then 147.6 s for a
        turn that took a moment), which failed handoff #8 after #7 had run long."""
        started = float(getattr(session, "turn_started_at", 0) or 0)
        session._turn_timed_out = bool(started) and time.time() - started >= 0.9 * AGY_PRINT_TIMEOUT_SEC
        raw = res_obj.get("usage") if isinstance(res_obj.get("usage"), dict) else None
        if raw is not None:
            conv = str(getattr(session, "conversation_id", "") or "")
            base = next((u["running_total"] for u in (h.get("usage") for h in reversed(getattr(session, "history", []) or []))
                         if isinstance(u, dict) and isinstance(u.get("running_total"), dict)
                         and u["running_total"].get("conversation") == conv), None)
            total = {k: v for k, v in raw.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            if base:
                raw = {k: max(0, v - int(base.get(k) or 0)) if k in total else v for k, v in raw.items()}
            raw = {**raw, "running_total": {**total, "conversation": conv}}
            if getattr(session, "_call_context", 0):
                raw = {**raw, "context_tokens": session._call_context}
        session._call_context = 0
        return raw

    def normalize_line(self, session: "AgentSession", raw_line: str) -> List[dict]:
        """Moved verbatim out of `AgentSession._handle_stdout_line` (Multi-Provider
        plan Phase 0) -- same parsing, same session-mutation order, same
        returned event shapes. Only structural change: events are collected
        and returned instead of emitted inline, so `_handle_stdout_line` can
        stay provider-agnostic (see AgentAdapter.normalize_line docstring for
        why this still takes `session` instead of being a pure function)."""
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            return [{"event": "raw", "text": raw_line[:2000]}]
        if not isinstance(obj, dict):
            return []

        self._note_call(session, obj)
        session._observe_agent_step(obj)

        events: List[dict] = []
        tool_ev = session._tool_summary(obj)   # still run: it stages images and arms the error_message failfast
        own = self._tool_info_events(session, obj)
        if own or (isinstance(obj.get("step_update"), dict) and "tool_info" in obj["step_update"]):
            tool_ev = own   # a tool_info step is parsed here, not by the session's generic guess
        if tool_ev:
            if isinstance(tool_ev, list):
                events.extend(tool_ev)
            else:
                events.append(tool_ev)

        ev = obj.get("event") or obj.get("type") or "message"
        text = ""
        is_delta = False
        step = obj.get("step_update")
        if isinstance(step, dict) and step.get("step_type") == "agent_response" and isinstance(step.get("text_delta"), str):
            text = step.get("text_delta") or ""
            ev = "delta"
            is_delta = True
        if isinstance(obj.get("text"), str) and not text:
            text = obj["text"]
        msg = obj.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                bits = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        bits.append(str(part.get("text") or ""))
                    elif isinstance(part, str):
                        bits.append(part)
                if bits:
                    text = "".join(bits)
        delta = obj.get("delta") or obj.get("content_block_delta")
        if isinstance(delta, dict) and delta.get("text"):
            text = str(delta.get("text"))
            ev = "delta"
            is_delta = True

        if text:
            text = session._rewrite_artifact_paths(text)

        # Compute delta_offset AFTER rewrite so the client assistantBuf index
        # matches the server-side rewritten-length counter (P2 fix).
        delta_offset = None
        if is_delta and text is not None:
            delta_offset = len(session.current_text or "")
            session.current_text = (session.current_text or "") + text

        if ev == "result":
            res_obj = obj.get("result") if isinstance(obj.get("result"), dict) else {}
            raw_usage = self._turn_usage(session, res_obj)
            res_err = self._fresh_error(session, str(res_obj.get("error") or obj.get("error") or ""),
                                        str(res_obj.get("status") or ""), session.current_text or text)
            # the operator pressed stop: the CLI's "interrupted" is the stop itself, not a failure to report
            is_err = bool(res_err) and not session._stop_requested
            out_ev = self.finalize_turn(
                session=session,
                text=text,
                raw_usage=raw_usage,
                is_err=is_err,
                error=res_err if is_err else None,
            )
            final = out_ev.get("text") or ""
            duration_seconds = out_ev.get("duration_seconds")
            status = str(res_obj.get("status") or "")
            dur = float(duration_seconds or 0)   # the engine's own timing; agy's is the conversation's running total
            # TURN_END_ORDER_v1: append the terminal event FIRST, then ask
            # session to stop the child AFTER _handle_events flushes it.
            # Never call _end_unfinished_turn here — it _emit/_auto_stop
            # immediately and races ahead of the answer paint.
            events.append(out_ev)
            need_stop = (not session._stop_requested) and (
                status not in ("", "SUCCESS")
                or (not final.strip() and dur >= 0.9 * AGY_PRINT_TIMEOUT_SEC)
            )
            if need_stop:
                # Extra Korean unfinished notice only when finalize did not
                # already produce error/answer — empty SUCCESS timeout case.
                extra = None
                if (
                    not final.strip()
                    and out_ev.get("event") != "error"
                    and status in ("", "SUCCESS")
                ):
                    why = (
                        f"status={status or '?'}"
                        + (f", error={res_err}" if res_err else "")
                        + f", {int(dur)}s"
                    )
                    extra = {"event": "error", "notice": "error", **i18n.msg("srv.turn_ended_early", why=why)}
                    events.append(extra)
                session._request_post_result_stop(status, res_err, dur)

        elif ev in ("assistant", "message", "delta", "error", "system") or (ev in ("tool_use", "tool_result") and not tool_ev):
            out = {"event": ev, "text": text, "raw_event": ev}
            if ev == "delta" and delta_offset is not None:
                out["offset"] = delta_offset
            if obj.get("error"):
                out["error"] = obj.get("error")
            events.append(out)
        elif not tool_ev:
            events.append({"event": "provider_event", "text": text, "payload": {k: obj.get(k) for k in list(obj)[:12]}})

        return events

    @staticmethod
    def _fresh_error(session, err: str, status: str, answer) -> str:
        """STALE_ERROR_v1: agy's result reports the conversation, not the turn -- after one failed turn (a quota hit on
        the Claude route, 2026-10-08) every later result in that conversation still carries the same error, and each
        good Gemini answer was stored as failed. The same error text again, on a turn that ended SUCCESS with an
        answer, is that old one: not this turn's. A first error, a changed one, or a turn with no answer stays."""
        conv = str(getattr(session, "conversation_id", "") or "")
        seen = getattr(session, "_agy_seen_error", None)
        if err:
            session._agy_seen_error = (conv, err)
        if err and seen == (conv, err) and status in ("", "SUCCESS") and str(answer or "").strip():
            return ""
        return err

    def rate_limit_report(self) -> Optional[dict]:
        """`agy --print /usage` -- the CLI's own rate-limit report; unavailable
        inside a stream-json session, must be a separate one-shot invocation.
        Moved out of the old module-level `_get_usage()` (Multi-Provider plan
        Phase 0.5) so that function can become a generic provider-dispatching
        + caching wrapper instead of hardcoding this agy-only subprocess call."""
        try:
            proc = subprocess.run([self.find_executable(), "--print", "/usage"], capture_output=True, text=True, timeout=30)
            rows = []
            # Strip CSI/C0 so a colorized post-login banner doesn't break the
            # tab-split parsing below (same fix as ClaudeAdapter's /cost parsing).
            stdout = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", proc.stdout or "")
            stdout = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", stdout)
            for line in stdout.splitlines():
                parts = [p.strip() for p in line.split("\t")]
                if len(parts) >= 4:
                    rows.append({"group": parts[0], "limit_type": parts[1], "remaining_pct": parts[2], "reset_at": parts[3]})
            if not rows and proc.stderr:
                return {"error": _redact_err(proc.stderr)[:400]}
            return {"rows": rows}
        except Exception as e:
            return {"error": str(e)}

    def quota_view(self, model: str, rows: list) -> dict:
        """QUOTA_VIEW_v1: agy's limits are per model GROUP ("Gemini Models", "Claude and GPT models"), each with a
        five-hour and a weekly window. The group is the one whose name holds the model's family word (the part of
        the id before the first '-': gemini, claude, gpt); no match -> every group."""
        family = re.split(r"[-/]", str(model or ""), maxsplit=1)[0].lower()
        mine = [r for r in rows or [] if family and family in str(r.get("group", "")).lower()]
        short = lambda r: ("5h" if "five" in r.get("limit_type", "").lower() else "week" if "week" in r.get("limit_type", "").lower()
                           else r.get("limit_type", ""))
        if not mine:
            return quota_view_of(rows, "", lambda r: f"{r.get('group', '')} {short(r)}".strip())
        mine.sort(key=lambda r: "five" not in r.get("limit_type", "").lower())   # the short window first
        return quota_view_of(mine, str(mine[0].get("group", "")), short)


class AgyMediaSource(_media.MediaSource):
    """agy writes a conversation's files under its brain store: BRAIN/<conversation id>/."""

    def _dir(self, conversation_id):
        if not conversation_id:
            return None
        d = _media._cfg("BRAIN") / conversation_id
        return d if d.is_dir() else None

    def artifact_dirs(self, conversation_id):
        d = self._dir(conversation_id)
        return [d, d / ".tempmediaStorage"] if d else []

    def scan_dirs(self, conversation_id, cutoff):
        d = self._dir(conversation_id)
        out = [d, d / ".tempmediaStorage", d / ".system_generated"] if d else []
        brain = _media._cfg("BRAIN")
        try:
            if brain.exists():
                for sub in brain.iterdir():
                    try:
                        if sub != d and sub.is_dir() and sub.stat().st_mtime >= cutoff - 5:
                            out.append(sub)
                    except OSError:
                        continue
        except Exception:  # noqa: BLE001
            pass
        return out

    def text_roots(self):
        return [_media._cfg("BRAIN")]
