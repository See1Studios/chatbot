"""Every chat bubble is the same frosted glass (BUBBLE_GLASS_v1, static/chat-log.css): one dark base and one blur for
all kinds, so text reads the same over the stage and character art; a kind only sets its tint (--tint) and border.
Read from the stylesheets: no bubble rule (a .msg selector without descendants) sets its own background or blur.
Run: engine/run-tests.sh test_bubble_glass
"""
import re
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"
PARTS = ["chat-base.css", "chat-log.css", "chat-composer.css", "chat-panes.css", "chat-responsive.css", "chat-features.css"]
KINDS = [".msg.user", ".msg.assistant", ".msg.action", ".msg.system", ".msg.btw-card"]
BUBBLE = re.compile(r"^(?:body[.\w-]*\s+)?\.msg(?:\.[\w-]+)+$")   # the bubble itself, not something inside it


def rules():
    for name in PARTS:
        css = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
        for sel, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
            yield name, [s.strip() for s in sel.split(",")], body


class BubbleGlass(unittest.TestCase):
    def test_one_rule_gives_every_kind_the_base_and_the_blur(self):
        shared = [(n, b) for n, sels, b in rules() if set(KINDS) <= set(sels)]
        self.assertEqual(len(shared), 1, "one shared glass rule")
        body = shared[0][1]
        self.assertIn("var(--bubble-base)", body)
        self.assertIn("backdrop-filter:var(--bubble-blur)", body)
        self.assertIn("-webkit-backdrop-filter:var(--bubble-blur)", body)

    def test_a_kind_sets_its_tint_never_its_own_background_or_blur(self):
        for name, sels, body in rules():
            if set(KINDS) <= set(sels):
                continue
            for sel in sels:
                if BUBBLE.match(sel):
                    self.assertNotRegex(body, r"(?<![-\w])background(-color|-image)?\s*:", "%s %s: set --tint" % (name, sel))
                    self.assertNotRegex(body, r"backdrop-filter\s*:", "%s %s: the blur is shared" % (name, sel))

    def test_every_kind_is_tinted_by_colour(self):
        tinted = {s for _, sels, b in rules() for s in sels if "--tint:" in b}
        for sel in [".msg.user", ".msg.system", ".msg.btw-card", ".msg.system.notice-warn", ".msg.system.notice-error"]:
            self.assertIn(sel, tinted)


if __name__ == "__main__":
    unittest.main()
