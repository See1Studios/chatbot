"""A doctor-probe session (X-Chatbot-Caller: doctor-probe) is never listed, never live, and never flips the
operator's session after a restart (#227).
Run: python3 -m unittest tests.test_probe_session_hidden  (from services/chatbot)
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import session as S  # noqa: E402


class ProbeSessionHidden(unittest.TestCase):
    OWN = "20260921-180000-mine01"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._sessions = S.SESSIONS
        S.SESSIONS = self.tmp / "sessions"
        S.SESSIONS.mkdir()
        self.reg = S.Registry()
        d = S.SESSIONS / self.OWN
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({
            "id": self.OWN, "provider": "claude", "model": "claude-sonnet-5",
            "history": [{"role": "user", "text": "real work"}],
        }), encoding="utf-8")

    def tearDown(self):
        S.SESSIONS = self._sessions
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_probe_session_is_not_listed(self):
        probe = self.reg.create(probe=True)
        ids = [m["id"] for m in self.reg.list()]
        self.assertNotIn(probe.sid, ids)
        self.assertIn(self.OWN, ids)
        self.assertTrue(self.reg.is_probe(probe.sid))
        self.assertFalse(self.reg.is_probe(self.OWN))

    def test_probe_session_is_not_active_even_before_its_ping(self):
        probe = self.reg.create(probe=True)          # empty history: the text heuristic alone can't see it yet
        self.assertGreater(probe.sid, self.OWN)
        self.assertEqual(self.reg.get_active().sid, self.OWN)

    def test_normal_session_keeps_its_provider_after_restart(self):
        self.reg.create(probe=True)
        restarted = S.Registry()                     # a fresh process: only disk state survives
        live = restarted.get_active()
        self.assertEqual(live.sid, self.OWN)
        self.assertEqual(live.provider, "claude")
        self.assertEqual([m["id"] for m in restarted.list()], [self.OWN])


if __name__ == "__main__":
    unittest.main()
