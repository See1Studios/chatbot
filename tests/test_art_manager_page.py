"""The art manager modal, the page half (static/app-art.js, character-art-manager.md am/C v0): a slot says whether it
shows its own picture, what it falls back to, or the placeholder; a finished job that drew into a character's
gallery is recognised from its paths; the tray and the work card open the modal; a sprite pack's result
says what landed and what was skipped (am/D); the request for missing pictures names them and the spec (am/E). The REAL functions run in node.
Run: python3 -m unittest tests.test_art_manager_page  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import i18n_prelude  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "static"

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const { artSlotBadge, artShownName, artGalleryCharacter, artPackSummary, artRequestText, ART_TEXT } =
  new Function(src + '; return { artSlotBadge, artShownName, artGalleryCharacter, artPackSummary, artRequestText, ART_TEXT };')();
console.log(JSON.stringify({
  own: artSlotBadge({ own: true }), ph: artSlotBadge({ own: false, placeholder: true }),
  falls: artSlotBadge({ own: false, placeholder: false, shows: 'sprites/bust/joy.giggle.webp' }),
  name: artShownName('sprites/bust/grok/neutral.png'),
  drew: artGalleryCharacter(['docs/x.md', 'data/workspace/characters/char_01m376xaa1e0fsdhm3e3kbnybd/gallery/nono-desk-01.png']),
  none: artGalleryCharacter(['data/workspace/characters/char_01ab/card.json']),
  pack: artPackSummary({ placed: ['joy', 'smug'], skipped: [{ file: 'readme.txt', why: 'not a picture' }] }),
  packAll: artPackSummary({ placed: ['joy'], skipped: [] }),
  askEmo: artRequestText('노노', 'char_x', 'emotion', 'bust', [{ name: 'neutral', own: true }, { name: 'joy', own: false }, { name: 'fear', own: false, placeholder: true }]),
  askBg: artRequestText('노노', 'char_x', 'background', 'bust', [{ name: 'main', own: false }]),
  askNone: artRequestText('노노', 'char_x', 'icon', 'bust', [{ name: 'main', own: true }]),
  tabs: [ART_TEXT.gallery, ART_TEXT.icon, ART_TEXT.background, ART_TEXT.emotion].every(Boolean),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ArtManagerPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", i18n_prelude() + HARNESS, str(STATIC / "app-art.js")], capture_output=True, text=True, timeout=20)
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

    def test_a_pack_result_says_what_landed_and_what_was_skipped_why(self):
        self.assertEqual(self.o["pack"], "표정 2개 반영 · 건너뜀 1개: readme.txt (not a picture)")
        self.assertEqual(self.o["packAll"], "표정 1개 반영")

    def test_the_request_names_what_is_missing_and_the_spec(self):
        emo = self.o["askEmo"]
        self.assertIn("joy, fear", emo)
        self.assertNotIn("neutral", emo.split(":")[1].split(".")[0], "a slot with its own picture is not asked for")
        self.assertIn("character-art", emo)
        self.assertIn("bust", emo)   # the request goes to the agent: English (I18N_v1)
        self.assertIn("char_x", emo)
        self.assertIn("no people", self.o["askBg"])
        self.assertEqual(self.o["askNone"], "", "nothing missing, nothing to ask")
        self.assertIn(": 기본.", self.o["askBg"], "the main slot is asked for by its shown name")


class Wiring(unittest.TestCase):
    def test_the_page_loads_it_and_two_places_open_it(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('./app-art.js', page)
        self.assertIn('./art-manager.css', page)
        self.assertLess(page.index("./app-art.js"), page.index("./app.js?"))
        self.assertIn("openArtManager(openCharacterId())", (STATIC / "app-characters.js").read_text(encoding="utf-8"))
        self.assertIn("openArtManager(drewFor, 'gallery')", (STATIC / "app-evolution.js").read_text(encoding="utf-8"))

    def test_the_request_button_is_for_work_sessions_only(self):
        src = (STATIC / "app-art.js").read_text(encoding="utf-8")
        self.assertIn("sessionMode !== 'private'", src)
        self.assertIn("fillComposer(text)", src)


if __name__ == "__main__":
    unittest.main()
