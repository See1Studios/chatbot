"""The character's picture opens each run of its bubbles, in place of the old expression chip (BUBBLE_AVATAR_v1): the
expression rides on the bubble as attributes (static/markdown.js paintExpressionBadge, real code in node), the text
gets no chip, and the stylesheet draws the picture only on a bubble that does not follow another of the character's.
Run: python3 -m unittest tests.test_bubble_avatar  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const code = src.slice(src.indexOf('const EXPRESSION_HEAD'), src.indexOf('const THOUGHT_STATE_BLOCK'))
  + src.slice(src.indexOf('function expressionEmoji'), src.indexOf('// STREAM_FLOW_v1: the cheap projection'));
const { paintExpressionBadge } = new Function(code + '; return { paintExpressionBadge };')();
const bubble = () => ({ dataset: {}, inserted: 0, querySelector: () => null, insertBefore() { this.inserted++; } });
const out = {};
let n = bubble(); paintExpressionBadge(n, '[expression: joy]안녕'); out.joy = [n.dataset.expression, n.dataset.exp, n.inserted];
paintExpressionBadge(n, '[expression: sorrow]그래도'); out.changed = [n.dataset.expression, n.dataset.exp];
n = bubble(); paintExpressionBadge(n, '[expression: blush]음'); out.unknown = n.dataset.exp;
n = bubble(); paintExpressionBadge(n, '표정 없이'); out.none = n.dataset;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ExpressionOnTheBubble(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "markdown.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_expression_is_an_attribute_not_a_chip_in_the_text(self):
        self.assertEqual(self.o["joy"], ["joy", "\U0001F60A", 0])
        self.assertEqual(self.o["changed"], ["sorrow", "\U0001F97A"])

    def test_an_unknown_expression_gets_the_masks_and_none_leaves_the_bubble_alone(self):
        self.assertEqual(self.o["unknown"], "\U0001F3AD")
        self.assertEqual(self.o["none"], {})


class PictureOpensTheRun(unittest.TestCase):
    def test_only_a_bubble_that_does_not_follow_another_gets_the_picture(self):
        css = (STATIC / "chat-log.css").read_text(encoding="utf-8")
        start = "#log > .msg.assistant:first-child::before,#log > :not(.msg.assistant) + .msg.assistant::before{"
        self.assertIn(start, css)
        self.assertIn("background:var(--char-avatar, none) center/cover no-repeat", css[css.index(start):])
        self.assertIn("#log > :not(.msg.assistant) + .msg.assistant[data-exp]::after{", css)
        self.assertIn("content:attr(data-exp)", css)
        self.assertNotIn(".exp-badge{", css, "the chip is gone")

    def test_the_picture_is_the_header_avatar(self):
        js = (STATIC / "app-characters.js").read_text(encoding="utf-8")
        at = js.index("brandAvatarEl.src = characterPortrait(ch, p);")
        self.assertIn("setProperty('--char-avatar'", js[at:at + 400])


if __name__ == "__main__":
    unittest.main()
