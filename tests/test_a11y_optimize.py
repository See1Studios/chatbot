"""Chat-page load and stream cost (impeccable optimize).

The chat page does not load the hub sheet (its font imports and amber tokens).
A resting notice is not its own layer. A long stream spans only its tail.

Run: engine/run-tests.sh test_a11y_optimize
"""
import re
import unittest
from pathlib import Path

from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"


def text(name):
    return (STATIC / name).read_text(encoding="utf-8")


def block(css, selector):
    m = re.search(r"(?m)^[ \t]*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


class ChatPageSkipsTheHubSheet(unittest.TestCase):
    def test_index_does_not_load_sphere_theme(self):
        html = text("index.html")
        self.assertNotIn("sphere-theme.css", html)
        self.assertIn("pretendardvariable-dynamic-subset.min.css", html)
        base = text("chat-base.css")
        self.assertIn("color-scheme: dark", block(base, "html, body"))


class RestingNoticeIsNotALayer(unittest.TestCase):
    def test_will_change_lives_only_on_the_moving_notice(self):
        css = text("chat-composer.css")
        self.assertNotIn("will-change", block(css, ".msg.system"))
        self.assertIn("will-change:transform,opacity", block(css, ".msg.system.swiping"))
        self.assertIn("will-change:transform,opacity", block(css, ".msg.system.dismissing"))


class LongStreamSpansItsTail(unittest.TestCase):
    def test_the_letter_clock_caps_the_live_spans(self):
        src = text("app-sse.js")
        self.assertIn("spanFrom = n > 24 ? n - 24 : 0", src)
        self.assertIn("at < spanFrom", src)


if __name__ == "__main__":
    unittest.main()
