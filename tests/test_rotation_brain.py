"""#885: a heavy-session rotation starts the successor on the character's saved brain. It copied the old session's
model, so after the work brain was set to flash-low (2026-10-09) the default character's long talk rotated onto flash-high and the
first answer took 73 s.
Run: engine/run-tests.sh test_rotation_brain
"""
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import session  # noqa: E402,F401 -- session_registry reads it at import
import session_registry as SR  # noqa: E402


class RotationBrain(unittest.TestCase):
    def setUp(self):
        self.reg = SR.Registry.__new__(SR.Registry)
        self.old = SimpleNamespace(character="c1", mode="work", provider="agy", model="gemini-3.8-flash-high",
                                   effort="")

    def test_the_saved_choice_wins_over_the_old_session_s_model(self):
        saved = {"provider": "agy", "model": "gemini-3.8-flash-low", "effort": ""}
        with mock.patch.object(SR, "_override_brain", lambda cid, mode: saved if mode == "work" else {}), \
                mock.patch.object(SR, "_character_id", lambda c: c):
            self.assertEqual(self.reg.rotation_brain(self.old)["model"], "gemini-3.8-flash-low")

    def test_without_a_saved_choice_the_successor_keeps_the_brain_it_was_on(self):
        with mock.patch.object(SR, "_override_brain", lambda cid, mode: {}), \
                mock.patch.object(SR, "_character_id", lambda c: c):
            self.assertEqual(self.reg.rotation_brain(self.old),
                             {"provider": "agy", "model": "gemini-3.8-flash-high", "effort": ""})

    def test_the_rotation_asks_for_it(self):
        src = (ENGINE / "session_turn.py").read_text(encoding="utf-8")
        rot = src[src.index("def _rotate_to_fresh_session"):]
        rot = rot[:rot.index("\n    def ", 10)]
        self.assertIn("brain = _s().REG.rotation_brain(self)", rot)
        self.assertIn('model=brain["model"]', rot)
        self.assertNotIn("model=self.model", rot)


if __name__ == "__main__":
    unittest.main()
