"""What a session shows (monolith-split split/C, moved from session.py as a mixin of AgentSession, like
turn_watchdog.py): its public view, the tool activity lines, the activity log, the artifacts gallery, the handover
summary, the handoff text that summary is built from, the trimmed screen record used when a process restarts, the image paths staged into an answer, and the events sent to the screen. The paths and helpers that tests point elsewhere
(SESSIONS, WORKSPACE, DATA, get_adapter, _oneshot, ...) are read from `session` on every call, never copied at import."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from session_weights import _billed_tokens, _current_context_tokens
from tool_format import _format_tool_call, _format_tool_result


def _session():
    import session
    return session


SKIP_TOOL_NOISE = {"", "tool", "step", "step_update", "unknown", "agent_response"}


def _make_tool_event(text: str, title: str, kind: str, status: str, detail: Any = None) -> dict:
    ev = {"event": "tool", "text": text[:600], "title": title[:200], "kind": kind, "status": str(status)[:80]}
    if detail:
        d = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, indent=2)
        if len(d) > 2 and (len(d) > len(text) or "\n" in d or isinstance(detail, dict)):
            ev["detail"] = d[:4000]
    return ev


class SessionView:
    def _step_update_summary(self, step: dict) -> Union[dict, None]:
        stype = str(step.get("step_type") or step.get("type") or "").strip()
        if stype in ("agent_response",):
            return None
        title = step.get("title") or step.get("name") or step.get("tool") or step.get("tool_name") or step.get("function") or ""
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
            args_dict, text = {}, ""
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
        ev = _make_tool_event(text, title or stype, "call", status, args_dict)
        ev["step_type"] = stype[:80]
        if stype == "error_message":
            hint = ""
            for k in ("error", "message", "text", "summary", "description", "detail"):
                val = step.get(k)
                if isinstance(val, str) and val.strip():
                    hint = val.strip()[:500]
                    break
            if not hint:
                for nest in (step.get("result"), step.get("output"), step.get("content"), args_dict):
                    if isinstance(nest, dict):
                        for k in ("error", "message", "text"):
                            val = nest.get(k)
                            if isinstance(val, str) and val.strip():
                                hint = val.strip()[:500]
                                break
                    if hint:
                        break
            if hint:
                ev["detail"] = hint
                self._err_msg_hint = hint
            self._arm_error_message_failfast()
        return ev

    def _tool_summary(self, obj: dict) -> Union[dict, List[dict], None]:
        """Surface tool activity with detailed arguments and results."""
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
                    args = args if isinstance(args, dict) else {}
                    text = _format_tool_call(name, args)
                    if text and text != self._last_tool_sig:
                        self._last_tool_sig = text
                        events.append(_make_tool_event(text, name, "call", "calling", args))
            if events:
                return events

        # 2. Antigravity GENERIC tool execution result
        if obj.get("type") == "GENERIC" and isinstance(obj.get("content"), str) and obj.get("content").strip():
            raw = obj["content"].strip()
            res_summary = _format_tool_result(raw)
            if res_summary and res_summary != self._last_tool_sig:
                self._last_tool_sig = res_summary
                return _make_tool_event(res_summary, "result", "result", "done", raw)

        # 3. step_update format
        step = obj.get("step_update")
        if isinstance(step, dict):
            return self._step_update_summary(step)

        # 4. classic tool_use / tool_call / tool_result / tool_error
        ev = obj.get("event") or obj.get("type")
        if ev in ("tool_use", "tool_call"):
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            args = obj.get("args") or obj.get("input") or obj.get("parameters") or {}
            args = args if isinstance(args, dict) else {}
            text = _format_tool_call(name, args) if args else name
            if text and text.lower() not in SKIP_TOOL_NOISE and text != self._last_tool_sig:
                self._last_tool_sig = text
                return _make_tool_event(text, name, "call", str(ev), args)

        if ev in ("tool_result", "tool_error"):
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            raw = obj.get("output") or obj.get("content") or obj.get("result") or ""
            raw_str = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, indent=2)
            res_text = _format_tool_result(raw_str) if raw_str else f"{ev}: {name or 'done'}"
            if res_text and res_text != self._last_tool_sig:
                self._last_tool_sig = res_text
                return _make_tool_event(res_text, name or "result", "result", str(ev), raw_str)

        # 5. nested message tool_use / tool_result blocks
        msg = obj.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            events = []
            for part in msg["content"]:
                if isinstance(part, dict):
                    ptype = part.get("type")
                    if ptype == "tool_use":
                        name = str(part.get("name") or "").strip()
                        args = part.get("input") or {}
                        args = args if isinstance(args, dict) else {}
                        text = _format_tool_call(name, args)
                        if text and text != self._last_tool_sig:
                            self._last_tool_sig = text
                            events.append(_make_tool_event(text, name, "call", "tool_use", args))
                    elif ptype == "tool_result":
                        res = str(part.get("content") or part.get("output") or "")
                        text = _format_tool_result(res) if res else "↳ tool_result: done"
                        if text and text != self._last_tool_sig:
                            self._last_tool_sig = text
                            events.append(_make_tool_event(text, "result", "result", "tool_result", res))
            if events:
                return events
        return None

    def get_handover_summary(self, max_turns: int = 8, use_cache: bool = True, native: bool = True) -> str:
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
        `native=False` makes no model call at all: the visible history, trimmed
        (instant; for a caller that must not block, e.g. an in-place provider
        swap, which refines it in the background -- _refine_swap_handoff).
        """
        if use_cache and getattr(self, "_cached_summary", ""):
            return self._with_last_exchange(self._cached_summary)
        if not native:
            return self._host_history_digest(header="(The provider changed. Below is the recent talk from the screen record. Carry on.)")

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
        if cid:
            base = self._native_compact(self.provider, cid)

        if not base:
            base = self._dialogue_summary_fallback(max_turns)

        # only the compressed summary (base) is cached; the recent talk is joined when returned (operator's idea, 2026-09-17).
        if use_cache:
            self._cached_summary = base
        return self._with_last_exchange(base)

    def to_public(self) -> dict:
        _redact_line, ADD_DIRS = _session()._redact_line, _session().ADD_DIRS
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
            "character": getattr(self, "character", "") or "",
            "mode": getattr(self, "mode", "work") or "work",
            "busy": really_busy,
            "queue_len": len(getattr(self, "msg_queue", [])),
            "alive": self._proc_alive(),
            "current_text": draft,
            "turn_started_at": float(self.turn_started_at or 0) if really_busy else 0,
            "last_progress": (getattr(self, "last_progress", "") or "") if really_busy else "",
            "last_progress_key": (getattr(self, "last_progress_key", "") or "") if really_busy else "",
            "last_progress_vars": (getattr(self, "last_progress_vars", None) or {}) if really_busy else {},
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

    def _collect_artifact_roots(self) -> Tuple[List[Path], Dict[Path, str], Set[Path]]:
        SESSIONS = _session().SESSIONS
        provider_dirs = list(self._artifact_dirs())
        roots = list(provider_dirs)
        session_roots: Dict[Path, str] = {}

        my_adir = self.meta_path.parent / "artifacts"
        session_roots[my_adir] = self.sid
        roots.append(my_adir)

        curr_pred = getattr(self, "predecessor_session_id", "") or ""
        seen_sids = {self.sid}
        while curr_pred and curr_pred not in seen_sids:
            seen_sids.add(curr_pred)
            p_dir = SESSIONS / curr_pred / "artifacts"
            session_roots[p_dir] = curr_pred
            roots.append(p_dir)
            p_meta = SESSIONS / curr_pred / "meta.json"
            curr_pred = ""
            if p_meta.is_file():
                try:
                    data = json.loads(p_meta.read_text(encoding="utf-8"))
                    curr_pred = str(data.get("predecessor_session_id") or "")
                except Exception:
                    break
        return roots, session_roots, set(provider_dirs)

    def get_artifacts(self) -> List[dict]:
        exts_img = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
        exts_doc = {".md", ".txt", ".json", ".pdf", ".html", ".csv", ".yaml", ".yml"}
        exts_code = {".py", ".js", ".ts", ".gd", ".sh", ".sql", ".css"}

        roots, session_artifact_roots, brain_source_roots = self._collect_artifact_roots()
        found = []
        seen_sizes = set()
        seen_names = set()

        for root in roots:
            if not root or not Path(root).exists():
                continue
            try:
                for fp in Path(root).rglob("*"):
                    if not fp.is_file() or fp.name.startswith("."):
                        continue
                    try:
                        nested = fp.relative_to(root).parts[:-1]
                    except ValueError:
                        nested = fp.parts[:-1]
                    if any(part.startswith(".") for part in nested):
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
                    if root in brain_source_roots:
                        url = self._stage_image(fp)
                    elif root in session_artifact_roots:
                        owner_sid = session_artifact_roots[root]
                        url = f"/artifacts/{owner_sid}/{fp.relative_to(root).as_posix()}"
                    else:
                        url = f"/artifacts/{fp.name}"

                    sz_str = f"{sz / 1048576:.1f} MB" if sz >= 1048576 else (f"{sz / 1024:.0f} KB" if sz >= 1024 else f"{sz} B")

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

    @staticmethod
    def _native_compact(provider: str, cid: str) -> str:
        """That provider's own summary of conversation `cid` (adapter hook; "" when it has none)."""
        try:
            return _session().get_adapter(provider).native_compact(cid)
        except Exception:  # noqa: BLE001
            return ""

    def _recent_turns(self, max_turns: int, max_hops: int = 10) -> List[dict]:
        """The last `max_turns` user/assistant turns of this conversation, oldest first: this session's, then back
        along predecessor_session_id. Sessions here are often 2-8 turns long, so one session alone was not enough
        (#613). Read-only; a missing or broken predecessor ends the walk."""
        turns = [h for h in self.history if h.get("role") in ("user", "assistant")]
        pred, seen = str(getattr(self, "predecessor_session_id", "") or ""), {self.sid}
        while len(turns) < max_turns and pred and pred not in seen and len(seen) <= max_hops:
            seen.add(pred)
            try:
                meta = json.loads((_session().SESSIONS / pred / "meta.json").read_text(encoding="utf-8"))
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
            label = _session().user_title() if role == "user" else _session().display_name()
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
        return f"{prefix}[Recent talk, verbatim]\n" + "\n".join(lines) + "\n"

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

        prompt = _session()._handoff_prompt(dialogue_blob)

        r = _session()._oneshot(prompt, 12)
        if r and r.get("text"):
            return r["text"]

        # Deterministic fallback when no provider answered
        user_turns = [h.get("text") for h in self.history if h.get("role") == "user"]
        asst_turns = [h.get("text") for h in self.history if h.get("role") == "assistant"]
        last_u = str(user_turns[-1] if user_turns else "")[:120]
        last_a = str(asst_turns[-1] if asst_turns else "")[:120]
        return f"- Last instruction from {_session().user_title()}: {last_u}\n- Last answer: {last_a}"

    def _rewrite_artifact_paths(self, text: str) -> str:
        return _session()._rewrite_artifact_paths(self.sid, self.conversation_id, text)

    def _artifact_dirs(self) -> List[Path]:
        """The provider's own folders for this conversation (media_handler registry)."""
        return _session()._artifact_dirs(self.conversation_id)

    def _collect_new_images(self, since_ts: Optional[float] = None) -> list:
        return _session()._collect_new_images(self.conversation_id, self.last_activity, since_ts)

    def _stage_image(self, src: Path) -> Optional[str]:
        return _session()._stage_image(self.sid, src)

    def _append_images_markdown(self, text: str, since_ts: Optional[float] = None) -> str:
        return _session()._append_images_markdown(self.sid, self.conversation_id, self.last_activity, text, since_ts)

    def _host_history_digest(self, max_turns: int = 8, per_turn: int = 700, total: int = 5000,
                             header: str = "(The agent process restarted and its memory did not carry over. Below is the recent talk from the screen record.)") -> str:
        """The visible history, trimmed -- no model call, so it is instant and free."""
        me, ut = _session().display_name(), _session().user_title()
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

    def _emit(self, event: dict) -> None:
        host = _session()
        self.last_activity = host._now()
        kind = event.get("event")
        if kind in ("tool", "system"):
            # QUOTA_ERR_DEDUP_v1: agy surfaces quota as step_type/title error_message
            step = str(event.get("step_type") or event.get("title") or "").strip()
            line = (event.get("title") or event.get("text") or "").strip()
            is_err_msg = step == "error_message" or line == "error_message"
            if is_err_msg:
                line = host.i18n.text("srv.checking_quota")
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
        if kind in host.PERSISTED_LOG_KINDS:
            self._append_log_event(event)
        if kind in host._OBS_FORWARD:
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
            host = _session()
            obslog = host.obslog
            LOOP_NOTICE_KEYS = host.LOOP_NOTICE_KEYS
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

    def _append_log_event(self, event: dict) -> None:
        try:
            entry = dict(event)
            entry.setdefault("ts", _session()._now())
            path = self.meta_path.parent / "events.jsonl"
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
