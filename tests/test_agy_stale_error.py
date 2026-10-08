"""agy's result reports the conversation, not the turn (STALE_ERROR_v1): after one failed turn every later result in
the conversation carried the same error, so good answers were stored as failed (2026-10-08: a Claude-route quota hit at
13:32, then nine Gemini answers marked with it). The repeated error on a SUCCESS turn with an answer is dropped; a first
error, a changed one, a failed status or an empty answer stays.
Run: engine/run-tests.sh test_agy_stale_error
"""
import unittest
from types import SimpleNamespace

from providers.adapter_agy import AgyAdapter  # noqa: E402

QUOTA = "Individual quota reached. Resets in 4h52m55s."


class StaleError(unittest.TestCase):
    def setUp(self):
        self.s = SimpleNamespace(conversation_id="c1")

    def fresh(self, err, status="SUCCESS", answer="hi"):
        return AgyAdapter._fresh_error(self.s, err, status, answer)

    def test_the_first_error_counts_and_its_repeats_on_good_answers_do_not(self):
        self.assertEqual(self.fresh(QUOTA), QUOTA)
        self.assertEqual(self.fresh(QUOTA), "")
        self.assertEqual(self.fresh(QUOTA, status=""), "")

    def test_a_repeat_that_really_failed_still_counts(self):
        self.fresh(QUOTA)
        self.assertEqual(self.fresh(QUOTA, answer="  "), QUOTA, "no answer: the error is this turn's")
        self.assertEqual(self.fresh(QUOTA, status="ERROR"), QUOTA)

    def test_a_new_error_or_a_new_conversation_counts(self):
        self.fresh(QUOTA)
        self.assertEqual(self.fresh("other"), "other")
        self.s.conversation_id = "c2"
        self.assertEqual(self.fresh("other"), "other")

    def test_no_error_is_no_error(self):
        self.assertEqual(self.fresh(""), "")

    def test_the_result_path_uses_it(self):
        from pathlib import Path
        import providers.adapter_agy as m
        self.assertIn("res_err = self._fresh_error(session,", Path(m.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
