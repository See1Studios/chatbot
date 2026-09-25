"""CONTENT_GUARD_v1: preflight block, refusal -> warn notice, provider-neutral table.
Run: python3 -m unittest tests.test_content_guards  (from services/chatbot)
"""
import ast
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import content_guard  # noqa: E402
from providers import adapters  # noqa: E402

TABLE = {
    "locale": "ko",
    "texts": {"ko": {"k.pre": "사전 차단", "k.post": "거절 공지"}},
    "default": {
        "pre_filter": {"keywords": ["금지어"], "patterns": ["bad\\s+thing"], "notice_key": "k.pre", "default_text": "pre"},
        "post_refusal": {"finish_reasons": ["content_filter", "safety", "refusal"], "max_chars": 50,
                         "patterns": ["^I can't help with that"], "notice_key": "k.post", "default_text": "post"},
    },
    "providers": {"p2": {"pre_filter": {"keywords": ["other"], "default_text": "p2 only"}}},
}


class Preflight(unittest.TestCase):
    def test_keyword_and_pattern_block(self):
        self.assertEqual(content_guard.check_preflight("p1", "이건 금지어 포함", TABLE), (True, "사전 차단"))
        self.assertEqual(content_guard.check_preflight("p1", "a BAD  thing", TABLE), (True, "사전 차단"))

    def test_clean_and_empty_pass(self):
        self.assertEqual(content_guard.check_preflight("p1", "안녕", TABLE), (False, ""))
        self.assertEqual(content_guard.check_preflight("p1", "  ", TABLE), (False, ""))

    def test_provider_override_then_default_text(self):
        self.assertEqual(content_guard.check_preflight("p2", "금지어", TABLE), (False, ""))
        self.assertEqual(content_guard.check_preflight("p2", "other", TABLE), (True, "p2 only"))

    def test_broken_pattern_is_skipped(self):
        t = {"default": {"pre_filter": {"patterns": ["(", "x"], "default_text": "d"}}}
        self.assertEqual(content_guard.check_preflight("p", "x", t), (True, "d"))


class Refusal(unittest.TestCase):
    def test_finish_reason_counts(self):
        for r in ("content_filter", "SAFETY", "refusal"):
            self.assertEqual(content_guard.intercept_refusal("p1", "", r, TABLE), (True, "거절 공지"))
        self.assertEqual(content_guard.intercept_refusal("p1", "hi", "stop", TABLE), (False, ""))

    def test_pattern_only_on_short_answers(self):
        self.assertTrue(content_guard.intercept_refusal("p1", "I can't help with that.", None, TABLE)[0])
        long = "I can't help with that. " + "but here is a real answer " * 5
        self.assertFalse(content_guard.intercept_refusal("p1", long, None, TABLE)[0])

    def test_shipped_table_loads_and_is_neutral(self):
        t = content_guard.load_table()
        self.assertTrue(t["default"]["pre_filter"] and t["default"]["post_refusal"])
        for sec in (t["default"]["pre_filter"], t["default"]["post_refusal"]):
            for p in sec["patterns"]:
                re.compile(p)
            self.assertIn(sec["notice_key"], t["texts"][t["locale"]])
        self.assertTrue(content_guard.intercept_refusal("any", "", "content_filter")[0])
        self.assertFalse(content_guard.intercept_refusal("any", "물론이죠, 코드는 이렇습니다.", "stop")[0])
        self.assertFalse(content_guard.check_preflight("any", "파이썬 정렬 코드 짜줘")[0])
        # the table's defaults name no provider; overrides are keyed by id only
        default_src = json.dumps(t["default"], ensure_ascii=False).lower()
        for pid in adapters.AGENT_ADAPTERS:
            self.assertNotIn('"%s"' % pid, default_src)


class _Sess:
    def __init__(self):
        self.provider, self.model = "p1", ""
        self.current_text, self.turn_started_at, self.pending_images = "", 0, []
        self.history, self.saved = [], 0

    def _rewrite_artifact_paths(self, t):
        return t

    def _append_images_markdown(self, t, _since):
        return t

    def save_meta(self):
        self.saved += 1


class FinalizeTurn(unittest.TestCase):
    def setUp(self):
        self._orig = content_guard.load_table
        content_guard.load_table = lambda path=None: TABLE

    def tearDown(self):
        content_guard.load_table = self._orig

    def test_refusal_becomes_warn_notice(self):
        s = _Sess()
        out = adapters.AgentAdapter().finalize_turn(s, "I can't help with that.", None)
        self.assertEqual((out["event"], out["notice"], out["text"]), ("error", "warn", "거절 공지"))
        self.assertEqual((s.history[-1]["notice"], s.history[-1]["text"]), ("warn", "거절 공지"))

    def test_finish_reason_refusal_with_empty_text(self):
        s = _Sess()
        out = adapters.AgentAdapter().finalize_turn(s, "", None, finish_reason="content_filter")
        self.assertEqual(out.get("notice"), "warn")
        self.assertEqual(len(s.history), 1)

    def test_normal_answer_untouched(self):
        s = _Sess()
        out = adapters.AgentAdapter().finalize_turn(s, "여기 답입니다", None)
        self.assertEqual(out["event"], "result")
        self.assertNotIn("notice", s.history[-1])

    def test_plain_error_stays_error(self):
        s = _Sess()
        out = adapters.AgentAdapter().finalize_turn(s, "", None, is_err=True, error="boom")
        self.assertEqual(out.get("notice"), "error")


class Wiring(unittest.TestCase):
    def test_server_checks_before_send_and_module_is_neutral(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertLess(src.index("content_guard.check_preflight("), src.index("rotated = sess.send(text"))
        names = {getattr(n, "id", getattr(n, "name", getattr(n, "attr", "")))
                 for n in ast.walk(ast.parse((ROOT / "content_guard.py").read_text(encoding="utf-8")))}
        pat = re.compile("|".join(map(re.escape, adapters.AGENT_ADAPTERS)), re.I)
        self.assertEqual([n for n in names if n and pat.search(str(n))], [])

    def test_notice_item_shape(self):
        item, ev = content_guard.notice_item("x", ts=1.0)
        self.assertEqual(item, {"role": "assistant", "text": "x", "notice": "warn", "ts": 1.0})
        self.assertEqual((ev["event"], ev["notice"], ev["ts"]), ("error", "warn", 1.0))


if __name__ == "__main__":
    unittest.main()
