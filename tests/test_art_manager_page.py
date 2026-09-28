"""The art manager modal, the page half (static/app-art.js, character-art-manager.md am/C v0): a slot says whether it
shows its own picture, what it falls back to, or the placeholder; a finished job that drew into a character's
gallery is recognised from its paths; the tray and the work card open the modal. The REAL functions run in node.
Run: python3 -m unittest tests.test_art_manager_page  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const { artSlotBadge, artShownName, artGalleryCharacter, ART_TEXT } =
  new Function(src + '; return { artSlotBadge, artShownName, artGalleryCharacter, ART_TEXT };')();
console.log(JSON.stringify({
  own: artSlotBadge({ own: true }), ph: artSlotBadge({ own: false, placeholder: true }),
  falls: artSlotBadge({ own: false, placeholder: false, shows: 'sprites/bust/joy.giggle.webp' }),
  name: artShownName('sprites/bust/grok/neutral.png'),
  drew: artGalleryCharacter(['docs/x.md', 'data/workspace/characters/char_01m376xaa1e0fsdhm3e3kbnybd/gallery/nono-desk-01.png']),
  none: artGalleryCharacter(['data/workspace/characters/char_01ab/card.json']),
  tabs: [ART_TEXT.gallery, ART_TEXT.icon, ART_TEXT.background, ART_TEXT.emotion].every(Boolean),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ArtManagerPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-art.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_slot_says_what_it_shows(self):
        self.assertEqual(self.o["own"][1], "own")
        self.assertEqual(self.o["ph"][1], "ph")
        self.assertEqual(self.o["falls"], ["→ joy.giggle", "falls"])
        self.assertEqual(self.o["name"], "neutral")

    def test_a_job_that_drew_into_a_gallery_is_recognised(self):
        self.assertEqual(self.o["drew"], "char_01m376xaa1e0fsdhm3e3kbnybd")
        self.assertEqual(self.o["none"], "")
        self.assertTrue(self.o["tabs"])


class Wiring(unittest.TestCase):
    def test_the_page_loads_it_and_two_places_open_it(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('./app-art.js', page)
        self.assertIn('./art-manager.css', page)
        self.assertLess(page.index("./app-art.js"), page.index("./app.js?"))
        self.assertIn("openArtManager(openCharacterId())", (STATIC / "app-characters.js").read_text(encoding="utf-8"))
        self.assertIn("openArtManager(drewFor, 'gallery')", (STATIC / "app-evolution.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
