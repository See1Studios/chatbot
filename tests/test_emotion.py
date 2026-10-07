"""Emotion tags in assistant text become at most one `emotion` SSE event per turn (#251, emotion.py).
Run: python3 -m unittest tests.test_emotion  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import emotion  # noqa: E402


class Parse(unittest.TestCase):
    def test_the_tag_forms_and_keywords(self):
        cases = {
            "좋아요 *표정: Happy*": "happy",
            "[emotion: sad] 그렇구나": "sad",
            "음 [shy]": "shy",
            "happy! 오늘은 좋다": "happy",
            "오늘은 좋다 — thinking...": "thinking",
            "그냥 평범한 문장": None,
            "[unknown]": None,
            "": None,
        }
        for text, want in cases.items():
            self.assertEqual(emotion.parse(text), want, text)


class Tracker(unittest.TestCase):
    def test_a_streamed_sentence_sends_once_per_turn(self):
        t = emotion.Tracker()
        self.assertIsNone(t.feed({"event": "delta", "text": "안녕하세요"}))
        self.assertEqual(t.feed({"event": "delta", "text": " [happy]. 더 말하면"}), "happy")
        self.assertIsNone(t.feed({"event": "delta", "text": " [sad]."}))          # one per turn
        self.assertIsNone(t.feed({"event": "result", "text": "[sad]"}))           # already sent this turn
        self.assertEqual(t.feed({"event": "delta", "text": "*표정: angry*"}), "angry")   # next turn starts fresh

    def test_the_result_is_the_fallback(self):
        t = emotion.Tracker()
        self.assertIsNone(t.feed({"event": "delta", "text": "태그 없는 답"}))
        self.assertEqual(t.feed({"event": "result", "text": "끝 [surprised]"}), "surprised")

    def test_other_events_pass_through(self):
        t = emotion.Tracker()
        self.assertIsNone(t.feed({"event": "tool", "text": "[happy]"}))
        self.assertIsNone(t.feed({"event": "error"}))


if __name__ == "__main__":
    unittest.main()
