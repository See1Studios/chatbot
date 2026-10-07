"""The newest-session lookup reads each meta.json once per change, not on every poll (SESSION_INDEX_v1).
Run: engine/run-tests.sh test_session_index
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import session as S  # noqa: E402
import session_registry as SR  # noqa: E402


class SessionIndex(unittest.TestCase):
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
        d.mkdir(exist_ok=True)
        payload = {"id": sid, "history": [{"role": "user", "text": "hi"}], "successor_session_id": ""}
        payload.update(extra)
        (d / "meta.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_talks_is_the_newest_work_talk_of_each_character(self):
        import os
        self.write("20260101-000000-aaaaaa", character="kit", history=[{"role": "user", "text": "old work"}])
        self.write("20260102-000000-bbbbbb", character="kit", provider="brain-b", history=[{"role": "user", "text": "new work"}])
        self.write("20260103-000000-cccccc", character="kit", mode="private", history=[{"role": "user", "text": "secret"}])
        self.write("20260104-000000-dddddd", character="kit", history=[])          # opened, nothing said
        self.write("20260105-000000-eeeeee", character="kit", mode="room", history=[{"role": "user", "text": "seat"}])
        self.write("20260101-000000-ffffff", character="ari", history=[{"role": "assistant", "text": "x" * 200}])
        for i, sid in enumerate(sorted(p.name for p in S.SESSIONS.iterdir())):   # mtime follows the id
            os.utime(S.SESSIONS / sid / "meta.json", (1000 + i, 1000 + i))
        talks = self.reg.talks()
        self.assertEqual(sorted(talks), ["ari", "kit"])
        self.assertEqual(talks["kit"]["preview"], "new work")
        self.assertEqual((talks["kit"]["provider"], talks["ari"]["provider"]), ("brain-b", ""))   # its own brain, or unknown
        self.assertEqual(len(talks["ari"]["preview"]), 80)
        self.assertNotIn("secret", json.dumps(talks))

    def test_polls_without_changes_read_no_file(self):
        self.write("20260921-100000-aaaaaa")
        self.write("20260921-110000-bbbbbb")
        self.assertEqual(self.reg.get_active().sid, "20260921-110000-bbbbbb")
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("re-read")):
            self.assertEqual(self.reg.get_active().sid, "20260921-110000-bbbbbb")
            self.assertEqual(len(self.reg.list()), 2)

    def test_a_new_session_folder_is_seen_at_once(self):
        self.write("20260921-100000-aaaaaa")
        self.reg.get_active()
        self.write("20260921-120000-cccccc")
        self.assertEqual(self.reg.get_active().sid, "20260921-120000-cccccc")

    def test_own_saves_refresh_only_that_session(self):
        a = self.reg.get_active()
        a.history.append({"role": "user", "text": "hello there", "ts": 1})
        a.save_meta()
        row = {x["id"]: x for x in self.reg.list()}[a.sid]
        self.assertEqual((row["turns"], row["preview"]), (1, "hello there"))

    def test_a_probe_session_turns_real_when_it_grows(self):
        self.write("20260921-100000-aaaaaa")
        self.write("20260921-110000-probe1", history=[{"role": "user", "text": "[diag] ping"}])
        self.assertEqual(self.reg.get_active().sid, "20260921-100000-aaaaaa")
        p = S.SESSIONS / "20260921-110000-probe1" / "meta.json"
        self.write("20260921-110000-probe1", history=[{"role": "user", "text": "[diag] ping"}] * 3)
        S._meta_touched(p)
        self.assertEqual(self.reg.get_active().sid, "20260921-110000-probe1")

    def test_other_writers_are_picked_up_after_the_rescan_window(self):
        self.write("20260921-100000-aaaaaa", mode="private")
        self.write("20260921-090000-bbbbbb")
        self.assertEqual(self.reg.get_active().sid, "20260921-090000-bbbbbb")
        self.write("20260921-100000-aaaaaa")                          # another process flips it to work
        with mock.patch.object(SR, "_META_RESCAN_SEC", 0.0):
            self.assertEqual(self.reg.get_active().sid, "20260921-100000-aaaaaa")


if __name__ == "__main__":
    unittest.main()
