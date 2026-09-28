"""CHOICES_LEAK_RESCUE_v1: a model that writes its `choices` tool call into the answer as text (seen on
gemini-3.8-flash-high: `</tool_call>` + `{"name": "choices", "arguments": {...}}`) must not leave JSON on screen and
no buttons. The server takes the call out of the text for every provider and turns it into the turn's choices; the
page hides it while the answer is still arriving. Commands are never rescued from text.
Run: python3 -m unittest tests.test_choices_leak  (from services/chatbot)
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
from providers.adapter_base import rescue_leaked_choices  # noqa: E402
from providers.adapters import AgyAdapter  # noqa: E402

# The two leaks as they were logged on 2026-09-28 (session 20260928-142512-2454c6), items shortened.
CALL = ('{"name": "choices", "arguments": {"action": "choices", "items": ['
        '{"label": "잠깐, 가까이", "kind": "command", "payload": "act"}, '
        '{"label": "고개 기울여", "kind": "command", "payload": "act"}, '
        '{"label": "말없이 안기", "kind": "command", "payload": "act"}]}}')
TAGGED = "아, 내 실수야~ 지금 다시 걸게.\n\n</tool_call>\n" + CALL + "\n</tool_call>"
BARE = "이마를 코치의 어깨에 가만히 댔다.\n\n아무 말도 하지 않았다.\n\n" + CALL
WANT = ["잠깐, 가까이 -> (잠깐, 가까이)", "고개 기울여 -> (고개 기울여)", "말없이 안기 -> (말없이 안기)"]


def fake_session():
    s = types.SimpleNamespace(current_text="", pending_images=[], history=[], turn_started_at=0, provider="agy",
                              model="m", served_model="")
    s._rewrite_artifact_paths = lambda t: t
    s._append_images_markdown = lambda t, since=None: t
    s.save_meta = lambda: None
    return s


class Rescue(unittest.TestCase):
    def test_both_logged_leaks_become_choices_and_clean_text(self):
        self.assertEqual(rescue_leaked_choices(TAGGED), ("아, 내 실수야~ 지금 다시 걸게.", WANT))
        self.assertEqual(rescue_leaked_choices(BARE), ("이마를 코치의 어깨에 가만히 댔다.\n\n아무 말도 하지 않았다.", WANT))

    def test_say_and_action_keep_the_page_s_forms(self):
        call = json.dumps({"name": "choices", "arguments": {"items": [
            {"label": "웃기", "kind": "action", "payload": "(살짝 웃는다)"},
            {"label": "대답", "kind": "say", "payload": "좋아"}]}}, ensure_ascii=False)
        self.assertEqual(rescue_leaked_choices("본문 " + call)[1], ["웃기 -> (살짝 웃는다)", '대답 -> "좋아"'])

    def test_a_command_is_never_rescued_but_the_json_still_leaves(self):
        call = json.dumps({"name": "choices", "arguments": {"items": [
            {"label": "재시작", "kind": "command", "payload": "/defib"},
            {"label": "그만", "kind": "say", "payload": "그만"}]}}, ensure_ascii=False)
        self.assertEqual(rescue_leaked_choices("앞\n" + call + "\n뒤"), ("앞\n\n뒤", []))

    def test_ordinary_text_is_untouched(self):
        for text in ("그냥 대답이야", '설정은 {"a": 1} 이렇게', "선택지(choices)는 다음에", '{"name": "memory"}',
                     '"name": "choices" 라고 적힌 글', "도구 형식 예시:\n```json\n" + CALL + "\n```"):
            self.assertEqual(rescue_leaked_choices(text), (text, []), text)

    def test_the_turn_carries_the_rescued_choices(self):
        s = fake_session()
        s.current_text = TAGGED
        ev = AgyAdapter().finalize_turn(session=s, text="", raw_usage=None)
        self.assertEqual((ev["text"], ev["choices"]), ("아, 내 실수야~ 지금 다시 걸게.", WANT))
        self.assertEqual(s.history[-1]["choices"], WANT, "the tension engine reads the offer from history")

    def test_a_real_marker_wins(self):
        s = fake_session()
        s.current_text = "답\n<!--choices: 진행 | 보류-->"
        ev = AgyAdapter().finalize_turn(session=s, text="", raw_usage=None)
        self.assertEqual(ev["choices"], ["진행", "보류"])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PageHidesItWhileStreaming(unittest.TestCase):
    def test_the_leak_is_never_typed_out(self):
        src = (ROOT / "static" / "markdown.js").read_text(encoding="utf-8")
        a = src.index("const LEAKED_TOOL_CALL")
        b = src.index("function prepareStreamText")
        prefixes = [TAGGED[:n] for n in (len("아, 내 실수야~ 지금 다시 걸게."), len(TAGGED) // 2, len(TAGGED))]
        prefixes += [BARE[:len(BARE) - len(CALL) + 20], "그냥 {중괄호} 있는 글"]
        js = src[a:b] + "\nconsole.log(JSON.stringify(%s.map(hideLeakedToolCall)));" % json.dumps(prefixes, ensure_ascii=False)
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        got = json.loads(out.stdout)
        self.assertEqual(got[:3], ["아, 내 실수야~ 지금 다시 걸게."] * 3)
        self.assertEqual(got[3], "이마를 코치의 어깨에 가만히 댔다.\n\n아무 말도 하지 않았다.")
        self.assertEqual(got[4], "그냥 {중괄호} 있는 글")


if __name__ == "__main__":
    unittest.main()
