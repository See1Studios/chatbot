"""CONTEXT_METRIC_v1 (token-economy): a session's weight reads the last model call's prompt, not the turn's summed
input. Measured 2026-10-05 from agy's own transcripts: the lead's calls carried 49-89k each, while the turn usage
(every call of the turn added up) read 240-500k, warned "heavy" 55 times and rotated 15 sessions in one day.
Run: python3 -m unittest tests.test_session_weight_context  (from services/chatbot)
"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
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
        src = (ROOT / "providers" / "adapter_agy.py").read_text(encoding="utf-8")
        self.assertIn('"context_tokens": session._call_context', src)            # carried into the turn usage

if __name__ == "__main__":
    unittest.main()
