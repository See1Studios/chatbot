"""The page appears once, after boot has drawn it (BOOT_CURTAIN_v1): the page starts hidden (static/index.html
html.booting, laid out but transparent), app.js lifts it two frames after boot() settles and in any case after
BOOT_CURTAIN_MAX_MS, and the stage fades in only once its own picture has loaded (no stand-in first).
Run: engine/run-tests.sh test_boot_curtain
"""
import re
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"
read = lambda n: (STATIC / n).read_text(encoding="utf-8")


class BootCurtain(unittest.TestCase):
    def test_the_page_starts_behind_the_curtain(self):
        self.assertRegex(read("index.html"), r'<html lang="ko" class="booting">')
        css = read("chat-base.css")
        self.assertIn("html.booting body{opacity:0}", css)
        self.assertIn("html{background:var(--bg)}", css, "no white flash behind a transparent body")
        self.assertNotRegex(css, r"html\.booting[^{]*\{[^}]*display:\s*none", "hidden, never unlaid: boot measures")

    def test_boot_lifts_it_and_a_hung_boot_cannot_keep_it(self):
        app = read("app.js")
        self.assertIn("setTimeout(liftBootCurtain, BOOT_CURTAIN_MAX_MS);", app)
        self.assertLessEqual(int(re.search(r"BOOT_CURTAIN_MAX_MS = (\d+)", app).group(1)), 5000)
        tail = app[app.index("setTimeout(liftBootCurtain"):]
        self.assertRegex(tail, r"(boot\(\)|\.then\(boot\))[\s\S]*\.finally\([\s\S]*liftBootCurtain")   # I18N_v1: after the words

    def test_nothing_overwrites_the_root_classes(self):
        for js in STATIC.glob("*.js"):
            self.assertNotRegex(js.read_text(encoding="utf-8"), r"documentElement\.className\s*=", js.name)

    def test_the_stage_waits_for_its_own_picture(self):
        self.assertIn("html:not(.stage-ready) .stage::before{opacity:0 !important}", read("chat-log.css"))
        chars = read("app-characters.js")
        fn = chars[chars.index("function updateStageBackground"):chars.index("function updateBrandAvatar")]
        self.assertEqual(fn.count("ready();"), 2, "both the picture and its fallback lift the stage")


if __name__ == "__main__":
    unittest.main()
