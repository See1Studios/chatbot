"""The art manager's server half (art_manager.py, character-art-manager.md am/B): a character's slots by CCv3 kind
with what each shows, its gallery of candidates, putting a gallery picture in a slot (fitted, WebP under the cap,
PNG master beside it, the old one to _old/), taking one out (back to the gallery), and uploads into the gallery.
Nothing is deleted. Runs against a scratch workspace; needs Pillow.
Run: python3 -m unittest tests.test_art_manager  (from services/chatbot)
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import art_manager as A  # noqa: E402
import character_art  # noqa: E402
import characters as C  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def png(size, alpha=False, color=(200, 120, 90)):
    im = Image.new("RGBA" if alpha else "RGB", size, (0, 0, 0, 0) if alpha else color)
    if alpha:
        im.paste(Image.new("RGBA", (size[0] // 2, size[1] // 2), color + (255,)), (size[0] // 4, size[1] // 2))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


@unittest.skipUnless(Image, "Pillow not installed")
class ArtManager(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("A", description="a"), self.ws)
        self.base = C.card_path(self.cid, self.ws).parent
        self.patch = mock.patch.object(C, "_default_ws", return_value=self.ws)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.ws, ignore_errors=True)

    def gallery(self, name, data):
        (self.base / "gallery").mkdir(parents=True, exist_ok=True)
        (self.base / "gallery" / name).write_bytes(data)

    def test_an_empty_character_lists_every_slot_as_placeholder(self):
        L = A.listing(self.cid, self.ws)
        self.assertEqual([s["name"] for s in L["emotion"]["bust"]], list(A.EMOTION_SLOTS))
        self.assertTrue(all(s["placeholder"] and not s["own"] for s in L["emotion"]["bust"] + L["icon"] + L["background"]))
        self.assertEqual(L["gallery"], [])

    def test_a_gallery_picture_becomes_the_icon_fitted_under_the_cap(self):
        self.gallery("wide.png", png((900, 600)))
        slot = A.assign(self.cid, "wide.png", "icon", ws=self.ws)
        self.assertTrue(slot["own"] and not slot["placeholder"])
        out = self.base / "avatar.webp"
        with Image.open(out) as im:
            self.assertEqual(im.size, C.ART_SIZE)
        self.assertLessEqual(out.stat().st_size, C.ART_MAX_BYTES)
        self.assertTrue((self.base / "avatar.png").is_file(), "the master is kept")
        self.assertTrue((self.base / "gallery" / "wide.png").is_file(), "the candidate stays in the gallery")

    def test_an_expression_must_be_transparent_and_lands_on_its_canvas(self):
        self.gallery("flat.png", png((500, 800)))
        with self.assertRaises(A.ArtError):
            A.assign(self.cid, "flat.png", "emotion", "joy", "bust", ws=self.ws)
        self.gallery("cut.png", png((500, 800), alpha=True))
        A.assign(self.cid, "cut.png", "emotion", "joy.giggle", "bust", ws=self.ws)
        with Image.open(self.base / "sprites" / "bust" / "joy.giggle.webp") as im:
            self.assertEqual(im.size, C.FRAMINGS["bust"][0])
            self.assertEqual(im.getchannel("A").getbbox()[3], im.height, "the figure stands on the bottom edge")
        slots = {s["name"]: s for s in A.listing(self.cid, self.ws)["emotion"]["bust"]}
        self.assertTrue(slots["joy.giggle"]["own"])
        self.assertFalse(slots["joy"]["own"])
        self.assertEqual(slots["joy"]["shows"], "sprites/bust/joy.giggle.webp", "joy's only picture is a joy variant")
        self.assertTrue(slots["sadness"]["placeholder"], "no neutral yet, so an unrelated expression is the placeholder")

    def test_replacing_keeps_the_old_one_and_removing_returns_it_to_the_gallery(self):
        self.gallery("a.png", png((600, 600), color=(10, 20, 30)))
        self.gallery("b.png", png((600, 600), color=(200, 20, 30)))
        A.assign(self.cid, "a.png", "background", ws=self.ws)
        A.assign(self.cid, "b.png", "background", ws=self.ws)
        old = sorted(p.name for p in (self.base / "_old").iterdir())
        self.assertTrue(any(n.endswith("stage.webp") for n in old) and any(n.endswith("stage.png") for n in old), old)
        A.remove(self.cid, "background", ws=self.ws)
        self.assertFalse((self.base / "stage.webp").exists())
        self.assertTrue(any(p.name.endswith("-stage.webp") for p in (self.base / "gallery").iterdir()))
        self.assertEqual(C.art_file(self.cid, "stage", ws=self.ws)[1], True, "an empty slot is the placeholder again")

    def test_uploads_go_to_the_gallery_and_only_pictures_get_in(self):
        f = A.upload(self.cid, "내 그림 (1).png", png((300, 300)), ws=self.ws)
        self.assertTrue((self.base / "gallery" / f["file"]).is_file())
        self.assertRegex(f["file"], r"^[A-Za-z0-9_-]+\.png$")
        again = A.upload(self.cid, "내 그림 (1).png", png((300, 300)), ws=self.ws)
        self.assertNotEqual(again["file"], f["file"], "a second upload never overwrites")
        for bad in (b"", b"not an image", b"GIF89a" + b"\0" * 20):
            with self.assertRaises(A.ArtError):
                A.upload(self.cid, "x.png", bad, ws=self.ws)

    def test_names_that_cannot_be_slots_are_refused(self):
        self.gallery("a.png", png((100, 100)))
        for args in (("emotion", "../x", "bust"), ("emotion", "joy", "side"), ("nope", "", "bust")):
            with self.assertRaises(A.ArtError):
                A.assign(self.cid, "a.png", *args, ws=self.ws)
        with self.assertRaises(A.ArtError):
            A.assign(self.cid, "../card.json", "icon", ws=self.ws)
        self.assertIsNone(A.gallery_file(self.cid, "..%2Fcard.json", self.ws))

    def test_routes(self):
        self.gallery("a.png", png((200, 200)))
        code, body = A.handle_get("/api/characters/%s/art" % self.cid)
        self.assertEqual((code, body["gallery"][0]["file"]), (200, "a.png"))
        code, body = A.handle_post("/api/characters/%s/art/assign" % self.cid, {"from": "a.png", "kind": "icon"})
        self.assertEqual((code, body["slot"]["own"]), (200, True))
        code, body = A.handle_post("/api/characters/%s/art/assign" % self.cid, {"from": "zz.png", "kind": "icon"})
        self.assertEqual(code, 400)
        pic = character_art.handle("/api/characters/%s/gallery/a.png" % self.cid, {})
        self.assertEqual((pic[0], pic[2]), (200, "image/png"))
        for p in ("/api/characters/%s/art/x" % self.cid, "/api/characters/nope/art", "/api/sessions/x/art"):
            self.assertIsNone(A.handle_get(p), p)
            self.assertIsNone(A.handle_post(p, {}), p)


if __name__ == "__main__":
    unittest.main()
