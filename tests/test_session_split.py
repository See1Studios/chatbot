"""Work and private talk are separate sessions (SESSION_SPLIT_v1, plan doc §12): the live work session never
lands on a private one, each character's private session is reused, and a private bundle carries no work.
Run: python3 -m unittest tests.test_session_split  (from services/chatbot)
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import characters as C  # noqa: E402
import host_config  # noqa: E402
import instructions as I  # noqa: E402
import server  # noqa: E402
import session as S  # noqa: E402


class SessionSplit(unittest.TestCase):
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
        payload = {"id": sid, "history": [{"role": "user", "text": "hi"}], "successor_session_id": ""}
        payload.update(extra)
        (d / "meta.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_the_live_work_session_skips_private_and_other_characters(self):
        self.write("20260921-100000-work01")
        self.write("20260921-110000-priv01", mode="private")
        self.write("20260921-120000-other1", character=C.new_id())
        self.assertEqual(self.reg.get_active().sid, "20260921-100000-work01")
        self.assertEqual(self.reg.get_active().mode, "work")

    def test_a_private_session_is_created_once_and_keeps_its_mode(self):
        work = self.reg.get_active()
        work.provider, work.model = "agy", "gemini-3.1-pro-high"
        priv = self.reg.get_private("", like=work)
        self.assertTrue(priv.is_private)
        self.assertEqual((priv.provider, priv.model), ("agy", "gemini-3.1-pro-high"))
        self.assertTrue(priv.history == [] and priv.sid != work.sid)
        priv.history.append({"role": "user", "text": "x", "ts": 1})
        priv.save_meta()
        again = S.Registry()
        self.assertEqual(again.get_private("").sid, priv.sid)
        self.assertEqual(again.get(priv.sid).mode, "private")
        self.assertEqual(again.get_active().sid, work.sid)
        listed = {x["id"]: x["mode"] for x in again.list()}
        self.assertEqual(listed[priv.sid], "private")

    def test_private_sessions_are_per_character(self):
        other = C.new_id()
        a = self.reg.get_private("")
        b = self.reg.get_private(other)
        for s in (a, b):
            s.history.append({"role": "user", "text": "x", "ts": 1})
            s.save_meta()
        self.assertNotEqual(a.sid, b.sid)
        self.assertEqual(S.Registry().get_private(other).sid, b.sid)
        self.assertEqual(S.Registry().get_private(other).character, other)

    def test_the_successor_of_a_private_session_is_private(self):
        self.write("20260921-100000-work01")
        self.write("20260921-110000-priv01", mode="private", successor_session_id="20260921-130000-priv02")
        self.write("20260921-130000-priv02", mode="private")
        self.assertEqual(self.reg.get_private("").sid, "20260921-130000-priv02")


class NewSessionKeepsKind(unittest.TestCase):
    """/new (POST /api/sessions) in a private or non-default character's session stays there (#154)."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.pd, self.lulu = C.new_id(), C.new_id()
        C.save(self.pd, C.new_card("P", "pd"), self.ws)
        C.save(self.lulu, C.new_card("L", "staff"), self.ws)
        self.saved = (S.SESSIONS, S.WORKSPACE, I.WORKSPACE, host_config.WORKSPACE)
        S.SESSIONS = self.tmp / "sessions"
        S.SESSIONS.mkdir()
        S.WORKSPACE = I.WORKSPACE = host_config.WORKSPACE = self.ws
        self.reg = S.Registry()

    def tearDown(self):
        S.SESSIONS, S.WORKSPACE, I.WORKSPACE, host_config.WORKSPACE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new(self, body):
        mode, character = server._new_session_kind(body)
        return self.reg.create(model="m", provider="agy", mode=mode, character=character)

    def test_a_private_session_with_a_character_keeps_both(self):
        sess = self.new({"mode": "private", "character": self.lulu})
        self.assertEqual((sess.mode, sess.character), ("private", self.lulu))
        again = S.Registry().get(sess.sid)
        self.assertEqual((again.mode, again.character), ("private", self.lulu))

    def test_no_mode_or_character_is_the_default_work_session(self):
        sess = self.new({})
        self.assertEqual((sess.mode, sess.character), ("work", self.pd))
        self.assertEqual(server._new_session_kind({"mode": "bogus", "character": ""}), ("work", ""))

    def test_an_unknown_character_is_refused(self):
        self.assertIsNone(server._new_session_kind({"character": C.new_id()}))
        self.assertIsNone(server._new_session_kind({"character": "../x"}))


class PrivateBundle(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        (self.ws / "memory").mkdir()
        (self.ws / "AGENTS.md").write_text("charter", encoding="utf-8")
        (self.ws / "memory" / "MEMORY.md").write_text("# Memory\n- work fact\n", encoding="utf-8")
        card = C.new_card("P", "pd", description="persona body")
        card["data"]["system_prompt"] = "private rules"
        self.cid = C.new_id()
        C.save(self.cid, card, self.ws)
        C.remember_private(self.cid, ["likes tea"], ws=self.ws)
        self.saved = (I.WORKSPACE, I.MEMORY_FILE)
        I.WORKSPACE, I.MEMORY_FILE = self.ws, self.ws / "memory" / "MEMORY.md"

    def tearDown(self):
        I.WORKSPACE, I.MEMORY_FILE = self.saved
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_private_gets_private_rules_and_memory_and_no_work(self):
        text = I.build_instruction_bundle(mode="private")["text"]
        for want in ("charter", "persona body", "private rules", "likes tea", I.PRIVATE_SESSION_NOTE):
            self.assertIn(want, text)
        for never in ("work fact", "[스킬 색인]", "[자기개선 상태]"):
            self.assertNotIn(never, text)
        work = I.build_instruction_bundle()["text"]
        self.assertIn("work fact", work)
        self.assertNotIn("likes tea", work)
        self.assertNotIn("private rules", work)
        self.assertNotEqual(I.build_instruction_bundle(mode="private")["hash"], I.build_instruction_bundle()["hash"])
        self.assertIn("likes tea", I.build_instruction_bundle(mode="private", character=self.cid)["text"])


if __name__ == "__main__":
    unittest.main()
