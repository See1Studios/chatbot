"""Running a turn (monolith-split split/C, moved from session.py as a mixin of AgentSession, like turn_watchdog.py
and session_view.py): send (queue, steer, rotate when idle or heavy), the turn itself, /btw side questions, interrupt,
and handing over to a successor session. Every name session.py defines or tests and server.py swap (REG, boot_notice,
build_instruction_bundle, _oneshot, ...) is read as `_s().name` on each call, never copied at import."""
from __future__ import annotations

import threading
from typing import Dict, Optional

import obslog
from host_config import INACTIVITY_ROTATE_SEC, _now
from identity import user_title
from private_engine import tension_step
from session_weights import _btw_prompt, _is_inquiry


def _s():
    import session
    return session


class SessionTurn:
    def _run_btw(self, query: str) -> None:
        query = (query or "").strip()
        if not query:
            self._emit({"event": "btw", "query": "", "text": f"{user_title()}, `/btw <질문 내용>` 형태로 궁금한 점을 적어주세요!"})
            return
        self._emit({"event": "btw_start", "query": query})
        context_snippets = []
        with self.lock:
            is_active = bool(self.busy and self._proc_alive())
            silent = is_active and bool(getattr(self, "is_silent", False))
            cur_tool = getattr(self, "_last_tool_sig", "") or ""
            recent_hist = [f"{h.get('role')}: {str(h.get('text') or '')[:120]}" for h in self.history[-4:] if h.get("role") in ("user", "assistant")]
        if is_active:
            context_snippets.append(f"[현재 백그라운드 진행 중인 메인 작업: {cur_tool}]" if cur_tool else "[현재 백그라운드에서 메인 작업 추론/수행 중]")
            if silent:
                context_snippets.append(f"[현재 메인 작업이 {int(self.SILENT_NOTICE_SEC)}초 이상 무응답(침묵) 상태입니다. 지연 또는 정체 중일 수 있습니다.]")
        else:
            context_snippets.append("[현재 백그라운드에서 실행 중인 메인 작업이 없습니다. 이전 작업은 완료되었거나 대기/중단 상태입니다.]")
        if recent_hist:
            context_snippets.append("[최근 대화 맥락:\n" + "\n".join(recent_hist) + "]")

        prompt = _btw_prompt(query, is_active, context_snippets, silent)
        ans = "답변을 가져오지 못했습니다."
        usage = None
        duration_seconds = None
        r = _s()._oneshot(prompt, 20)
        if r is None:
            ans = "간이 질문에 답할 제공자가 설정되지 않았습니다 (CHATBOT_ONESHOT_PROVIDER)."
        elif r.get("text"):
            ans, usage, duration_seconds = r["text"], r.get("usage"), r.get("duration_seconds")
        elif r.get("error") == "timeout":
            ans = "간이 질문 응답 시간이 초과되었습니다."
        elif r.get("error"):
            ans = _s()._redact_text(r["error"]) or ans

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

    def _rotate_to_fresh_session(self, text: str, reason: str = "heavy", client_mid: str = "", client_context: Optional[Dict[str, Any]] = None) -> "AgentSession":
        """Sticky rotate: reuse successor_session_id when usable; else create once and remember with handover."""
        if reason == "inactivity":
            msg = (
                "이전 대화 이후 시간이 경과하여 이전 맥락을 인계받아 새 세션으로 이어갑니다 ✦ (이전 대화는 보존됩니다)"
            )
        else:
            msg = (
                "세션이 길어져서 이전 맥락을 인계받아 새 채팅으로 전환합니다. 이전 세션 데이터는 그대로 보존됩니다 ✦"
            )
        succ_id = getattr(self, "successor_session_id", "") or ""
        if succ_id and self._successor_usable(succ_id):
            new_sess = _s().REG.get(succ_id)
        else:
            summary = self.get_handover_summary()
            new_sess = _s().REG.create(
                model=self.model,
                effort=self.effort,
                predecessor_sid=self.sid,
                handoff_summary=summary,
                # same fix as continue_to_successor(): without it the successor starts as agy
                # with this provider's model name (e.g. claude "sonnet") and the turn dies with
                # "invalid model selection" (2026-09-21, also seen with grok-4.6)
                provider=self.provider,
                character=self.character,
                mode=self.mode,
            )
            self.successor_session_id = new_sess.sid
            try:
                self.save_meta()
            except Exception:
                pass
            if _s().evolution is not None:
                _s().evolution.record_candidate(self._observation_root(), "rotation", self.sid, self.provider, {"outcome": reason})
        # client_mid lets the sending tab's own SSE handler recognize this
        # rotation as one it already knows about (the /message HTTP response
        # itself carries the same info) and skip re-rendering -- without
        # this, both the SSE event (emitted here, before the slow successor
        # spawn/send below) and the POST response (arriving after) independently
        # re-entered the new session, and the SSE one (missing the user's
        # own just-typed text) usually rendered first, making the message
        # look like it vanished (operator: "내가 말을 하면 바로 새 세션으로
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

        # Soft warn anytime; hard rotate before appending more to bloated conversation.
        # Skip rotate for doctor probes and queued follow-ups while busy.
        w = self._emit_heavy_if_needed()
        is_probe = text.strip().startswith("[doctor-probe]")
        if (w.get("level") == "hard") and (not is_probe) and (not self._is_busy()):
            return self._rotate_to_fresh_session(text, reason="heavy", client_mid=client_mid, client_context=client_context)

        # Inactivity auto-rotate: if session had prior conversation and was inactive > INACTIVITY_ROTATE_SEC
        user_or_asst_turns = [h for h in self.history if h.get("role") in ("user", "assistant")]
        time_since_active = _now() - getattr(self, "last_activity", _now())
        if len(user_or_asst_turns) >= 2 and (time_since_active >= INACTIVITY_ROTATE_SEC) and (not is_probe) and (not self._is_busy()):
            return self._rotate_to_fresh_session(text, reason="inactivity", client_mid=client_mid, client_context=client_context)

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

    def _guard_lines(self, stdin_content: str) -> str:
        """What the guards tell the agent before its message: a tree-watch hold (TREE_WATCH_v1, director-handoff
        dir/B; called every turn, it also remembers the tree) and why the previous turn was stopped."""
        hold = _s().write_guard.turn_start(self, _s().ROOT)
        if hold and not self.is_private:
            stdin_content = f"[시스템 안내] {hold}\n\n{stdin_content}"  # l10n-ok
        if self._loop_hint:  # the previous turn was stopped automatically; tell the agent once
            stdin_content = f"[시스템 안내] {self._loop_hint}\n\n{stdin_content}"
            self._loop_hint = ""
        return stdin_content

    def _start_turn(self, text: str, client_mid: str, client_context: Optional[Dict[str, Any]], notice: bool, event_type: str) -> None:
        # Multi-Provider plan Phase 2: a one-shot exec provider (grok, and any
        # future codex-style adapter) needs its prompt known BEFORE spawning
        # (baked into argv/a prompt file), so ensure()-then-write-to-stdin
        # doesn't apply -- stdin_content must be finalized first either way,
        # then the two provider shapes fork at the bottom of this method.
        if self.adapter.keeps_stdin_open:
            self.ensure()
            assert self.proc and self.proc.stdin

        stdin_content = f"[시스템 안내] {text}" if notice else text
        self._cached_summary, rules_prefix = "", ""  # a new turn stales the handover cache (#613); bundle goes AFTER the handoff wrap
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
            bundle = _s().build_instruction_bundle(mode=getattr(self, "mode", "work"), character=getattr(self, "character", ""))
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
                # off-topic reply about the summary instead (operator: "일을
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
                self.handoff_injected = self._handed_over = True   # _handed_over: the turn hook recaps dialogs (inbox/C)
                self._emit({
                    "event": "system",
                    "text": f"{label} 맥락을 인계받아 대화를 시작했습니다 ✦",
                })

        if client_context:
            ctx_line = _s().format_client_context(client_context)
            if ctx_line:
                stdin_content = f"{ctx_line}\n\n{stdin_content}"
        stdin_content = "\n\n".join(filter(None, ["" if notice else _s().boot_notice(self), stdin_content]))

        if not notice and self.is_private:  # PRIVATE_TENSION_v1: move the stage, then tell the agent where it stands
            self.tension_stage, self.recent_choices = tension_step(self.tension_stage, self.recent_choices, self.history, text, event_type)
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
        if notice and event_type != "handoff":   # handed-over work is a whole turn of work (HANDOFF_v1)
            self._loop_guard.tighten(_s().LOOP_STOP_AFTER_NOTICE)  # the resumed turn stops sooner if it keeps repeating
        else:
            self._loop_guard.relax()
            self._loop_noticed = False
        with self.lock:
            self.current_text = ""
            self.turn_started_at = _now(); self._obs_turn_logged = None; self._cancel_error_message_failfast(); self._err_msg_failfast_done = False; self._err_msg_hint = ""; self._post_result_stop = None; self._cancel_silent_hang(); self._silent_hang_done = False; self._last_turn_activity_at = 0.0
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
            payload = self.adapter.format_stdin(stdin_content)
            with self.lock:
                self.busy = True
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
        never settled on one continuation (operator 보고: 창을 여러 개 열면
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
                mark = (f"*(🧭 {user_title()}의 새 지시를 반영하려고 여기서 잠시 멈췄습니다)*" if reason == "steer"
                        else "*(🧭 같은 호출이 반복돼 여기서 잠시 멈추고 방향을 바꾸도록 알렸습니다)*" if reason == "loop"
                        else f"*(⚡ {user_title()}의 새 지시로 이전 작업이 중단되었습니다)*")
                annotated = (self._rewrite_artifact_paths(cur) + "\n\n" if cur else "") + mark
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
                    "text": ("새 지시를 반영하는 중이에요 — 하던 작업은 이어서 합니다 ✦" if reason == "steer"
                             else "방향을 바꾸도록 알리는 중이에요 — 하던 작업은 이어서 합니다 ✦" if reason == "loop"
                             else f"진행 중인 작업이 {user_title()}의 새 지시로 전환되었습니다 ✦")})
        self._finish_turn("steer" if reason in ("steer", "loop") else "interrupted")
        _s()._record_live_pids()
