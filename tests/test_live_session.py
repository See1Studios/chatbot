"""Live conversation is newest session id + successor tip, not mtime.
Run: python3 -m unittest tests.test_live_session  (from services/chatbot)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session as S  # noqa: E402


class LiveSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._sessions = S.SESSIONS
        S.SESSIONS = self.tmp / "sessions"
        S.SESSIONS.mkdir()
        self.reg = S.Registry()

    def tearDown(self):
        S.SESSIONS = self._sessions
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, sid, **extra):
        d = S.SESSIONS / sid
        d.mkdir()
        payload = {
            "id": sid,
            "history": [{"role": "user", "text": "hi"}],
            "successor_session_id": "",
        }
        payload.update(extra)
        (d / "meta.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_a_recently_opened_past_session_is_not_live(self):
        self.write("20260920-090000-past1", history=[{"role": "user", "text": "old"}])
        self.write("20260921-180000-latest9", history=[{"role": "user", "text": "new"}])
        past = S.SESSIONS / "20260920-090000-past1" / "meta.json"
        os.utime(past, (9_999_999_999, 9_999_999_999))
        self.assertEqual(self.reg.get_active().sid, "20260921-180000-latest9")

    def test_a_newer_probe_session_is_skipped(self):
        self.write("20260921-180000-latest9", history=[{"role": "user", "text": "real"}])
        self.write("20260921-190000-probe1", history=[{"role": "user", "text": "[doctor-probe] ping"}])
        self.assertEqual(self.reg.get_active().sid, "20260921-180000-latest9")

    def test_a_non_timestamp_sid_cannot_become_live(self):
        self.write("20260921-180000-latest9", history=[{"role": "user", "text": "real"}])
        self.write("nonexistent-sid-test", history=[{"role": "user", "text": "leak"}] * 3)
        self.assertEqual(self.reg.get_active().sid, "20260921-180000-latest9")

    def test_successor_tip_is_live(self):
        self.write(
            "20260921-120000-mid2",
            history=[{"role": "user", "text": "m"}],
            successor_session_id="20260921-180000-latest9",
        )
        self.write("20260921-180000-latest9", history=[{"role": "user", "text": "l"}])
        self.assertEqual(self.reg.get_active().sid, "20260921-180000-latest9")


if __name__ == "__main__":
    unittest.main()
