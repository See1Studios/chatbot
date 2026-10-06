"""CONTEXT_PANEL_v1 (docs/plans/layered-context-architecture.md lca/E): the status tab shows what went into the open
conversation's agent. The session keeps its last injections (kept across a restart), GET /api/sessions/<sid>/context
serves them, and the page names every layer in Korean.
Run: python3 -m unittest tests.test_context_panel  (from services/chatbot)
"""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import instructions as I  # noqa: E402
import obslog  # noqa: E402
import session as S  # noqa: E402

STATIC = ROOT / "static"


class SessionRecord(unittest.TestCase):
    def make(self):
        s = S.AgentSession.__new__(S.AgentSession)
        s.sid, s.provider, s.mode, s.character = "sid-1", "agy", "work", ""
        return s

    def test_each_injection_is_kept_newest_last_and_capped(self):
        s = self.make()
        with mock.patch.object(obslog, "event"), mock.patch.object(I, "context_alerts", return_value=[]):
            s._log_context({"text": "x" * 10, "hash": "h", "layers": [{"id": "charter", "kind": "rules", "chars": 10}]})
            s.persona_injected = True
            for i in range(S.CONTEXT_LOG_KEEP + 2):
                s._log_context({"text": "y", "layers": [{"id": "house_memory", "chars": 1}]}, "refresh")
        self.assertEqual(len(s.context_log), S.CONTEXT_LOG_KEEP)
        self.assertEqual(s.context_log[-1]["why"], "refresh")
        self.assertEqual(s.context_log[-1]["layers"], [{"id": "house_memory", "chars": 1}])
        self.assertTrue(set(s.context_log[-1]) == {"ts", "why", "chars", "layers"}, "sizes and ids only, never text")

    def test_the_record_is_saved_with_the_session(self):
        src = (ROOT / "session.py").read_text(encoding="utf-8")
        self.assertIn('"context_log": list(getattr(self, "context_log", []) or [])[-CONTEXT_LOG_KEEP:]', src)
        self.assertIn('self.context_log = list(meta.get("context_log") or [])[-CONTEXT_LOG_KEEP:]', src)

    def test_the_route_serves_it(self):
        import route_sessions as R
        s = self.make()
        s.context_log = [{"ts": 1.0, "why": "first", "chars": 5, "layers": []}]
        got = {}
        req = type("Q", (), {"arg": "sid-1", "json": lambda self, d, code=200: got.update(d),
                             "send": lambda self, *a: got.update(status=a[0])})()
        with mock.patch.object(R.REG, "peek", return_value=s):
            R.context(req)
        self.assertEqual(got["records"], s.context_log)
        with mock.patch.object(R.REG, "peek", return_value=None):
            R.context(req)
        self.assertEqual(got["status"], 404)
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertLess(server.index('"/api/sessions/*/context"'), server.index('("/api/sessions/*", route_sessions.detail)'))


class Page(unittest.TestCase):
    def test_every_layer_and_reason_has_a_name_in_every_language(self):
        whys = {"first", "rules_changed", "refresh", "lore"}   # session_turn._log_context's reasons
        for cat in sorted((STATIC / "i18n").glob("*.json")):
            keys = json.loads(cat.read_text(encoding="utf-8"))
            self.assertEqual({x.id for x in I.LAYERS if "context.layer." + x.id not in keys}, set(),
                             "%s: a new layer needs its name" % cat.name)
            self.assertEqual({w for w in whys if "context.why." + w not in keys}, set(), cat.name)

    def test_the_panel_loads_with_the_status_tab(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="statusContext"', html)
        self.assertLess(html.index('src="./app-status.js'), html.index('src="./app-status-context.js'))
        self.assertIn("loadContextNow();", (STATIC / "app-status.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
