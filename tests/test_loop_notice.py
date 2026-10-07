"""A repeat that reaches its warning threshold makes the host tell the agent to change course (agy only),
instead of only warning the operator. Same interrupt-at-a-step-boundary-and-resume as a steer, so the work
done is kept; if the repeat goes on anyway the turn is stopped after LOOP_STOP_AFTER_NOTICE more repeats.

Why (2026-09-21): a Gemini turn re-read the same 1949-line file ten times until the guard stopped it, and
nothing reached the agent in between. Whether the notice actually pulls a looping agent out is NOT measured
(the loop could not be reproduced, agy.md A46) -- these tests only pin the mechanics.
Run: engine/run-tests.sh test_loop_notice
"""
import json
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import session as S  # noqa: E402
from providers.adapters import AgyAdapter  # noqa: E402
from loop_guard import LoopGuard  # noqa: E402
from tests.test_conversation_sync import Base as SyncBase  # noqa: E402
from tests.test_steer import Base as SteerBase, stub_adapter  # noqa: E402


def read_done(i=0, path="/src/adapters.py"):
    """One finished read: same arguments, same content every time (a stat-only output is not evidence)."""
    return {"event": "step_update", "step_update": {"step_index": i, "state": "DONE", "step_type": "tool",
            "tool_name": "view_file", "tool_info": {"name": "view_file", "parameters": {"AbsolutePath": path},
                                                    "output": "1: import json\n2: import os"}}}


class NoticeCase(SteerBase):
    def make(self, provider="agy"):
        s = super().make(provider)

        def send_direct(text, mid="", client_context=None, notice=False):
            self.sent.append((text, notice))
            self.delivered.set()
        s._send_direct = send_direct
        return s

    def repeat(self, s, n):
        for i in range(n):
            AgyAdapter().normalize_line(s, json.dumps(read_done(i)))

    def systems(self):
        return [e for e in self.events if e.get("event") == "system" and "⚠" in str(e.get("text"))]


class NoticeInsteadOfWarning(NoticeCase):
    def test_a_repeat_at_the_warning_threshold_interrupts_and_resumes_with_a_notice(self):
        s = self.make()
        self.repeat(s, 5)                                          # consecutive-warning threshold
        self.assertTrue(self.delivered.wait(3), "the notice was not sent")
        self.assertEqual(self.interrupts, ["loop"])
        text, notice = self.sent[0]
        self.assertTrue(notice)
        self.assertIn("repeating the same tool call", text)
        self.assertIn("view_file", text)                           # says WHAT repeated
        self.assertIn("StartLine/EndLine", text)                   # and what to do instead
        warn = self.systems()
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0]["evidence"]["action"], "notice")  # the operator sees it, with the call as evidence
        self.assertEqual([e for e in self.events if e.get("event") == "stopped"], [])

    def test_only_once_per_user_turn(self):
        s = self.make()
        self.repeat(s, 5)
        self.assertTrue(self.delivered.wait(3))
        s.busy = True
        s._loop_stopping = False
        s._loop_guard.reset()
        self.repeat(s, 5)                                          # the agent kept repeating
        self.assertEqual(self.interrupts, ["loop"])                # no second notice
        self.assertEqual(len(self.sent), 1)
        self.assertIn("If it keeps repeating, it stops by itself", str(self.systems()[-1]["text"]))   # plain warning as before

    def test_a_message_the_user_already_has_waiting_is_left_to_the_steer_path(self):
        s = self.make()
        s.msg_queue.append(("이것도 해줘", "m1"))
        self.repeat(s, 5)
        self.assertNotIn("loop", self.interrupts)

    def test_providers_that_cannot_resume_keep_the_plain_warning(self):
        s = self.make("claude")
        self.repeat(s, 5)
        self.assertEqual(self.interrupts, [])
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.systems()), 1)
        self.assertNotIn("action", self.systems()[0]["evidence"])

    def test_the_turn_ending_meanwhile_sends_nothing(self):
        s = self.make()
        s.busy = False
        s._notice_loop_worker("view_file /src/adapters.py")
        self.assertEqual(self.sent, [])
        self.assertFalse(s._loop_stopping)                        # the flag is released either way


