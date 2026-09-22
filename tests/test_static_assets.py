"""The shell only loads what exists, and nothing still leans on the retired mascot.
Run: python3 -m unittest tests.test_static_assets  (from services/chatbot)
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")

# Globals/ids the retired mascot defined (2026-09-19). Any of them reappearing means half a
# removal or a resurrection: the overlay swallowed clicks even when it looked hidden.
RETIRED = ["mascotOverlay", "mascotStageBox", "mascotBubble", "toggleMascotBtn", "isMascotVisible",
           "setMascotTalking", "showMascotBubble", "initMascot", "triggerMascotBlink",
           "triggerMascotEarTwitch", "mascot-overlay", "mascot-layer", "mascot.js"]


class StaticAssets(unittest.TestCase):
    def test_every_local_script_and_stylesheet_in_index_html_exists(self):
        refs = re.findall(r'<(?:script[^>]+src|link[^>]+href)="\./([^"?#]+)', HTML)
        self.assertTrue(refs, "found no local asset references -- the pattern is stale")
        # vendor/*.min.js are third-party and git-ignored (installed per host), so a fresh
        # checkout legitimately lacks them; only the files this repo owns are checked.
        owned = [r for r in refs if not r.startswith("vendor/")]
        self.assertTrue(owned)
        missing = [r for r in owned if not (STATIC / r).is_file()]
        self.assertEqual(missing, [], "index.html loads files that do not exist")

    def test_no_reference_to_the_retired_mascot_remains(self):
        offenders = []
        for f in list(STATIC.glob("*.js")) + list(STATIC.glob("*.css")) + [STATIC / "index.html"]:
            text = f.read_text(encoding="utf-8")
            offenders += [f"{f.name}: {w}" for w in RETIRED if w in text]
        self.assertEqual(offenders, [])

    def test_the_retired_file_is_gone(self):
        self.assertFalse((STATIC / "mascot.js").exists())

    def test_no_overlay_layers_are_loaded_by_the_page(self):
        # the old overlay pulled ~20 layer PNGs even while hidden
        self.assertNotIn("/artifacts/see_through/", HTML)

    def test_css_braces_balance(self):
        css = (STATIC / "chat.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("{"), css.count("}"))


if __name__ == "__main__":
    unittest.main()
