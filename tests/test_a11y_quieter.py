"""Reboot HUD and summon portal follow the accent dial (impeccable quieter).

The scanline and the looping pulse meter are gone. Status green and red stay.
The caret still blinks and the busy mark still spins; reduced motion stops both.

Run: engine/run-tests.sh test_a11y_quieter
"""
import re
import unittest

from tests._paths import REPO  # noqa: E402

CSS = (REPO / "static" / "chat-features.css").read_text(encoding="utf-8")


def between(start, end):
    a = CSS.index(start)
    b = CSS.index(end, a) if end else len(CSS)
    return CSS[a:b]


def block(css, selector):
    m = re.search(r"(?m)^[ \t]*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


REBOOT = between("/* REBOOT_HUD_v3", "/* CHAT_MAP_v1")
SUMMON = between("/* CHARACTER_PORTAL_v1", "")


class RebootAndSummonFollowTheDial(unittest.TestCase):
    def test_neon_and_the_scanline_are_gone(self):
        for name, part in (("reboot", REBOOT), ("summon", SUMMON)):
            self.assertNotIn("#00f0ff", part, name)
            self.assertNotIn("0,240,255", part, name)
            self.assertNotIn("repeating-linear-gradient", part, name)
            self.assertIn("var(--accent)", part, name)
        self.assertNotIn("reboot-pulse-run", CSS)
        pulse = block(REBOOT, ".reboot-pulse-bar")
        self.assertNotIn("animation", pulse)
        self.assertNotIn("infinite", pulse)
        self.assertIn("#34d399", REBOOT)
        self.assertIn("#00ff88", REBOOT)
        self.assertIn("#f87171", SUMMON)

    def test_the_caret_and_the_busy_mark_still_move_until_reduced_motion(self):
        self.assertIn("reboot-blink", block(REBOOT, ".reboot-cursor"))
        self.assertIn("animation:none", REBOOT)
        self.assertIn("summon-spin", block(SUMMON, ".summon-weaver"))
        self.assertIn(".summon-weaver{animation:none}", SUMMON)


if __name__ == "__main__":
    unittest.main()
