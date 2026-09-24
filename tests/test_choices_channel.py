"""Choices leave the answer's text (OUT_OF_BAND_CHOICES_v1, docs/plans/out-of-band-choices-actions.md 1a): the server
takes the trailing `<!--choices: …-->` out once, for every provider, so history, the CLI and the agent's context keep
clean text, and sends the items beside it; the page draws the chips from them.
Run: python3 -m unittest tests.test_choices_channel  (from services/chatbot)
"""
import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from providers.adapter_base import split_choices  # noqa: E402
from providers.adapters import AgyAdapter  # noqa: E402
from tests.page_source import app_bundle  # noqa: E402


def fake_session():
    s = types.SimpleNamespace(current_text="", pending_images=[], history=[], turn_started_at=0, provider="agy",
                              model="m", served_model="")
    s._rewrite_artifact_paths = lambda t: t
    s._append_images_markdown = lambda t, since=None: t
    s.save_meta = lambda: None
    return s


class ServerSplits(unittest.TestCase):
    def test_the_last_marker_leaves_the_text(self):
        self.assertEqual(split_choices("답이야\n<!--choices: 좋아 | 싫어-->"), ("답이야", ["좋아", "싫어"]))
        self.assertEqual(split_choices("a <!--choices: x--> b <!--choices: 1 | 2 -> (웃는다)-->"),
                         ("a <!--choices: x--> b", ["1", "2 -> (웃는다)"]))

    def test_a_quoted_marker_or_none_keeps_the_text(self):
        for text in ("인용 `<!--choices: a-->` 이후 본문", "그냥 답", "<!--choices:   -->"):
            self.assertEqual(split_choices(text), (text, []))

    def test_at_most_four_short_items(self):
        _, items = split_choices("x <!--choices: " + " | ".join(["가" * 200] * 6) + "-->")
        self.assertEqual((len(items), len(items[0])), (4, 120))

    def test_the_turn_keeps_clean_text_and_carries_the_items(self):
        s = fake_session()
        s.current_text = "어떻게 할까?\n<!--choices: 진행 | 보류-->"
        ev = AgyAdapter().finalize_turn(session=s, text="", raw_usage=None)
        self.assertEqual((ev["text"], ev["choices"]), ("어떻게 할까?", ["진행", "보류"]))
        self.assertEqual((s.history[-1]["text"], s.history[-1]["choices"]), ("어떻게 할까?", ["진행", "보류"]))

    def test_no_choices_no_field(self):
        s = fake_session()
        s.current_text = "그냥 답"
        ev = AgyAdapter().finalize_turn(session=s, text="", raw_usage=None)
        self.assertNotIn("choices", ev)
        self.assertNotIn("choices", s.history[-1])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PageDrawsFromItems(unittest.TestCase):
    def test_the_marker_is_rebuilt_only_for_drawing(self):
        js = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function textWithChoices'), b = src.indexOf('function addChat', a);
eval(src.slice(a, b));
process.stdout.write(JSON.stringify([textWithChoices({ text: 'a', choices: ['x', 'y -> (웃음)'] }),
  textWithChoices({ text: 'b' }), textWithChoices({ text: 'c', choices: [' ', 3] })]));
"""
        r = subprocess.run(["node", "-e", js, str(app_bundle())], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["a\n<!--choices: x | y -> (웃음)-->", "b", "c"])


if __name__ == "__main__":
    unittest.main()
