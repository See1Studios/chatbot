"""PROVIDER_NEUTRAL_v1: media_handler knows no provider; adapters register where each CLI keeps its media.
Run: python3 -m unittest tests.test_media_sources  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
from providers import adapters  # noqa: E402,F401  (registers the sources)
import media_handler as MH  # noqa: E402
import session as S  # noqa: E402
from tests.test_instructions import WorkspaceCase  # noqa: E402


class Base(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self._saved = (S.SESSIONS, S.HOME, S.WORKSPACE, getattr(S, "BRAIN", None))
        S.SESSIONS = self.tmp / "sessions"
        S.HOME = self.tmp / "home"
        S.WORKSPACE = self.ws
        S.BRAIN = self.tmp / "brain"
        (S.SESSIONS / "t").mkdir(parents=True)
        self.cid = "conv-1"
        self.bdir = S.BRAIN / self.cid
        self.bdir.mkdir(parents=True)
        (self.bdir / "shot.png").write_bytes(b"\x89PNGfake")
        self.s = S.AgentSession("t", provider="agy")
        self.s.conversation_id = self.cid

    def tearDown(self):
        S.SESSIONS, S.HOME, S.WORKSPACE, brain = self._saved
        if brain is None:
            del S.BRAIN
        else:
            S.BRAIN = brain
        super().tearDown()


class RegistryTest(Base):
    def test_sources_come_from_the_provider_module(self):
        names = {type(s).__name__ for s in MH._SOURCES}
        self.assertTrue({"AgyMediaSource", "GrokMediaSource"} <= names)
        self.assertEqual(MH.MediaSource().scan_dirs("x", 0), [])   # the base knows nothing

    def test_artifacts_tab_lists_the_providers_conversation_files(self):
        arts = self.s.get_artifacts()
        self.assertTrue(any("shot.png" in str(a) for a in arts), arts)

    def test_absolute_provider_paths_in_text_are_staged(self):
        out = self.s._rewrite_artifact_paths("see %s/shot.png" % self.bdir)
        self.assertIn("/artifacts/t/brain/shot.png", out)
        self.assertTrue((S.SESSIONS / "t" / "artifacts" / "brain" / "shot.png").is_file())

    def test_new_images_are_found_through_the_registry(self):
        self.assertIn("shot.png", {p.name for p in self.s._collect_new_images(since_ts=0)})

    def test_without_sources_no_provider_folder_is_known(self):
        saved = list(MH._SOURCES)
        MH._SOURCES.clear()
        try:
            self.assertNotIn("shot.png", {p.name for p in self.s._collect_new_images(since_ts=0)})
            self.assertEqual(self.s._artifact_dirs(), [])
        finally:
            MH._SOURCES.extend(saved)


if __name__ == "__main__":
    unittest.main()