class OverBudget(NoticeCase):
    """Rule D (token-economy.md, #614): reads of different files, none repeated, still cost the whole turn."""

    def read_new(self, s, n, size):
        for i in range(n):
            line = {"event": "step_update", "step_update": {"step_index": i, "state": "DONE", "step_type": "tool",
                    "tool_name": "view_file", "tool_info": {"name": "view_file",
                                                            "parameters": {"AbsolutePath": "/src/f%d.py" % i},
                                                            "output": "900 lines, %d bytes" % size}}}
            AgyAdapter().normalize_line(s, json.dumps(line))

    def test_the_agent_is_told_to_delegate_or_wrap_up(self):
        s = self.make()
        self.read_new(s, 2, 300_000)                               # 600 KB of whole-file reads
        self.assertTrue(self.delivered.wait(3), "the budget notice was not sent")
        text, notice = self.sent[0]
        self.assertTrue(notice)
        self.assertIn("over its budget (2 tool calls, 600 KB read)", text)   # English for the agent (principle 0)
        self.assertIn("delegate", text)
        self.assertNotIn("repeating the same tool call", text)


class TheNoticeIsNotAUserMessage(SyncBase):
    def test_no_bubble_no_history_and_the_guard_gets_stricter_until_the_user_speaks_again(self):
        s = self.make()
        s._send_direct(S.LOOP_NOTICE.format(what="view_file adapters.py", user="실장님"), notice=True)
        self.assertEqual(s.history, [])                            # not something the user said
        self.assertEqual([e for e in self.events if e.get("event") == "user_ack"], [])
        self.assertTrue(self.sent[-1].endswith("[Host note] " + S.LOOP_NOTICE.format(what="view_file adapters.py", user="실장님")))
        self.assertEqual(s._loop_guard.exact_stop, S.LOOP_STOP_AFTER_NOTICE)
        self.assertEqual(s._loop_guard.consec_stop, S.LOOP_STOP_AFTER_NOTICE)

        s._loop_noticed = True
        s._send_direct("다음 거 해줘")                              # a real message starts a fresh user turn
        self.assertEqual([h["text"] for h in s.history], ["다음 거 해줘"])
        self.assertEqual(s._loop_guard.exact_stop, 10)
        self.assertFalse(s._loop_noticed)


class StrictAfterTheNotice(unittest.TestCase):
    def repeats_until_stop(self, g):
        for i in range(1, 12):
            v = g.observe("view_file", {"AbsolutePath": "/a.py"}, "1: import json\n2: import os")
            if v is not None and v.level == "stop":
                return i
        return None

    def test_tighten_survives_reset_and_relax_restores(self):
        g = LoopGuard()
        self.assertEqual(self.repeats_until_stop(g), 8)            # consecutive stop, as before
        g = LoopGuard()
        g.tighten(3)
        g.reset()                                                  # the resumed turn resets the guard
        self.assertEqual(self.repeats_until_stop(g), 3)
        g.relax()
        g.reset()
        self.assertEqual(self.repeats_until_stop(g), 8)

    def test_tighten_never_loosens(self):
        g = LoopGuard(exact_stop=2, consec_stop=2)
        g.tighten(3)
        self.assertEqual((g.exact_stop, g.consec_stop), (2, 2))


class BudgetSetting(unittest.TestCase):
    def test_a_host_may_set_the_turn_budget(self):
        # HANDOFF_DRILL_v1: the drill's sandbox runs short budgets
        from unittest import mock
        with mock.patch.dict("os.environ", {"CHATBOT_TURN_BUDGET_CALLS": "3,6"}):
            self.assertEqual(LoopGuard().budget_calls, (3, 6))
        for bad in ("6,3", "x", "0,4"):
            with mock.patch.dict("os.environ", {"CHATBOT_TURN_BUDGET_CALLS": bad}):
                self.assertEqual(LoopGuard().budget_calls, (20, 40), bad)
        self.assertEqual(LoopGuard().budget_calls, (20, 40))


if __name__ == "__main__":
    unittest.main()
