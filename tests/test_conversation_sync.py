"""The chat window and the agent stay in sync across respawns, and a runaway turn is stopped.

2026-09-20: every stored agy conversation_id was a phantom (114 of 114 absent from agy's store),
so each respawn silently started an EMPTY conversation while the window kept the whole chat; and a
Gemini turn looped on view_file for ~23 minutes with nothing shown.
Run: python3 -m unittest tests.test_conversation_sync  (from services/chatbot)
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session as S  # noqa: E402
from providers.adapters import AgyAdapter, AGY_PRINT_TIMEOUT_SEC  # noqa: E402
from tests.test_instructions import WorkspaceCase  # noqa: E402
import session_weights as SW  # noqa: E402

REAL, PHANTOM = "fd45a3f5-52e4-4d03-80a1-1d62d7d12f38", "16d6f861-2036-40e6-84bf-6df758de4b1e"


class Base(WorkspaceCase):
    def make(self, history=None):
        self._sessions, self._home, self._sw_home = S.SESSIONS, S.HOME, SW.HOME
        S.SESSIONS = self.tmp / "sessions"
        (S.SESSIONS / "t").mkdir(parents=True, exist_ok=True)
        S.HOME = self.tmp / "home"                                   # agy's store lives under HOME
        SW.HOME = S.HOME                                             # _conversation_db_path uses session_weights.HOME
        (S.HOME / ".gemini" / "antigravity-cli" / "conversations").mkdir(parents=True, exist_ok=True)
        s = S.AgentSession("t", provider="agy")
        from providers import adapters
        s.adapter = types.SimpleNamespace(id="agy", keeps_stdin_open=False, transport_kind="process",
                                          format_stdin=lambda c: c, mints_own_conversation_id=lambda: False,
                                          # a store-backed CLI (agy's real check), not "because the id is agy"
                                          has_conversation=adapters.AgyAdapter().has_conversation)
        s.history = list(history or [])
        self.events, self.sent, self.stops = [], [], []
        s._emit = self.events.append
        s.save_meta = lambda: None
        s.stop = lambda notify=True: self.stops.append(notify)
        s._spawn = lambda prompt="": self.sent.append(prompt)
        # Images the turn produced are looked up in the real agy store on this host; a picture the live chat made
        # at 19:47 on 2026-09-28 became these tests' "answer" and hid the errors they check. Nothing leaks in now.
        s._collect_new_images = lambda since_ts=None: []
        s._append_images_markdown = lambda text, since_ts=None: text
        return s

    def tearDown(self):
        if hasattr(self, "_sessions"):
            S.SESSIONS, S.HOME = self._sessions, self._home
        if hasattr(self, "_sw_home"):
            SW.HOME = self._sw_home

    def store(self, cid):                                            # make agy "have" this conversation
        (S.HOME / ".gemini" / "antigravity-cli" / "conversations" / f"{cid}.db").write_bytes(b"x")

    def feed(self, s, obj):
        return AgyAdapter().normalize_line(s, json.dumps(obj))


HISTORY = [{"role": "user", "text": "샛길 응답 개선하냐"}, {"role": "assistant", "text": "네, 손볼게요"},
           {"role": "user", "text": "중복 출력 수정부터"}, {"role": "assistant", "text": "원인은 클라이언트 전송 시점입니다"}]


class AdoptTheRealId(Base):
    def test_init_step_update_and_result_all_carry_the_id_and_replace_the_phantom(self):
        for obj in ({"event": "init", "conversation_id": REAL},
                    {"event": "step_update", "step_update": {"conversation_id": REAL, "state": "DONE", "step_type": "user_input"}},
                    {"event": "result", "result": {"conversation_id": REAL, "status": "SUCCESS", "response": "ok"}}):
            s = self.make()
            s.conversation_id = PHANTOM
            self.feed(s, obj)
            self.assertEqual(s.conversation_id, REAL, obj["event"])

    def test_the_same_id_is_not_re_announced(self):
        s = self.make()
        s.conversation_id = REAL
        self.feed(s, {"event": "init", "conversation_id": REAL})
        self.assertEqual([e for e in self.events if "conversation_id=" in str(e.get("text"))], [])

    def test_providers_that_mint_their_own_id_keep_the_old_capture_rule(self):
        s = self.make()
        s.adapter = types.SimpleNamespace(mints_own_conversation_id=lambda: True)
        s.conversation_id = "keep-this-id-1234"
        s._maybe_capture_conversation_id({"conversation_id": REAL})
        self.assertEqual(s.conversation_id, "keep-this-id-1234")       # never replaced once set
        s.conversation_id = None
        s._maybe_capture_conversation_id({"session_id": "sess-abcdef12"})
        self.assertEqual(s.conversation_id, "sess-abcdef12")


class RespawnKeepsTheAgentInSync(Base):
    def test_a_real_conversation_is_resumed_and_nothing_is_reseeded(self):
        s = self.make(HISTORY)
        s.conversation_id, s.persona_injected = REAL, True
        self.store(REAL)
        s._resume_or_reseed()
        self.assertEqual((s.conversation_id, s.persona_injected), (REAL, True))
        self.assertEqual(self.events, [])

    def test_a_phantom_id_is_dropped_and_the_next_message_gets_rules_and_recent_history(self):
        s = self.make(HISTORY)
        s.conversation_id, s.persona_injected, s.handoff_injected = PHANTOM, True, True
        s._resume_or_reseed()                                          # agy has no such conversation
        self.assertIsNone(s.conversation_id)
        self.assertFalse(s.persona_injected)
        self.assertFalse(s.handoff_injected)
        self.assertIn("중복 출력 수정부터", s.handoff_summary)
        self.assertIn("클라이언트 전송 시점", s.handoff_summary)
        # ...and that really reaches the wire on the next message
        s._send_direct("그래")
        wire = self.sent[0]
        self.assertIn("CHARTER-MARK", wire)                            # rules re-injected
        self.assertIn("클라이언트 전송 시점", wire)                     # visible history re-injected
        self.assertTrue(wire.rstrip().endswith("그래"))

    def test_a_brand_new_session_is_not_reseeded(self):
        s = self.make([])
        s.conversation_id, s.persona_injected = PHANTOM, False
        s._resume_or_reseed()
        self.assertIsNone(s.conversation_id)
        self.assertEqual(s.handoff_summary, "")

    def test_a_pending_continue_handoff_is_kept_not_overwritten(self):
        s = self.make(HISTORY)
        s.conversation_id, s.handoff_summary, s.handoff_injected = PHANTOM, "PENDING-HANDOFF", False
        s._resume_or_reseed()
        self.assertEqual(s.handoff_summary, "PENDING-HANDOFF")

    def test_a_provider_that_cannot_tell_keeps_its_id(self):
        s = self.make(HISTORY)
        s.adapter = types.SimpleNamespace(id="claude", mints_own_conversation_id=lambda: True)
        s.conversation_id = "claude-own-session-id"
        s._resume_or_reseed()
        self.assertEqual(s.conversation_id, "claude-own-session-id")

    def test_the_digest_is_bounded_and_skips_side_questions(self):
        rows = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"turn {i} " + "x" * 2000} for i in range(30)]
        rows.insert(5, {"role": "btw", "text": "SIDE-QUESTION"})
        d = self.make(rows)._host_history_digest()
        self.assertNotIn("SIDE-QUESTION", d)
        self.assertLessEqual(d.count("turn "), 8)
        self.assertLess(len(d), 5200)


class UnfinishedTurns(Base):
    """TURN_END_ORDER_v1: the adapter returns the turn's terminal events (it no longer emits them itself) and only
    asks the session to stop the child; the session stops it after those events are flushed."""
    def result(self, s, **kw):
        res = {"conversation_id": REAL, "status": "SUCCESS", "response": "", "duration_seconds": 5, **kw}
        out = self.feed(s, {"event": "result", "result": res}) or []
        self.events.extend(out)
        return out

    def test_the_print_timeout_empty_result_is_surfaced_and_the_child_is_stopped(self):
        s = self.make()
        s._auto_stop_worker = lambda: self.stops.append("worker")
        self.result(s, duration_seconds=AGY_PRINT_TIMEOUT_SEC + 1)      # what 00:48:30 looked like
        errors = [e for e in self.events if e.get("event") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("답을 내기 전에", errors[0]["text"])
        self.assertEqual(self.stops, [], "not before the events are flushed")
        s._run_post_result_stop()                                      # what the session does after the flush
        import time; time.sleep(0.2)
        self.assertTrue(self.stops, "the still-running child must be stopped")
        self.assertIn("답을 내기 전에", s._loop_hint)

    def test_a_normal_short_empty_success_is_left_alone(self):
        s = self.make()
        self.result(s, duration_seconds=3)
        self.assertEqual([e for e in self.events if e.get("event") == "error"], [])
        self.assertEqual(self.stops, [])

    def test_an_error_status_is_surfaced(self):
        s = self.make()
        self.result(s, status="ERROR", error="quota exhausted", duration_seconds=2)
        self.assertTrue(any("quota exhausted" in str(e.get("text")) for e in self.events))

    def test_a_result_after_the_user_pressed_stop_is_not_treated_as_a_failure(self):
        s = self.make()
        s._stop_requested = True
        self.result(s, status="ERROR", error="interrupted", duration_seconds=2)
        self.assertEqual([e for e in self.events if e.get("event") == "error"], [])


class RunawayLoopIsStopped(Base):
    def tool_done(self, i, path="/src/app.js", start=10, end=25):
        return {"event": "step_update", "step_update": {"step_index": i, "state": "DONE", "step_type": "tool",
                "tool_name": "view_file", "tool_info": {"name": "view_file", "parameters": {
                    "AbsolutePath": path, "StartLine": start, "EndLine": end, "toolSummary": f"try {i}"},
                    "output": f"lines {start}-{end}"}}}

    def test_identical_calls_warn_then_stop_and_the_next_message_carries_a_hint(self):
        import time
        s = self.make()
        for i in range(8):
            self.feed(s, self.tool_done(i))
        time.sleep(0.2)
        warns = [e for e in self.events if e.get("event") == "system" and "⚠" in str(e.get("text"))]
        stopped = [e for e in self.events if e.get("event") == "stopped"]
        self.assertEqual(len(warns), 1)
        self.assertEqual(len(stopped), 1)
        self.assertIn("자동으로 중단", stopped[0]["text"])
        self.assertTrue(self.stops)
        s._loop_guard.reset(); s._stop_requested = False
        s._send_direct("계속해")
        wire = self.sent[-1]
        self.assertIn("같은 작업을 반복하다", wire)
        self.assertTrue(wire.rstrip().endswith("계속해"))
        s._send_direct("또")
        self.assertNotIn("같은 작업을 반복하다", self.sent[-1])        # said once

    def test_loop_events_carry_the_call_and_output_evidence(self):
        import time
        s = self.make()
        for i in range(8):
            self.feed(s, self.tool_done(i))
        time.sleep(0.2)
        stopped = [e for e in self.events if e.get("event") == "stopped"][0]
        ev = stopped["evidence"]
        self.assertEqual(ev["tool"], "view_file")
        self.assertIn("StartLine", ev["params"])
        self.assertNotIn("toolSummary", ev["params"])       # model prose stays out
        self.assertGreater(ev["output_chars"], 0)
        self.assertTrue(ev["output_head"].startswith("lines "))
        warn = [e for e in self.events if e.get("event") == "system" and "⚠" in str(e.get("text"))][0]
        self.assertIn("evidence", warn)

    def test_the_guard_is_quiet_for_ordinary_varied_work(self):
        s = self.make()
        for i in range(60):
            self.feed(s, self.tool_done(i, path=f"/src/file{i}.py"))
        self.assertEqual([e for e in self.events if e.get("event") in ("stopped", "error")], [])
        self.assertEqual(self.stops, [])

    def test_nothing_is_counted_after_the_user_stopped_the_turn(self):
        s = self.make()
        s._stop_requested = True
        for i in range(20):
            self.feed(s, self.tool_done(i))
        self.assertEqual(self.events, [])




class SilentHangWatchdog(Base):
    """SILENT_HANG_v1: busy + no text + no tool/progress + no error_message closes before print-timeout."""

    def setUp(self):
        # WorkspaceCase may define setUp; keep short timers for unit tests.
        if hasattr(super(), "setUp"):
            super().setUp()

    def _busy(self, s, hang_sec=0.25):
        s.SILENT_HANG_SEC = hang_sec
        s.ERROR_MESSAGE_FAILFAST_SEC = 30  # keep quota path from racing these tests
        s.busy = True
        s.turn_started_at = __import__("time").time()
        s._silent_hang_done = False
        s._err_msg_failfast_done = False
        s._err_msg_failfast_timer = None
        s._last_assistant_delta_at = s.turn_started_at
        s._last_turn_activity_at = s.turn_started_at
        # finalize_turn must exist on the stub adapter
        def finalize_turn(session, text="", raw_usage=None, is_err=False, error=None):
            if is_err:
                return {"event": "error", "notice": "error", "text": error or "err"}
            return {"event": "result", "text": text or ""}
        s.adapter.finalize_turn = finalize_turn
        s._finish_turn = lambda outcome="result": None
        s._auto_stop_worker = lambda: self.stops.append("worker")
        return s

    def test_silent_idle_finalizes_with_hang_notice_and_stops_child(self):
        import time
        s = self._busy(self.make())
        s._arm_silent_hang()
        time.sleep(0.45)
        errs = [e for e in self.events if e.get("event") == "error"]
        self.assertTrue(errs, "hang must surface an error notice")
        self.assertTrue(any("무응답" in str(e.get("text")) or "오랫동안" in str(e.get("text")) for e in errs))
        self.assertFalse(s.busy)
        time.sleep(0.15)
        self.assertTrue(self.stops, "child must be stopped after terminal flush (TURN_END_ORDER)")

    def test_assistant_delta_rearms_and_avoids_false_hang(self):
        import time
        s = self._busy(self.make(), hang_sec=0.35)
        s._arm_silent_hang()
        time.sleep(0.2)
        # A mid-turn assistant delta must reset the idle clock (no hang yet).
        s._touch_assistant_delta()
        time.sleep(0.2)  # 0.4s from start, but only 0.2s since delta
        self.assertTrue(s.busy, "delta must reset the idle clock")
        self.assertFalse(getattr(s, "_silent_hang_done", False))
        hang = [e for e in self.events if e.get("event") == "error" and "무응답" in str(e.get("text"))]
        self.assertEqual(hang, [])
        # After another full idle window with no further deltas, hang fires.
        time.sleep(0.25)
        self.assertTrue(getattr(s, "_silent_hang_done", False))
        self.assertTrue(any(e.get("event") == "error" for e in self.events))

    def test_a_quiet_turn_is_announced_first_and_closed_only_later(self):
        """SILENT_NOTICE_v1 (#386): agy thinks without output; the notice keeps the turn, the hang closes it later."""
        import time
        s = self._busy(self.make(), hang_sec=0.6)
        s.SILENT_NOTICE_SEC = 0.2
        s._arm_silent_hang()
        time.sleep(0.35)
        notes = [e for e in self.events if e.get("event") == "progress"]
        self.assertEqual(len(notes), 1)
        self.assertTrue(s.busy, "the notice must not close the turn")
        self.assertFalse(any(e.get("event") == "error" for e in self.events))
        time.sleep(0.45)
        self.assertTrue(getattr(s, "_silent_hang_done", False))
        self.assertTrue(any(e.get("event") == "error" for e in self.events))

    def test_activity_after_the_notice_starts_both_clocks_again(self):
        import time
        s = self._busy(self.make(), hang_sec=0.5)
        s.SILENT_NOTICE_SEC = 0.15
        s._arm_silent_hang()
        time.sleep(0.25)                          # noticed
        s._touch_turn_activity()                  # the thinking step finished: a line arrived
        time.sleep(0.35)                          # 0.6s from start, 0.35s since activity
        self.assertTrue(s.busy)
        self.assertFalse(getattr(s, "_silent_hang_done", False))
        self.assertEqual(len([e for e in self.events if e.get("event") == "progress"]), 2)
        s._cancel_silent_hang()

    def test_error_message_path_is_owned_by_quota_failfast_not_silent_hang(self):
        import time
        s = self._busy(self.make(), hang_sec=0.2)
        s._arm_silent_hang()
        # Mimic error_message: arm quota failfast, which cancels silent hang
        s._err_msg_hint = "quota exhausted"
        s._arm_error_message_failfast()
        self.assertIsNone(getattr(s, "_silent_hang_timer", None))
        time.sleep(0.35)
        hang = [e for e in self.events if e.get("event") == "error" and "무응답" in str(e.get("text"))]
        self.assertEqual(hang, [], "silent hang must not fire after error_message")
        s._cancel_error_message_failfast()

    def test_tool_call_rearms_and_avoids_false_hang(self):
        """Tool start (no assistant text) must reset the idle clock — multi-tool turns."""
        import time
        s = self._busy(self.make(), hang_sec=0.35)
        s._arm_silent_hang()
        time.sleep(0.2)
        # Real _emit path: tool call without any delta
        S.AgentSession._emit(s, {"event": "tool", "text": "bash ls", "title": "bash",
                                 "kind": "call", "status": "calling", "step_type": "run_command"})
        time.sleep(0.2)  # 0.4s from start, but only ~0.2s since tool activity
        self.assertTrue(s.busy, "tool call must reset the idle clock")
        self.assertFalse(getattr(s, "_silent_hang_done", False))
        hang = [e for e in self.events if e.get("event") == "error" and "무응답" in str(e.get("text"))]
        self.assertEqual(hang, [])
        # After a full idle window with no further activity, hang fires.
        time.sleep(0.4)
        self.assertTrue(getattr(s, "_silent_hang_done", False))

    def test_tool_progress_heartbeat_rearms_during_long_tool(self):
        """Ongoing tool progress/heartbeats keep resetting — single tool > hang window OK."""
        import time
        s = self._busy(self.make(), hang_sec=0.3)
        s._arm_silent_hang()
        # Tool start
        S.AgentSession._emit(s, {"event": "tool", "text": "bash long-job", "title": "bash",
                                 "kind": "call", "status": "calling", "step_type": "run_command"})
        # Heartbeats every ~0.2s across > hang_sec total wall time
        for i in range(4):
            time.sleep(0.2)
            S.AgentSession._emit(s, {
                "event": "tool",
                "text": f"progress {i}",
                "title": "bash",
                "kind": "call",
                "status": "running",
                "step_type": "run_command",
            })
            self.assertTrue(s.busy, f"progress heartbeat {i} must keep turn alive")
            self.assertFalse(getattr(s, "_silent_hang_done", False), f"hang must not fire at heartbeat {i}")
        hang = [e for e in self.events if e.get("event") == "error" and "무응답" in str(e.get("text"))]
        self.assertEqual(hang, [], "long tool with progress must not false-positive hang")
        # Tool result also counts as activity, then silence → hang
        S.AgentSession._emit(s, {"event": "tool", "text": "↳ done", "title": "result",
                                 "kind": "result", "status": "done"})
        time.sleep(0.2)
        self.assertFalse(getattr(s, "_silent_hang_done", False))
        time.sleep(0.35)
        self.assertTrue(getattr(s, "_silent_hang_done", False), "true silence after tool ends must hang")

    def test_error_message_tool_event_does_not_rearm_silent_hang(self):
        """error_message tool/system events must not re-arm; QUOTA_FAILFAST owns that path."""
        import time
        s = self._busy(self.make(), hang_sec=0.25)
        s._arm_silent_hang()
        # Mimic _emit seeing error_message BEFORE failfast arm (order in practice:
        # translator arms failfast, then emits). Even if emit sees it first, must not re-arm.
        S.AgentSession._emit(s, {"event": "tool", "text": "error_message", "title": "error_message",
                                 "step_type": "error_message", "kind": "call", "status": ""})
        s._err_msg_hint = "quota exhausted"
        s._arm_error_message_failfast()
        self.assertIsNone(getattr(s, "_silent_hang_timer", None))
        time.sleep(0.35)
        hang = [e for e in self.events if e.get("event") == "error" and "무응답" in str(e.get("text"))]
        self.assertEqual(hang, [], "error_message must not produce silent-hang notice")
        s._cancel_error_message_failfast()

    def test_terminal_result_cancels_silent_hang(self):
        import time
        s = self._busy(self.make(), hang_sec=0.3)
        # Use real _emit for cancel path; collect via wrapper
        real_emit = S.AgentSession._emit.__get__(s, S.AgentSession)
        def wrap(ev):
            self.events.append(ev)
            # only run cancel side of _emit for terminal kinds without subscriber noise
            kind = ev.get("event")
            if kind in ("result", "error", "stopped"):
                s._cancel_error_message_failfast()
                s._cancel_silent_hang()
                s.last_progress = ""
        s._emit = wrap
        s._arm_silent_hang()
        s._emit({"event": "result", "text": "ok"})
        time.sleep(0.45)
        hang = [e for e in self.events if "무응답" in str(e.get("text"))]
        self.assertEqual(hang, [])
        self.assertIsNone(getattr(s, "_silent_hang_timer", None))

    def test_delta_after_error_message_cancels_failfast_and_rearms_silent_hang(self):
        """When an agent recovers from transient error and emits delta, failfast must cancel."""
        import time
        s = self._busy(self.make(), hang_sec=0.4)
        s._arm_silent_hang()
        s._err_msg_hint = "transient 500 error"
        s._arm_error_message_failfast()
        self.assertIsNotNone(getattr(s, "_err_msg_failfast_timer", None))

        # Real _emit path: assistant delta arrives
        S.AgentSession._emit(s, {"event": "delta", "text": "Hello"})
        self.assertIsNone(getattr(s, "_err_msg_failfast_timer", None), "delta must cancel failfast timer")
        self.assertIsNotNone(getattr(s, "_silent_hang_timer", None), "delta must re-arm silent hang")
        time.sleep(0.2)
        self.assertTrue(s.busy, "turn must remain active")
        self.assertFalse(getattr(s, "_err_msg_failfast_done", False))

    def test_a_normalized_tool_step_resets_the_idle_clock(self):
        import time
        s = self._busy(self.make(), hang_sec=0.35)
        s._arm_silent_hang()
        time.sleep(0.2)
        for ev in AgyToolInfoEvents.step(s, "DONE", output="ok"):
            S.AgentSession._emit(s, ev)
        time.sleep(0.2)                           # 0.4s from start, ~0.2s since the tool step
        self.assertTrue(s.busy, "a tool_info step must reset the idle clock")
        self.assertFalse(getattr(s, "_silent_hang_done", False))
        s._cancel_silent_hang()

    def test_a_recent_call_in_the_provider_log_keeps_a_quiet_turn(self):
        import time
        s = self._busy(self.make(), hang_sec=0.3)
        s.proc = types.SimpleNamespace(pid=4242)
        s.adapter.last_activity = lambda pid, started: time.time()   # the CLI log saw a model call just now
        s._silent_hang_fire()
        self.assertTrue(s.busy)
        self.assertFalse(getattr(s, "_silent_hang_done", False))
        self.assertIsNotNone(getattr(s, "_silent_hang_timer", None), "re-armed for the rest of the window")
        s.adapter.last_activity = lambda pid, started: started        # no call since: the next fire closes
        time.sleep(0.45)
        self.assertTrue(getattr(s, "_silent_hang_done", False))

    def test_the_hang_closes_at_three_minutes(self):
        """#513: 5 minutes kept the page locked on a real runtime hang."""
        self.assertEqual(S.AgentSession.SILENT_HANG_SEC, 180)
        self.assertLess(S.AgentSession.SILENT_NOTICE_SEC, S.AgentSession.SILENT_HANG_SEC)
        self.assertLess(S.AgentSession.SILENT_HANG_SEC, AGY_PRINT_TIMEOUT_SEC)

    def test_a_provider_log_line_from_an_earlier_turn_does_not_extend_this_one(self):
        s = self._busy(self.make(), hang_sec=0.3)
        s.proc = types.SimpleNamespace(pid=4242)
        s._last_turn_activity_at = 0.0
        s.adapter.last_activity = lambda pid, started: s.turn_started_at - 1   # seen before this turn began
        self.assertFalse(s._provider_shows_activity())
        s._silent_hang_fire()
        self.assertTrue(getattr(s, "_silent_hang_done", False))

    def test_is_silent_after_the_notice_window_only_while_busy(self):
        import time
        s = self._busy(self.make())
        s.SILENT_NOTICE_SEC = 90
        self.assertFalse(s.is_silent, "fresh activity is not silence")
        s._last_turn_activity_at = s.turn_started_at = time.time() - 91
        self.assertTrue(s.is_silent)
        s.busy = False
        self.assertFalse(s.is_silent, "an idle session is not a silent turn")

    def test_btw_tells_the_side_answer_the_main_turn_is_silent(self):
        import time
        s = self._busy(self.make())
        s._last_turn_activity_at = s.turn_started_at = time.time() - 120
        s._proc_alive = lambda: True
        prompts = []
        orig = S._oneshot
        S._oneshot = lambda prompt, timeout: prompts.append(prompt) or {"text": "ok"}
        try:
            s._run_btw("지금 어디까지 했어?")
        finally:
            S._oneshot = orig
        self.assertIn("90초 이상 무응답(침묵)", prompts[0])
        self.assertIn("'정상 진행 중'이라고 꾸며내지 마세요", prompts[0])

    def test_btw_prompt_stays_plain_for_a_lively_turn(self):
        self.assertNotIn("무응답", SW._btw_prompt("q", True, []))
        self.assertIn("무응답", SW._btw_prompt("q", True, [], True))


class AgyToolInfoEvents(Base):
    """The agy adapter turns `step_update.tool_info` into canonical tool events itself (provider neutrality)."""

    @staticmethod
    def step(s, state, output=None, i=3):
        info = {"name": "run_command", "parameters": {"CommandLine": "ls -la", "toolSummary": "list"}}
        if output is not None:
            info["output"] = output
        line = {"event": "step_update", "step_update": {"step_index": i, "state": state, "step_type": "tool",
                                                        "tool_name": "run_command", "tool_info": info}}
        return AgyAdapter().normalize_line(s, json.dumps(line))

    def test_the_call_then_the_result_each_once(self):
        s = self.make()
        active = self.step(s, "ACTIVE")
        done = self.step(s, "DONE", output="total 8\nfile.txt")
        self.assertEqual([(e["event"], e["kind"], e["status"]) for e in active], [("tool", "call", "calling")])
        self.assertEqual(active[0]["text"], "run_command: ls -la (list)")
        self.assertEqual(active[0]["title"], "run_command")
        self.assertEqual([(e["event"], e["kind"], e["status"]) for e in done], [("tool", "result", "done")])
        self.assertEqual(done[0]["text"], "↳ total 8 (외 1줄)")
        self.assertIn("file.txt", done[0]["detail"])

    def test_a_done_step_seen_alone_carries_both(self):
        s = self.make()
        evs = self.step(s, "DONE", output="ok")
        self.assertEqual([e["kind"] for e in evs], ["call", "result"])
        self.assertEqual(evs[1]["text"], "↳ ok")
        self.assertFalse([e for e in evs if e.get("event") == "provider_event"])


class SteerAtZeroChars(Base):
    def test_a_steer_before_any_text_adds_nothing_and_clears_the_turn(self):
        s = self.make(HISTORY)
        s.busy, s.current_text = True, ""
        s.interrupt_current_turn(reason="steer")
        self.assertFalse(s.busy)
        self.assertEqual(s.current_text, "")
        self.assertEqual(s.history, HISTORY)
        self.assertFalse([h for h in s.history if h.get("interrupted")])
        self.assertEqual([e["reason"] for e in self.events if e.get("event") == "interrupted"], ["steer"])

    def test_a_plain_interrupt_before_any_text_adds_nothing(self):
        s = self.make(HISTORY)
        s.busy = True
        s.interrupt_current_turn()
        self.assertEqual(s.history, HISTORY)
        self.assertFalse(s.busy)

    def test_a_notice_turn_that_cannot_start_does_not_leave_busy_stuck(self):
        s = self.make()
        s.adapter.keeps_stdin_open = True
        s.ensure = lambda: None

        def dead(_payload):
            raise BrokenPipeError("pipe closed")
        s.proc = types.SimpleNamespace(stdin=types.SimpleNamespace(write=dead, flush=lambda: None))
        with self.assertRaises(BrokenPipeError):
            s._send_direct("이벤트 알림", notice=True)
        self.assertFalse(s.busy)
        self.assertEqual(s.history, [])


if __name__ == "__main__":
    unittest.main()

