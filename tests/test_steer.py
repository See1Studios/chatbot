"""A message sent while an agy turn is running is accepted at once and applied at the next
tool-step boundary -- without cutting the work in flight (2026-09-20).
Measured first (agy.md A41): a second stdin line only QUEUES until the turn ends; the old design
killed the turn instead. Run: python3 -m unittest tests.test_steer  (from services/chatbot)
"""
import json
import sys
import threading
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session as S  # noqa: E402
from adapters import AgyAdapter  # noqa: E402
from tests.test_instructions import WorkspaceCase  # noqa: E402

TOOL_DONE = {"event": "step_update", "step_update": {"step_index": 3, "state": "DONE", "step_type": "tool",
             "tool_name": "run_command", "tool_info": {"name": "run_command", "parameters": {"CommandLine": "sleep 6"}}}}
TEXT_DONE = {"event": "step_update", "step_update": {"step_index": 4, "state": "DONE", "step_type": "agent_response",
             "text_delta": "생각 중"}}
ACTION = "이 함수도 같이 고쳐줘"


def stub_adapter(provider="agy", process=True):
    return types.SimpleNamespace(id=provider, keeps_stdin_open=process, transport_kind="process" if process else "http",
                                 format_stdin=lambda c: c, mints_own_conversation_id=lambda: provider != "agy")


class Base(WorkspaceCase):
    def make(self, provider="agy"):
        self._sessions = S.SESSIONS
        S.SESSIONS = self.tmp / "sessions"
        (S.SESSIONS / "t").mkdir(parents=True, exist_ok=True)
        s = S.AgySession("t", provider="agy")
        s.adapter = stub_adapter(provider)
        s.provider = provider
        s.busy = True
        s.proc = types.SimpleNamespace(poll=lambda: None)              # the turn is really running
        self.events, self.interrupts, self.sent = [], [], []
        s._emit = self.events.append
        s.save_meta = lambda: None
        s._emit_heavy_if_needed = lambda: {}
        self.delivered = threading.Event()

        def interrupt(reason="interrupted"):
            self.interrupts.append(reason)
            s.busy = False
            s.msg_queue.clear()                                          # the real one clears the queue too
        s.interrupt_current_turn = interrupt

        def send_direct(text, mid=""):
            self.sent.append((text, mid, s._loop_hint))
            self.delivered.set()
        s._send_direct = send_direct
        return s

    def tearDown(self):
        if hasattr(self, "_sessions"):
            S.SESSIONS = self._sessions

    def tool_done(self, s):
        return AgyAdapter().normalize_line(s, json.dumps(TOOL_DONE))

    def kinds(self):
        return [e.get("event") for e in self.events]


class AcceptWithoutCutting(Base):
    def test_a_message_while_busy_is_queued_and_the_turn_is_not_touched(self):
        s = self.make()
        s.send(ACTION, "m1")
        self.assertEqual(s.msg_queue, [(ACTION, "m1")])
        self.assertEqual(self.interrupts, [])                            # the work in flight keeps going
        self.assertEqual(self.sent, [])
        self.assertIn("steer_queued", self.kinds())
        self.assertTrue(s.busy)

    def test_a_question_while_busy_still_takes_the_side_channel(self):
        s = self.make()
        q = "이거 왜 이렇게 동작해?"
        self.assertTrue(S._is_inquiry(q), "premise: this text is classified as a question")
        ran = threading.Event()
        s._run_btw = lambda query: ran.set()
        s.send(q, "m2")
        self.assertTrue(ran.wait(2))
        self.assertEqual((s.msg_queue, self.interrupts), ([], []))

    def test_providers_that_cannot_steer_still_interrupt_at_once_but_say_the_work_was_paused(self):
        s = self.make(provider="claude")
        s.send(ACTION, "m3")
        self.assertEqual(self.interrupts, ["interrupted"])
        self.assertEqual(s.msg_queue, [])
        self.assertEqual(self.sent[0][2], S.STEER_HINT)                  # hint set when the message goes out


