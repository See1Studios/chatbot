"""Grok Imagine markdown `images/1.jpg` must become a served /artifacts URL.

Run: python3 -m unittest tests.test_grok_image_paths  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session as S  # noqa: E402
from tests.test_instructions import WorkspaceCase  # noqa: E402


class GrokRelImageRewrite(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self._sessions, self._home, self._ws = S.SESSIONS, S.HOME, S.WORKSPACE
        S.SESSIONS = self.tmp / "sessions"
        S.HOME = self.tmp / "home"
        S.WORKSPACE = self.ws
        (S.SESSIONS / "t").mkdir(parents=True)
        self.cid = "cid-test"
        gdir = S.HOME / ".grok" / "sessions" / quote(str(S.WORKSPACE), safe="") / self.cid / "images"
        gdir.mkdir(parents=True)
        (gdir / "1.jpg").write_bytes(b"\xff\xd8\xfffakejpeg")
        self.s = S.AgySession("t", provider="agy")
        self.s.conversation_id = self.cid

    def tearDown(self):
        S.SESSIONS, S.HOME, S.WORKSPACE = self._sessions, self._home, self._ws
        super().tearDown()

    def test_markdown_images_rel_becomes_artifact_url(self):
        out = self.s._rewrite_artifact_paths("현재 얼굴:\n\n![그록 고딕](images/1.jpg)\n")
        self.assertIn("/artifacts/t/brain/1.jpg", out)
        self.assertNotIn("(images/1.jpg)", out)
        staged = S.SESSIONS / "t" / "artifacts" / "brain" / "1.jpg"
        self.assertTrue(staged.is_file())

    def test_unknown_rel_image_is_left_alone(self):
        src = "![x](images/missing.jpg)"
        self.assertEqual(self.s._rewrite_artifact_paths(src), src)

    def test_collect_finds_grok_session_images(self):
        found = self.s._collect_new_images(since_ts=0)
        names = {p.name for p in found}
        self.assertIn("1.jpg", names)

    def test_rewrite_without_conversation_id_uses_newest_grok_session(self):
        self.s.conversation_id = None
        out = self.s._rewrite_artifact_paths("![x](images/1.jpg)")
        self.assertIn("/artifacts/t/brain/1.jpg", out)
        self.assertNotIn("(images/1.jpg)", out)

    def test_append_stages_when_markdown_already_has_rel_url(self):
        self.s.conversation_id = None
        out = self.s._append_images_markdown("![x](images/1.jpg)", since_ts=0)
        self.assertIn("/artifacts/t/brain/1.jpg", out)
        self.assertNotIn("(images/1.jpg)", out)
