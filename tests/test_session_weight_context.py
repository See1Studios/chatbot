"""CONTEXT_METRIC_v1 (token-economy): a session's weight reads the last model call's prompt, not the turn's summed
input. Measured 2026-10-05 from agy's own transcripts: the lead's calls carried 49-89k each, while the turn usage
(every call of the turn added up) read 240-500k, warned "heavy" 55 times and rotated 15 sessions in one day.
Run: engine/run-tests.sh test_session_weight_context
"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import session_weights as W  # noqa: E402
from providers.adapter_agy import AgyAdapter  # noqa: E402


class ContextMetric(unittest.TestCase):
    def test_the_recorded_call_context_wins_over_the_summed_turn_input(self):
        hist = [{"role": "assistant", "usage": {"input_tokens": 480_000, "context_tokens": 61_000}}]
        self.assertEqual(W._current_context_tokens(hist), 61_000)
        self.assertEqual(W._session_weight(hist, None)["level"], "ok")
        old = [{"role": "assistant", "usage": {"input_tokens": 480_000}}]          # no record: as before
        self.assertEqual(W._session_weight(old, None)["level"], "hard")

    def test_the_agy_adapter_keeps_the_last_calls_prompt_for_the_turn(self):
        sess = SimpleNamespace(_call_context=0, current_text="", _stop_requested=False,
                               _maybe_capture_conversation_id=lambda o: None, _observe_agent_step=lambda o: None,
                               _tool_summary=lambda o: None, _rewrite_artifact_paths=lambda t: t)
        a = AgyAdapter.__new__(AgyAdapter)
        a._tool_info_events = lambda s, o: []
        for u in ({"input_tokens": 13873, "cache_read_tokens": 0}, {"input_tokens": 2000, "cache_read_tokens": 14644}):
            a.normalize_line(sess, json.dumps({"step_update": {"step_type": "agent_response", "state": "DONE",
                                                               "usage": u}}))
        self.assertEqual(sess._call_context, 16644)                               # the last call, not the sum
        src = (ENGINE / "providers" / "adapter_agy.py").read_text(encoding="utf-8")
        self.assertIn('"context_tokens": session._call_context', src)            # carried into the turn usage

    def test_agy_turn_usage_is_the_turns_share_of_the_conversation_total(self):
        # TURN_USAGE_v1, measured 2026-10-05: 42,941 then 57,662 for a one-call "ping" turn; 2.1M on a fresh process
        hist = []
        sess = SimpleNamespace(_call_context=0, conversation_id="c1", history=hist)
        first = AgyAdapter._turn_usage(sess, {"usage": {"input_tokens": 42941, "output_tokens": 307}})
        self.assertEqual(first["input_tokens"], 42941)
        hist.append({"role": "assistant", "usage": first})
        second = AgyAdapter._turn_usage(sess, {"usage": {"input_tokens": 57662, "output_tokens": 308}})
        self.assertEqual((second["input_tokens"], second["output_tokens"]), (14721, 1))
        hist.append({"role": "assistant", "usage": second})
        # a restart: a new process resumes the same conversation; the total carries on, and so does the base
        third = AgyAdapter._turn_usage(sess, {"usage": {"input_tokens": 60000, "output_tokens": 310}})
        self.assertEqual(third["input_tokens"], 2338)
        sess.conversation_id = "c2"                                             # a new conversation starts at zero
        self.assertEqual(AgyAdapter._turn_usage(sess, {"usage": {"input_tokens": 9000}})["input_tokens"], 9000)
        import time
        sess.turn_started_at = time.time() - 46
        AgyAdapter._turn_usage(sess, {"usage": {"input_tokens": 9100}, "duration_seconds": 535.0})
        self.assertFalse(sess._turn_timed_out)          # agy's 535 s is the running total; this turn took 46 s (#8)
        sess.turn_started_at = time.time() - 489
        AgyAdapter._turn_usage(sess, {"usage": {"input_tokens": 9200}})
        self.assertTrue(sess._turn_timed_out)                                   # ran to the 8-minute print timeout

if __name__ == "__main__":
    unittest.main()
