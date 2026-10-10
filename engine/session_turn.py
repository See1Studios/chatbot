"""Running a turn (monolith-split split/C, moved from session.py as a mixin of AgentSession, like turn_watchdog.py
and session_view.py): send (queue, steer, the HTTP turn, rotate when idle or heavy), the turn itself, ending a turn, the session's weight, /btw side questions, interrupt,
handing over to a successor session, and swapping the provider or model. Every name session.py defines or tests and
server.py swap (REG, boot_notice, build_instruction_bundle, _oneshot, get_adapter, ...) is read as `_s().name` on
each call, never copied at import."""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Dict, List, Optional

import i18n
from telemetry import obslog
from host_config import INACTIVITY_ROTATE_SEC, _now
from identity import user_title
from private_engine import step_turn
from session_weights import _btw_prompt, _is_inquiry


REFRESH_MAX_CHARS = 2000   # one refreshed layer's share of a turn (CONTEXT_REFRESH_v1)


def _dynamic_hashes(bundle: Dict[str, Any]) -> Dict[str, str]:
    return {x["id"]: x["hash"] for x in bundle.get("layers") or [] if x.get("kind") == "dynamic"}


def _s():
    import session
    return session


class SessionTurn:
    def engine_choices(self, choices: list) -> list:
        """The choices the engine adds to this turn's answer (engine-decides): a marked personal turn in a work room
        gets the move choice (MOVE_CHOICE_v1, ed/B2). The answer's own choices come first and stay."""
        if getattr(self, "mode", "work") == "private":
            return choices
        import items
        import personal_turn
        try:
            root = self.meta_path.parent.parent
            turn = personal_turn.running_turn(self.history)
            personal_turn.await_judgment(root, self.sid, turn)   # a judgment still in flight would miss the chips
            extra = personal_turn.move_choices(root, self.sid, turn,
                                               items.state_path(self.character) if getattr(self, "character", "") else None)
        except Exception:  # noqa: BLE001 -- an extra choice must never break the answer
            extra = []
        for iid in getattr(self, "_turn_offer", None) or []:   # improvement-layers il/E: the operator decides
            extra += [{"label": "Make it work #%d" % iid, "label_key": "choice.incident_ticket", "label_vars": {"id": iid},
                       "kind": "command", "payload": "/incident ticket %d" % iid},
                      {"label": "Ignore #%d" % iid, "label_key": "choice.incident_ignore", "label_vars": {"id": iid},
                       "kind": "command", "payload": "/incident ignore %d" % iid}]
        self._turn_offer = []
        return list(choices or []) + extra

    def _run_btw(self, query: str) -> None:
        query = (query or "").strip()
        if not query:
            self._emit({"event": "btw", "query": "", **i18n.msg("srv.btw_usage", user=user_title())})
            return
        self._emit({"event": "btw_start", "query": query})
        context_snippets = []
        with self.lock:
            is_active = bool(self.busy and self._proc_alive())
            silent = is_active and bool(getattr(self, "is_silent", False))
            cur_tool = getattr(self, "_last_tool_sig", "") or ""
            recent_hist = [f"{h.get('role')}: {str(h.get('text') or '')[:120]}" for h in self.history[-4:] if h.get("role") in ("user", "assistant")]
        if is_active:
            context_snippets.append(f"[Main work running in the background: {cur_tool}]" if cur_tool else "[The main work is thinking/working in the background]")
            if silent:
                context_snippets.append(f"[The main work has been silent for over {int(self.SILENT_NOTICE_SEC)}s. It may be delayed or stuck.]")
        else:
            context_snippets.append("[No main work is running in the background. The last work finished, waits, or was stopped.]")
        if recent_hist:
            context_snippets.append("[Recent talk:\n" + "\n".join(recent_hist) + "]")

        prompt = _btw_prompt(query, is_active, context_snippets, silent)
        ans_msg = i18n.msg("srv.btw_no_answer")   # the side answer's words when no model gave one (I18N_v1)
        ans = ""
        usage = None
        duration_seconds = None
        r = _s()._oneshot(prompt, 20)
        if r is None:
            ans_msg = i18n.msg("srv.btw_no_provider")
        elif r.get("text"):
            ans, ans_msg, usage, duration_seconds = r["text"], None, r.get("usage"), r.get("duration_seconds")
        elif r.get("error") == "timeout":
            ans_msg = i18n.msg("srv.btw_timeout")
        elif r.get("error"):
            ans = _s()._redact_text(r["error"]) or ""
            ans_msg = None if ans else ans_msg
        if ans_msg:
            ans = ans_msg["text"]
        said = ans_msg or {"text": ans}   # a model's answer goes as it came; the host's own line goes by key

        with self.lock:
            item = {"role": "btw", "query": query, **said, "ts": _now()}
            if usage:
                item["usage"] = usage
            if duration_seconds is not None:
                item["duration_seconds"] = duration_seconds
            self.history.append(item)
            self.save_meta()
        out = {"event": "btw", "query": query, **said, "ts": item["ts"]}
        if usage:
            out["usage"] = usage
        if duration_seconds is not None:
            out["duration_seconds"] = duration_seconds
        self._emit(out)

    def _rotate_to_fresh_session(self, text: str, reason: str = "heavy", client_mid: str = "", client_context: Optional[Dict[str, Any]] = None, event_type: str = "") -> "AgentSession":
        """Sticky rotate: reuse successor_session_id when usable; else create once and remember with handover."""
        msg = i18n.msg("srv.rotated_inactivity" if reason == "inactivity" else "srv.rotated_heavy")
        succ_id = getattr(self, "successor_session_id", "") or ""
        if succ_id and self._successor_usable(succ_id):
            new_sess = _s().REG.get(succ_id)
        else:
            # The summary is up to two model calls: the page's waiting message hears that the server is at work (#812)
            self._emit({"event": "stage", **i18n.msg("srv.handoff_stage")})   # #887: a stage line, not the bubble
            summary = self.get_handover_summary()
            brain = _s().REG.rotation_brain(self)   # #885: the saved brain, not this session's model
            new_sess = _s().REG.create(
                model=brain["model"],
                effort=brain["effort"],
                predecessor_sid=self.sid,
                handoff_summary=summary,
                # same fix as continue_to_successor(): without it the successor starts as agy
                # with this provider's model name (e.g. claude "sonnet") and the turn dies with
                # "invalid model selection" (2026-09-21, also seen with grok-4.6)
                provider=brain["provider"],
                character=self.character,
                mode=self.mode,
            )
            self.successor_session_id = new_sess.sid
            try:
                self.save_meta()
            except Exception:
                pass
        # client_mid lets the sending tab's own SSE handler recognize this
        # rotation as one it already knows about (the /message HTTP response
        # itself carries the same info) and skip re-rendering -- without
        # this, both the SSE event (emitted here, before the slow successor
        # spawn/send below) and the POST response (arriving after) independently
        # re-entered the new session, and the SSE one (missing the user's
        # own just-typed text) usually rendered first, making the message
        # look like it vanished (operator: "the moment I speak it moves to a new session and I have to
        # say it again").
        self._emit({
            "event": "session_rotate",
            **msg,
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
        kw = {"event_type": event_type} if event_type else {}
        if client_context:
            kw["client_context"] = client_context
        new_sess._send_direct(text, client_mid, **kw)
        return new_sess

    def _is_busy(self) -> bool:
        return bool(self.busy or getattr(self, "_steering", False) or getattr(self, "_loop_stopping", False))

    def send(self, text: str, client_mid: str = "", client_context: Optional[Dict[str, Any]] = None, event_type: str = ""):
        """Return None (same session) or AgentSession if hard-rotated to a fresh session."""
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")

        if text.startswith("/btw ") or text.startswith("/btw\n") or text == "/btw":
            query = text[4:].strip()
            threading.Thread(target=self._run_btw, args=(query,), daemon=True).start()
            return None

        restore = getattr(self, "_regen_restore", "")   # #883: a harder-thinking take was one take; back to the chosen brain
        if restore and not self._is_busy():
            self._regen_restore = ""
            self.maybe_swap_model(restore, remember=False)
        # Soft warn anytime; hard rotate before appending more to bloated conversation.
        # Skip rotate for doctor probes and queued follow-ups while busy.
        w = self._emit_heavy_if_needed()
        is_probe = text.strip().startswith("[doctor-probe]")
        if (w.get("level") == "hard") and (not is_probe) and (not self._is_busy()):
            return self._rotate_to_fresh_session(text, reason="heavy", client_mid=client_mid, client_context=client_context, event_type=event_type)

        # Inactivity auto-rotate: if session had prior conversation and was inactive > INACTIVITY_ROTATE_SEC
        user_or_asst_turns = [h for h in self.history if h.get("role") in ("user", "assistant")]
        time_since_active = _now() - getattr(self, "last_activity", _now())
        if len(user_or_asst_turns) >= 2 and (time_since_active >= INACTIVITY_ROTATE_SEC) and (not is_probe) and (not self._is_busy()):
            return self._rotate_to_fresh_session(text, reason="inactivity", client_mid=client_mid, client_context=client_context, event_type=event_type)

        with self.lock:
            if self.busy and not self._proc_alive():
                self.busy = False
            if self._is_busy():
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
                self._loop_hint = _s().STEER_HINT
                self.interrupt_current_turn(reason="steer")

        kw = {"event_type": event_type} if event_type else {}
        if client_context:
            kw["client_context"] = client_context
        self._send_direct(text, client_mid, **kw)
        return None

    def _steer_worker(self) -> None:
        popped = None
        rest = None
        try:
            with self.lock:
                if not self.msg_queue or not self.busy:
                    return  # the turn ended meanwhile: the normal end-of-turn dispatch delivers it
                popped = self.msg_queue.pop(0)
                rest = list(self.msg_queue)
                self.msg_queue.clear()
            self.interrupt_current_turn(reason="steer", clear_queue=False)
            with self.lock:
                self.msg_queue[:] = rest + list(self.msg_queue)  # later messages wait for the next boundary
                self._steer_since = _now() if self.msg_queue else 0.0
                rest = None
            self._loop_hint = _s().STEER_HINT
            text, mid = popped
            self._send_direct(text, mid)  # respawns with --conversation <real id>: memory intact
            popped = None
        except Exception:
            if popped is not None or rest is not None:
                with self.lock:
                    to_restore = ([popped] if popped else []) + (rest or [])
                    self.msg_queue[:] = to_restore + list(self.msg_queue)
            raise
        finally:
            self._steering = False

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
                    **i18n.msg("srv.steer_queued")})
        timer = threading.Timer(_s().STEER_MAX_WAIT_SEC, self._steer_at_boundary, kwargs={"forced": True})
        timer.daemon = True
        timer.start()

    def _steer_at_boundary(self, forced: bool = False) -> None:
        """Called at every finished tool step (and by a timer as the fallback). If a message is
        waiting and the turn is still running, hand it to a worker thread -- never stop the child
        from the thread that reads its stdout."""
        with self.lock:
            if self._steering or not self.msg_queue or not self.busy:
                return
            if forced and _now() - self._steer_since < _s().STEER_MAX_WAIT_SEC - 1:
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

    def _send_direct(self, text: str, client_mid: str = "", client_context: Optional[Dict[str, Any]] = None,
                     notice: bool = False, event_type: str = "") -> None:
        """`notice=True`: `text` is a host note to the agent (a loop notice), not something the user said --
        it is neither shown as their message nor kept in history, and it does not start a new user turn.
        A turn that fails to start (spawn error, dead pipe) never leaves busy stuck; the caller gets the error."""
        try:
            self._open_turn(text, client_mid, client_context, notice, event_type)
        except Exception:
            with self.lock:
                self.busy = False
            self._finish_turn("error")
            raise

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
        host = _s()
        msgs: List[dict] = []
        system_text = host._persona_system_prompt(getattr(self, "mode", "work"), getattr(self, "character", ""), self.history)
        if system_text:
            msgs.append({"role": "system", "content": system_text})
        # Bare HTTP call has no CLI runtime telling the model what it
        # actually is (agy/claude/grok/codex get this for free from their
        # own process context) -- without it, "what model are you" on an
        # omniroute session got answered by guessing/pattern-matching the
        # AGENTS.md harness list, which reads DEFAULT_PROVIDER=agy most
        # prominently and answered "Antigravity(agy)" even while this
        # session's actual provider/model was omniroute/auto-best-free
        # (live-observed 2026-09-18, session 20260918-193213-e30f27).
        msgs.append({
            "role": "system",
            "content": f"[Runtime] This session's real backend is provider={self.provider}, model={self.model}.",
        })
        last_idx = len(self.history) - 1
        for i, h in enumerate(self.history):
            role = h.get("role")
            if role not in ("user", "assistant"):
                continue
            if h.get("queued"):
                continue
            text = host._as_named_now(h.get("text") or "", h.get("ts"))   # NAME_CHANGE_v1: older talk, today's names
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
                self._handle_events([{"event": "error", "error": str(e), **i18n.msg("srv.api_failed", error=e)}])

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
        m = i18n.msg("srv.http_timeout", minutes=minutes)
        with self.lock:
            self.history.append({"role": "assistant", **m, "ts": _now()})
            self.save_meta()
        self._emit({"event": "error", **m})

    def _guard_lines(self, stdin_content: str) -> str:
        """What the guards tell the agent before its message: a tree-watch hold (TREE_WATCH_v1, director-handoff
        dir/B; called every turn, it also remembers the tree) and why the previous turn was stopped."""
        hold = _s().write_guard.turn_start(self, _s().REPO_ROOT)
        if hold and not self.is_private:
            stdin_content = f"[Host note] {hold}\n\n{stdin_content}"
        if self._loop_hint:  # the previous turn was stopped automatically; tell the agent once
            stdin_content = f"[Host note] {self._loop_hint}\n\n{stdin_content}"
            self._loop_hint = ""
        return stdin_content

    def _context_prefix(self) -> str:
        """The text to put before this turn's message (lock held). Instruction bundle (instructions.py), injected above
        the adapter layer so every provider gets the same text the same way; native AGENTS.md/CLAUDE.md/skill
        auto-discovery is not relied on.
          - first turn of a conversation                     -> inject
          - static layers changed (charter/persona/skills)   -> re-inject as an update
          - resumed session that has a flag but no stored hash (pre-hash sessions) -> adopt the current hash silently
          - otherwise, dynamic layers that changed since     -> only those, as a refresh (CONTEXT_REFRESH_v1)
        The HTTP transport is stateless and already sends the bundle as the system message on every request, so a
        user-turn preamble would only duplicate it there."""
        bundle = _s().build_instruction_bundle(mode=getattr(self, "mode", "work"), character=getattr(self, "character", ""))
        btext, bhash = bundle["text"], bundle["hash"]
        if not btext:
            return ""
        if not getattr(self, "persona_injected", False):
            header = "Below are this chatbot's persona and rules. They are given on the first turn only."
        elif getattr(self, "persona_bundle_hash", "") and self.persona_bundle_hash != bhash:
            header = "The rules were updated. Below are the rules from now on; where they differ from the earlier ones, follow these."
        else:
            if not getattr(self, "persona_bundle_hash", ""):
                self.persona_bundle_hash = bhash
            return self._context_refresh(bundle)
        prefix = ""
        if self.adapter.transport_kind != "http":
            prefix = (f"[Host note] {header} Act by them, and do not mention this note.\n\n"
                      f"{btext}\n\n"
                      f"---\n\n")
        self._log_context(bundle)   # CONTEXT_LOG_v1: before the flags say it is in
        self.persona_injected = True
        self.persona_bundle_hash = bhash
        self.context_layer_hashes = _dynamic_hashes(bundle)
        return prefix

    def _context_refresh(self, bundle: Dict[str, Any]) -> str:
        """CONTEXT_REFRESH_v1 (layered-context-architecture lca/C): the bundle went in once; a memory, name or status
        layer changed since reaches the agent as a short block with only those layers (each capped), not the whole
        bundle again. A session from before this adopts the current state silently."""
        now = _dynamic_hashes(bundle)
        seen = getattr(self, "context_layer_hashes", None)
        if not isinstance(seen, dict):
            self.context_layer_hashes = now
            return ""
        changed = [lid for lid in now if seen.get(lid) != now[lid]]
        gone = [lid for lid in seen if lid not in now]
        if not changed and not gone:
            return ""
        self.context_layer_hashes = now
        if self.adapter.transport_kind == "http":   # it gets the whole bundle on every request
            return ""
        import instructions
        texts = {layer.id: t for layer, t in instructions.layer_texts(getattr(self, "mode", "work"),
                                                                      getattr(self, "character", "") or "")}
        parts = [texts.get(lid, "")[:REFRESH_MAX_CHARS] for lid in changed]
        parts += ["(%s: now empty)" % lid for lid in gone]
        block = ("[Host note] Memory or status changed since you were last told. Use what follows instead of the same "
                 "parts before, and do not mention this note.\n\n" + "\n\n".join(p for p in parts if p) + "\n\n---\n\n")
        self._log_context(dict(bundle, text=block, layers=[x for x in bundle.get("layers") or [] if x["id"] in changed]),
                          "refresh")   # chars = what this turn carries
        return block

    def _context_lore(self, text: str) -> str:
        """LORE_TURN_v1 (lca/D): lorebook entries the recent talk and this message match, as a block -- only when the
        matched set changed since the last one (the same match twice adds nothing). Not for a stateless transport: its
        bundle is built with the talk and already holds them."""
        if self.adapter.transport_kind == "http":
            return ""
        import instructions
        recent = list(getattr(self, "history", []) or [])[-(instructions.LOREBOOK_SCAN_DEPTH - 1):] + [{"text": text}]
        lore = instructions.lore_matches(getattr(self, "character", "") or "", recent)
        h = hashlib.sha256(lore.encode("utf-8")).hexdigest()[:8] if lore else ""
        if h == getattr(self, "context_lore_hash", ""):
            return ""
        self.context_lore_hash = h
        if not lore:
            return ""
        block = ("[Host note] Setting lore the talk just touched on. Use it, and do not mention this note.\n\n" + lore
                 + "\n\n---\n\n")
        self._log_context({"text": block, "hash": "", "mode": getattr(self, "mode", "work"),
                           "layers": [{"id": "lore_match", "kind": "turn", "chars": len(lore), "hash": h}]}, "lore")
        return block

    def _log_context(self, bundle: Dict[str, Any], why: str = "") -> None:
        """CONTEXT_LOG_v1 (layered-context-architecture lca/B): one `context.inject` line each time a bundle goes in --
        which layers, how long, why (first turn, or its static layers changed). `logdigest.py --evt context.inject`."""
        try:
            why = why or ("rules_changed" if getattr(self, "persona_injected", False) else "first")
            rec = {"ts": round(_now(), 1), "why": why, "chars": len(bundle.get("text") or ""),
                   "layers": [{"id": x.get("id"), "chars": x.get("chars")} for x in bundle.get("layers") or []]}
            self.context_log = (list(getattr(self, "context_log", []) or []) + [rec])[-_s().CONTEXT_LOG_KEEP:]
            obslog.event("context.inject", sid=self.sid, provider=self.provider, mode=getattr(self, "mode", "work"),
                         character=getattr(self, "character", "") or "", why=why, hash=bundle.get("hash", ""),
                         chars=len(bundle.get("text") or ""), layers=bundle.get("layers") or [])
            import instructions
            whole = why in ("first", "rules_changed")
            alerts = instructions.context_alerts(bundle, getattr(self, "character", "") or "") if whole else []
            for a in alerts:   # CONTEXT_ALERT_v1: a whole bundle only -- a refresh or lore block holds a few layers
                obslog.event("context.alert", lvl="error" if a["kind"] == "leak" else "warn", sid=self.sid,
                             mode=getattr(self, "mode", "work"), character=getattr(self, "character", "") or "", **a)
        except Exception:  # noqa: BLE001 -- a record never stops a turn
            pass

    def _ensure_timed(self, t_enter: float) -> Optional[float]:
        """ensure() the agent; the ms it took when this turn had to start one (telemetry tl/D spawn_ms), else None."""
        before = self.proc
        self.ensure()
        return round((time.time() - t_enter) * 1000, 1) if self.proc is not before else None

    def _phases_begin(self, t_enter: float, spawn_ms: Optional[float]) -> None:
        """The turn's phases so far: preparation (bundle, spawn) until the agent is told; the first tool call later."""
        self._turn_phases = {"prep_ms": round((self._turn_t0 - t_enter) * 1000, 1), "spawn_ms": spawn_ms,
                             "first_tool_ms": None}

    def _write_turn(self, payload: str) -> bool:
        """Hand the turn to the running agent. False: a stop() came while the turn was being prepared -- it clears
        proc first, so the stop wins and the turn ends here instead of writing to no process (#843: the repair
        probe stopped a turn whose standby agent took 8 s to start; AttributeError on proc.stdin)."""
        with self.lock:
            proc = self.proc
            if proc is None or proc.stdin is None:
                obslog.event("turn.dropped", sid=self.sid, provider=self.provider, reason="stopped_before_send")
                return False
            self.busy = True
            try:
                proc.stdin.write(payload)
                proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                if self.proc is proc and not getattr(self, "_stop_requested", False):
                    raise
                self.busy = False   # stopped between the check and the write: the same race, a step later
                obslog.event("turn.dropped", sid=self.sid, provider=self.provider, reason="stopped_while_sending")
                return False
        return True

    def _open_turn(self, text: str, client_mid: str, client_context: Optional[Dict[str, Any]], notice: bool, event_type: str) -> None:
        """Start the turn, and beside it the work-room affection judgment (engine-decides D1).
        A private session and a host notice are not judged. The judgment starts first and is
        attached to the user message's ts once that exists."""
        import personal_turn
        job = None
        if not notice and not getattr(self, "is_private", False):
            try:
                job = personal_turn.start_judgment(self.meta_path.parent.parent, self.sid, text, event_type or "")
            except Exception:
                job = None
        before = len(getattr(self, "history", None) or [])
        try:
            self._start_turn(text, client_mid, client_context, notice, event_type)
        finally:
            hist = getattr(self, "history", None) or []
            if job is not None and len(hist) > before and hist[-1].get("role") == "user":
                personal_turn.bind_judgment(job, hist[-1].get("ts"))

    def _start_turn(self, text: str, client_mid: str, client_context: Optional[Dict[str, Any]], notice: bool, event_type: str) -> None:
        # Multi-Provider plan Phase 2: a one-shot exec provider (grok, codex-style) needs its prompt known BEFORE
        # spawning (argv/a prompt file), so stdin_content is finalized first; the provider shapes fork at the bottom.
        t_enter, spawn_ms = time.time(), None   # telemetry tl/D phases: what happens before the agent hears the turn
        if self.adapter.keeps_stdin_open:
            spawn_ms = self._ensure_timed(t_enter)
            assert self.proc and self.proc.stdin

        stdin_content = f"[Host note] {text}" if notice else text
        self._turn_offer, self._incident_offer = getattr(self, "_incident_offer", None) or [], []   # il/E: this turn's buttons only (#867)
        self._cached_summary, rules_prefix = "", ""  # a new turn stales the handover cache (#613); bundle goes AFTER the handoff wrap
        with self.lock:
            rules_prefix = self._context_prefix() + self._context_lore(text)   # bundle or what changed; matched lore
        with self.lock:
            if not notice and not getattr(self, "handoff_injected", False) and getattr(self, "handoff_summary", ""):
                pred = getattr(self, "predecessor_session_id", "") or ""
                # A real cross-session rotation (/continue, heavy-session
                # auto-rotate) always sets predecessor_session_id alongside
                # handoff_summary (see REG.create() below); an in-place
                # provider swap (maybe_swap_provider()) sets handoff_summary
                # on the SAME session, with no predecessor id to show, so the
                # label reads as "the last talk" instead of a session id nobody
                # asked to see.
                label = f"the previous session ({pred[:8]})" if pred else "the last talk"   # the agent's words: English
                shown = i18n.line("srv.label_prev_session", sid=pred[:8]) if pred else i18n.line("srv.label_last_talk")
                # Explicit framing, not just labeled sections -- without a
                # direct instruction, the model (esp. the fast/small models
                # this rotates onto) sometimes treated the handoff summary
                # itself as the thing to respond to/discuss, rather than
                # background for the actual instruction below it, so a task
                # given right as a session rotated came back ignored with an
                # off-topic reply about the summary instead (operator: "I gave it
                # work, the session switched, and it forgot the work and talks
                # about something else"). agy's own /compact summary style (the
                # preferred summary source) isn't written with a "here's the
                # pending task" framing the way our custom fallback prompt
                # is, so this needs to hold regardless of which produced it.
                stdin_content = (
                    f"[Host note] This carries on from {label}, whose context was handed over. "
                    f"The 'handed-over context' below is background only -- do not sum it up or comment on it. "
                    f"What to answer or do now is only {user_title()}'s current message below it.\n\n"
                    f"[Handed-over context from {label} -- background only]\n"
                    f"{self.handoff_summary}\n"
                    f"--------------------------------------------------\n"
                    f"[{user_title()}'s current message -- what to answer or do now]\n"
                    f"{text}"
                )
                self.handoff_injected = self._handed_over = True   # _handed_over: the turn hook recaps dialogs (inbox/C)
                self._emit({
                    "event": "system",
                    **i18n.msg("srv.handed_over", label=shown),
                })

        if client_context:
            ctx_line = _s().format_client_context(client_context)
            if ctx_line:
                stdin_content = f"{ctx_line}\n\n{stdin_content}"
        stdin_content = "\n\n".join(filter(None, ["" if notice else _s().boot_notice(self), stdin_content]))

        if not notice and self.is_private:  # PRIVATE_TENSION_v1: move the stage, then tell the agent where it stands
            step_turn(self, text, event_type)   # #864: the stage moves and why, for the private.turn log
            stdin_content = f"{self.adapter.turn_context(self)}\n\n{stdin_content}"

        stdin_content = self._guard_lines(stdin_content)

        # Order on the wire: rules -> handoff context -> the current message.
        # (The handoff block above rebuilds stdin_content from `text`, so the
        # rules must be prepended after it, not before -- doing it before
        # silently dropped the bundle on every rotation / provider-swap turn.)
        if rules_prefix:
            stdin_content = rules_prefix + stdin_content

        self._loop_guard.reset()
        self._loop_warned = False
        if notice and event_type not in ("handoff", "regen"):   # a handover or another take is a whole turn (HANDOFF_v1)
            self._loop_guard.tighten(_s().LOOP_STOP_AFTER_NOTICE)  # the resumed turn stops sooner if it keeps repeating
        else:
            self._loop_guard.relax()
            self._loop_noticed = False
        with self.lock:
            self.current_text = ""
            self.turn_started_at = _now(); self._obs_turn_logged = None; self._cancel_error_message_failfast(); self._err_msg_failfast_done = False; self._err_msg_hint = ""; self._post_result_stop = None; self._cancel_silent_hang(); self._silent_hang_done = False; self._last_turn_activity_at = 0.0; self._turn_t0 = time.time(); self.ttft_ms = None; self._phases_begin(t_enter, spawn_ms)
            self.pending_images = []
            ts = _now()
            if not notice:
                self.history.append({"role": "user", "text": text, "ts": ts})
            self.last_activity = _now()
            self.save_meta()
        obslog.event("turn.start", sid=self.sid, provider=self.provider, model=self.model,
                     notice=bool(notice), chars=len(text or ""), resume=bool(self.conversation_id),
                     queued=len(getattr(self, "msg_queue", []) or []))

        # Other devices must see the question before any delta. HTTP/one-shot
        # turns used to start their worker thread first; the tablet then
        # drew the answer and only later appended the question underneath.
        if not notice:
            self._emit({"event": "user_ack", "text": text, "ts": ts, "client_mid": client_mid})

        if self.adapter.keeps_stdin_open:
            if not self._write_turn(self.adapter.format_stdin(stdin_content)):
                return
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
            # _spawn() resets this per turn; http never calls it, so without this
            # a single past stop() would latch _stop_requested=True and
            # _run_http_turn would silently drop every later turn's events.
            self._stop_requested = False
            threading.Thread(target=self._run_http_turn, args=(stdin_content,), daemon=True).start()
            threading.Thread(target=self._http_turn_watchdog, args=(turn_seq,), daemon=True).start()
        else:
            # One-shot exec: the prompt goes into the spawn itself (grok's
            # --prompt-file), not a stdin write on an already-running
            # process -- _spawn() kills whatever this session's previous
            # (already-exited, since one-shot turns finish and exit on their
            # own) process was and starts the next one. busy=True only after
            # _spawn(): its internal stop() resets busy (live 2026-09-17).
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

        # SILENT_HANG_v1: idle clock starts once the turn is live (any transport).
        # Resets on assistant text OR tool/progress activity; fires only on true silence.
        if self.busy:
            t0 = float(self.turn_started_at or _now())
            self._last_turn_activity_at = t0
            self._arm_silent_hang()

    def continue_to_successor(self, model: str, sticky: bool) -> dict:
        """Hand this session off to a successor, for the /continue route.

        sticky=True (used by the client's auto-redirect-on-open for a "hard"
        session) reuses an already-usable successor_session_id instead of
        always forking a fresh one. Without this, every browser tab/window
        that happened to load the same hard session before any of them
        finished handing off would each mint its own orphan successor, so N
        open windows meant N disconnected new chats and the old context
        never settled on one continuation (operator report: with several windows open
        each started its own new session and the old talk did not show). The manual "continue"
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
                new_sess = _s().REG.get(succ_id)
                summary = getattr(self, "handoff_summary", "") or ""
                reused = True
            else:
                summary = self.get_handover_summary()
                new_sess = _s().REG.create(
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
                    character=self.character,
                    mode=self.mode,
                )
                self.successor_session_id = new_sess.sid
                try:
                    self.save_meta()
                except Exception:
                    pass
        return {"new_sess": new_sess, "summary": summary, "reused": reused}

    def interrupt_current_turn(self, reason: str = "interrupted", clear_queue: bool = True) -> None:
        """Interrupt an in-flight turn (process or HTTP stream) safely, preserving partial text in history."""
        self._stop_requested = True
        proc = self.proc
        http_resp = self._http_resp
        with self.lock:
            if clear_queue and hasattr(self, "msg_queue"):
                self.msg_queue.clear()
            self.busy = False
            # If there was partial assistant text generated so far, preserve it in history
            cur = (self.current_text or "").strip()
            if cur:  # a 0-char turn (steer included) leaves nothing; the new instruction just follows
                # the model's words as they came; the host's mark beside them by key, added in the page's language
                mark = i18n.line({"steer": "srv.mark_steer", "loop": "srv.mark_loop"}.get(reason, "srv.mark_interrupted"), user=user_title())
                self.history.append({"role": "assistant", "text": self._rewrite_artifact_paths(cur), "mark": mark,
                                     "ts": _now(), "interrupted": True})
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
                    **i18n.msg({"steer": "srv.interrupted_steer", "loop": "srv.interrupted_loop"}.get(reason, "srv.interrupted"), user=user_title())})
        self._finish_turn("steer" if reason in ("steer", "loop") else "interrupted")
        _s()._record_live_pids()

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

    def _stop_for_swap(self, what: str) -> None:
        """Stop the live process because the provider/model is being swapped.

        A swap is not a user-requested stop, so it must not print "work
        stopped" -- that notice appeared, twice per switch (provider, then
        model), every time someone clicked through the provider tray just to
        look at another provider's usage, even with nothing running. Only say
        something when a turn really was in flight, and say what happened;
        emitting "stopped" then is also what resets the UI's busy state."""
        was_busy = self.busy
        self.stop(notify=False)
        if was_busy:
            self._emit({"event": "stopped", **i18n.msg(what)})

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
            self._stop_for_swap("srv.swap_stopped_model")
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
        (operator: "a switch midway probably leaves something to redo" -- confirmed
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
            self.adapter = _s().get_adapter(provider)
            self.conversation_id = None
            self.model = self.effort = ""   # both belong to the old brain (grok effort=low broke agy -high, 09-30)
            self.handoff_summary = summary
            self.handoff_injected = False
            # New provider = new conversation that has never seen the persona
            # rules; without this reset it would run persona-less (2026-09-19).
            self.persona_injected = False
            self.persona_bundle_hash = ""
            self._stop_for_swap("srv.swap_stopped_provider")
            self.save_meta()
            if remember:
                self._remember_brain_choice()
            if self.history:
                threading.Thread(target=self._refine_swap_handoff, args=(gen, old_provider, old_cid), daemon=True).start()

    def _finish_turn(self, outcome: str = "result") -> None:
        """Every way a turn can end (result/error event, stop, steer, interrupt, child died, auto-stop) calls this
        once: the turn's log line, the write guard, the low-quota note, regenerate's bookkeeping. Never raises."""
        self._cached_summary = ""  # handover cache stale after new content
        self._obs_turn_end(outcome)
        write_guard = _s().write_guard
        REPO_ROOT = _s().REPO_ROOT
        quota_state = _s().quota_state
        regenerate = _s().regenerate
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

    def weight(self) -> dict:
        soft_tokens, hard_tokens = self.adapter.soft_hard_tokens(self.model)
        return _s()._session_weight(self.history, self.conversation_id, soft_tokens, hard_tokens)

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
            meta_path = _s().SESSIONS / sid / "meta.json"
            if not meta_path.exists():
                return False
            succ = _s().REG.get(sid)
            w = succ.weight() if hasattr(succ, "weight") else {}
            if (w.get("level") or "ok") == "hard":
                return False
            return True
        except Exception:
            return False
