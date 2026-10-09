"""BRAIN_LIMITS_v1 (docs/plans/director-handoff.md dir/J): a brain that ran out is remembered until its reset, so the
delegation runner skips it at once instead of spending another try or another 20-minute timeout on it.
Run: engine/run-tests.sh test_brain_limits
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
        self.assertTrue(B.unavailable("timed out after 1200s", -1))
        self.assertFalse(B.unavailable("timed out after 1200s while working (last model activity 4s ago)", -1),
                         "#868: busy to the cutoff, the brain is fine")
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
        # Invalid model or provider error
        self.assertTrue(B.unavailable("model claude-opus-4-6-thinking is not recognized as a known model", 1))
        self.assertTrue(B.unavailable("error: invalid model selection", 1))
        self.assertTrue(B.unavailable("502 Bad Gateway: service unavailable", 1))
        self.assertTrue(B.unavailable("500 Internal Server Error", 1))
        self.assertTrue(B.unavailable("connection refused by peer", 1))

    def test_agy_model_family_resolution(self) -> None:
        from providers.adapter_agy import _resolve_agy_model
        known = [
            "gemini-3.8-flash-high",
            "gemini-3.8-flash-medium",
            "gemini-3.8-flash-low",
            "gemini-3.7-flash-high",
            "gemini-3.1-pro-high",
            "claude-opus-5-5-low",
            "claude-opus-5-5-medium",
            "claude-opus-5-5-high",
            "claude-sonnet-5-5-high",
            "gpt-oss-120b-medium",
        ]
        # exact match
        self.assertEqual(_resolve_agy_model("gemini-3.8-flash-medium", known), "gemini-3.8-flash-medium")
        # outdated model identifier mapped to latest high effort candidate
        self.assertEqual(_resolve_agy_model("claude-opus-4-6-thinking", known), "claude-opus-5-5-high")
        # family only mapped to highest version and high effort
        self.assertEqual(_resolve_agy_model("claude-opus", known), "claude-opus-5-5-high")
        self.assertEqual(_resolve_agy_model("gemini-flash", known), "gemini-3.8-flash-high")
        self.assertEqual(_resolve_agy_model("gemini-pro", known), "gemini-3.1-pro-high")
        # effort preference respected
        self.assertEqual(_resolve_agy_model("claude-opus-medium", known), "claude-opus-5-5-medium")
        self.assertEqual(_resolve_agy_model("gemini-flash-low", known), "gemini-3.8-flash-low")
        # unknown or custom pattern returns input unchanged
        self.assertEqual(_resolve_agy_model("unknown-custom-model", known), "unknown-custom-model")
        self.assertEqual(_resolve_agy_model("gemini-x", known), "gemini-x")


if __name__ == "__main__":
    unittest.main()

