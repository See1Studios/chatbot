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
from adapters import AgyAdapter, AGY_PRINT_TIMEOUT_SEC  # noqa: E402
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
        s = S.AgySession("t", provider="agy")
        s.adapter = types.SimpleNamespace(id="agy", keeps_stdin_open=False, transport_kind="process",
                                          format_stdin=lambda c: c, mints_own_conversation_id=lambda: False)
        s.history = list(history or [])
        self.events, self.sent, self.stops = [], [], []
        s._emit = self.events.append
        s.save_meta = lambda: None
        s.stop = lambda notify=True: self.stops.append(notify)
        s._spawn = lambda prompt="": self.sent.append(prompt)
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

    def test_only_agy_is_checked_against_agys_store(self):
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
    def result(self, s, **kw):
        res = {"conversation_id": REAL, "status": "SUCCESS", "response": "", "duration_seconds": 5, **kw}
        return self.feed(s, {"event": "result", "result": res})

    def test_the_print_timeout_empty_result_is_surfaced_and_the_child_is_stopped(self):
        s = self.make()
        self.result(s, duration_seconds=AGY_PRINT_TIMEOUT_SEC + 1)      # what 00:48:30 looked like
        s._auto_stop_worker = lambda: self.stops.append("worker")
        # _auto_stop started a real thread; give it a moment to run stop()
        import time; time.sleep(0.2)
        errors = [e for e in self.events if e.get("event") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("답을 내기 전에", errors[0]["text"])
        self.assertTrue(self.stops, "the still-running child must be stopped")
        self.assertIn("답을 내지 못하고", s._loop_hint)

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


if __name__ == "__main__":
    unittest.main()
