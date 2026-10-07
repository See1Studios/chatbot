"""CONTEXT_METRIC_v1 on the page: the session badge's window figure is the last model call's prompt (context_tokens)
when the turn recorded it, else the turn's input as before; a bubble's tooltip shows the context too.
Run: python3 -m unittest tests.test_token_badge  (from services/chatbot)
"""
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

SRC = (REPO / "static" / "app-messages.js").read_text(encoding="utf-8")


class TokenBadge(unittest.TestCase):
    def test_the_window_prefers_the_recorded_context(self):
        self.assertIn("function windowOf(u) { return Number((u && (u.context_tokens || u.input_tokens)) || 0); }", SRC)
        self.assertEqual(SRC.count("sessionTokens.input_tokens = windowOf("), 2)        # live turns and history
        self.assertNotIn("sessionTokens.input_tokens = Number(u", SRC)

    def test_a_bubble_shows_the_context(self):
        self.assertIn("usage.context_tokens", SRC)


if __name__ == "__main__":
    unittest.main()
