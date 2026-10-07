"""BRAIN_LIMITS_v1 (docs/plans/director-handoff.md dir/J): a brain that ran out is remembered until its reset, so the
delegation runner skips it at once instead of spending another try or another 20-minute timeout on it.
Run: python3 -m unittest tests.test_brain_limits  (from services/chatbot)
"""
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE / "tools"))
import brain_limits as B  # noqa: E402

A = {"provider": "agy", "model": "opus"}
G = {"provider": "grok", "model": ""}


class BrainLimits(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "runs" / "brain_limits.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_reset_time_in_the_error_sets_the_rest(self) -> None:
        self.assertEqual(B.rest_for("Individual quota reached. Resets in 146h32m12s."), 146 * 3600 + 32 * 60 + 12)
        self.assertEqual(B.rest_for("Resets in 35s"), 60)                         # at least a minute
        self.assertEqual(B.rest_for("timed out after 1200s"), B.TIMEOUT_REST)
        self.assertEqual(B.rest_for("rate limit"), B.UNKNOWN_REST)
        self.assertEqual(B.rest_for("Resets in 999h"), B.MAX_REST)

    def test_a_resting_brain_is_left_out_until_its_reset(self) -> None:
        B.mark(self.path, A, "quota reached, resets in 2h", now=1000.0)
        ok, resting = B.usable(self.path, [A, G], now=1000.0 + 3600)
        self.assertEqual(ok, [G])
        self.assertEqual(len(resting), 1)
        self.assertTrue(resting[0].startswith("agy/opus until "))
        self.assertEqual(B.usable(self.path, [A, G], now=1000.0 + 7201)[0], [A, G])

    def test_an_unreadable_state_only_turns_the_memory_off(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json")
        self.assertEqual(B.usable(self.path, [A]), ([A], []))
        B.mark(self.path, A, "timed out")                                         # rewrites it
        self.assertEqual(B.usable(self.path, [A])[0], [])

    def test_labels_and_the_unavailable_test(self) -> None:
        self.assertEqual(B.brain_label(G), "grok/default")
        self.assertTrue(B.unavailable("Error: quota exceeded", 1))
        self.assertTrue(B.unavailable("", -1))
        self.assertFalse(B.unavailable("SyntaxError", 1))


if __name__ == "__main__":
    unittest.main()