class ApplyAtTheNextBoundary(Base):
    def wait(self, ev, t=3):
        self.assertTrue(ev.wait(t), "the steer did not happen")

    def test_a_finished_tool_step_hands_the_message_over_and_resumes(self):
        s = self.make()
        s.send(ACTION, "m1")
        self.tool_done(s)
        self.wait(self.delivered)
        self.assertEqual(self.interrupts, ["steer"])
        self.assertEqual(self.sent, [(ACTION, "m1", S.STEER_HINT)])
        self.assertIn("취소된 것이 아닙니다", S.STEER_HINT)               # the agent is told to continue, not restart
        self.assertEqual(s.msg_queue, [])

    def test_one_message_per_boundary_the_rest_wait_for_the_next(self):
        s = self.make()
        s.send("첫째 지시", "a")
        s.send("둘째 지시", "b")
        self.tool_done(s)
        self.wait(self.delivered)
        self.assertEqual([t for t, _, _ in self.sent], ["첫째 지시"])
        self.assertEqual(s.msg_queue, [("둘째 지시", "b")])              # re-queued after the interrupt cleared it

    def test_text_steps_are_not_boundaries_and_neither_is_an_empty_queue(self):
        s = self.make()
        s.send(ACTION, "m1")
        AgyAdapter().normalize_line(s, json.dumps(TEXT_DONE))
        time.sleep(0.2)
        self.assertEqual((self.interrupts, self.sent), ([], []))
        s2 = self.make()                                                 # nothing waiting -> a tool step changes nothing
        self.tool_done(s2)
        time.sleep(0.2)
        self.assertEqual((self.interrupts, self.sent), ([], []))

    def test_a_steer_already_in_progress_is_not_started_twice(self):
        s = self.make()
        s.send(ACTION, "m1")
        s._steering = True
        self.tool_done(s)
        time.sleep(0.2)
        self.assertEqual(self.interrupts, [])

    def test_if_the_turn_ends_first_the_message_is_delivered_by_the_normal_end_of_turn_path(self):
        s = self.make()
        s.send(ACTION, "m1")
        done = threading.Event()
        s._dispatch_queued = done.set
        s._handle_events([{"event": "result", "text": "완료"}])
        self.assertTrue(done.wait(2))
        self.assertEqual(self.interrupts, [])                            # no cut: it just runs next

    def test_worker_gives_up_quietly_if_the_turn_ended_meanwhile(self):
        s = self.make()
        s.send(ACTION, "m1")
        s.busy = False
        s._steer_worker()
        self.assertEqual((self.interrupts, self.sent), ([], []))
        self.assertEqual(s.msg_queue, [(ACTION, "m1")])                  # left for _dispatch_queued


class TimerFallback(Base):
    def test_no_boundary_for_a_long_time_steers_anyway_but_not_before(self):
        s = self.make()
        s.send(ACTION, "m1")
        s._steer_at_boundary(forced=True)                                # just queued: too early
        time.sleep(0.2)
        self.assertEqual(self.interrupts, [])
        s._steer_since = time.time() - S.STEER_MAX_WAIT_SEC - 5
        s._steer_at_boundary(forced=True)
        self.assertTrue(self.delivered.wait(3))
        self.assertEqual(self.interrupts, ["steer"])


class HintReachesTheWire(WorkspaceCase):
    def test_the_hint_is_prepended_once_and_the_message_is_kept_verbatim(self):
        S.SESSIONS = self.tmp / "sessions"
        (S.SESSIONS / "t").mkdir(parents=True, exist_ok=True)
        s = S.AgySession("t", provider="agy")
        s.adapter = types.SimpleNamespace(id="agy", keeps_stdin_open=False, transport_kind="process",
                                          format_stdin=lambda c: c, mints_own_conversation_id=lambda: False)
        sent = []
        s._spawn = lambda prompt="": sent.append(prompt)
        s._emit = lambda ev: None
        s.persona_injected, s.persona_bundle_hash = True, "x"
        s._loop_hint = S.STEER_HINT
        s._send_direct("세 번 다 끝나면 수정됨이라고 답해")
        s._send_direct("다음 메시지")
        self.assertIn("취소된 것이 아닙니다", sent[0])
        self.assertTrue(sent[0].rstrip().endswith("세 번 다 끝나면 수정됨이라고 답해"))
        self.assertEqual(sent[1], "다음 메시지")                          # said once


class ReaderIsBoundToItsChild(Base):
    """A steer kills the child and respawns in milliseconds; the OLD child's reader must not
    touch the NEW turn."""

    def fake(self, lines):
        return types.SimpleNamespace(stdout=iter(lines), poll=lambda: None)

    def test_leftovers_of_a_replaced_child_are_ignored_and_its_exit_leaves_the_new_turn_alone(self):
        s = self.make()
        old, new = self.fake(['{"event":"result"}\n']), self.fake([])
        s.proc = new                                                     # the newer child is now current
        handled = []
        s._handle_stdout_line = handled.append
        s.busy = True                                                    # the NEW turn is running
        s._read_stdout(old)
        self.assertEqual(handled, [])
        self.assertTrue(s.busy)
        self.assertNotIn("error", self.kinds())

    def test_the_current_child_dying_mid_turn_is_still_reported(self):
        s = self.make()
        cur = self.fake([])
        s.proc, s.busy = cur, True
        s._read_stdout(cur)
        self.assertFalse(s.busy)
        self.assertIn("error", self.kinds())

    def test_the_current_childs_lines_are_processed(self):
        s = self.make()
        cur = self.fake(['{"a":1}\n', '\n', '{"b":2}\n'])
        s.proc = cur
        handled = []
        s._handle_stdout_line = handled.append
        s._read_stdout(cur)
        self.assertEqual(handled, ['{"a":1}', '{"b":2}'])


if __name__ == "__main__":
    unittest.main()
