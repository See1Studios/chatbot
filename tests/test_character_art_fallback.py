"""ART_PLACEHOLDER_v1: every character art kind resolves to a file -- the character's own, else the engine
placeholder in static/placeholders/ -- so the page never shows a broken image and never 404s on art (the sprite
requests 404ed all day on 2026-09-28). The placeholders follow the same format as real art (characters.py
CHARACTER_ART_v1), and every kind and framing has one.
Run: python3 -m unittest tests.test_character_art_fallback  (from services/chatbot)
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import character_art  # noqa: E402
import characters as C  # noqa: E402


class Placeholders(unittest.TestCase):
    def test_every_kind_and_framing_has_a_placeholder_in_the_art_format(self):
        from PIL import Image
        want = {"avatar": (C.ART_SIZE, C.ART_MAX_BYTES, "RGB"), "stage": (C.STAGE_SIZE, C.STAGE_MAX_BYTES, "RGB")}
        for f, (canvas, cap, _) in C.FRAMINGS.items():
            want["sprite:" + f] = (canvas, cap, "RGBA")                 # sprites are transparent
        self.assertEqual(set(C.PLACEHOLDERS), set(want), "a kind or framing without a placeholder")
        for key, (size, cap, mode) in want.items():
            p = C.PLACEHOLDER_DIR / C.PLACEHOLDERS[key]
            self.assertTrue(p.is_file(), p)
            self.assertLessEqual(p.stat().st_size, cap, p)
            with Image.open(p) as im:
                self.assertEqual((im.size, im.mode), (size, mode), p)


class Resolve(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("A", description="a"), self.ws)
        self.base = C.card_path(self.cid, self.ws).parent

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def put(self, rel):
        p = self.base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(rel.encode())
        return p

    def test_a_character_with_nothing_gets_every_placeholder(self):
        for kind, kw, name in (("avatar", {}, "avatar.webp"), ("stage", {}, "stage.webp"),
                               ("sprite", {"framing": "bust"}, "sprite-bust.webp"),
                               ("sprite", {"framing": "full", "label": "joy"}, "sprite-full.webp"),
                               ("sprite", {"framing": "nope"}, "sprite-full.webp")):
            path, ph = C.art_file(self.cid, kind, ws=self.ws, **kw)
            self.assertEqual((path, ph), (C.PLACEHOLDER_DIR / name, True), (kind, kw))

    def test_sprites_fall_back_label_then_neutral_then_the_other_framing(self):
        neutral = self.put("sprites/bust/neutral.webp")
        self.assertEqual(C.art_file(self.cid, "sprite", framing="full", label="joy", ws=self.ws), (neutral, False))
        joy = self.put("sprites/full/joy.webp")
        self.assertEqual(C.art_file(self.cid, "sprite", framing="full", label="joy", ws=self.ws), (joy, False))
        self.assertEqual(C.art_file(self.cid, "sprite", framing="full", label="default", ws=self.ws), (neutral, False))
        self.assertTrue(C.art_file(self.cid, "sprite", label="../../card", ws=self.ws)[0].is_file())

    def test_the_sprite_listing_names_what_exists(self):
        self.assertEqual(C.sprite_map(self.cid, "full", self.ws), {"framing": "full", "sprites": {}})
        self.put("sprites/bust/neutral.webp")
        self.put("sprites/bust/joy.webp")
        self.assertEqual(C.sprite_map(self.cid, "full", self.ws),
                         {"framing": "bust", "sprites": {"joy": "bust/joy.webp", "neutral": "bust/neutral.webp"}})


class Routes(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("A", description="a"), self.ws)
        self.patch = mock.patch.object(C, "_default_ws", return_value=self.ws)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.ws, ignore_errors=True)

    def get(self, rel, **q):
        return character_art.handle("/api/characters/%s/%s" % (self.cid, rel), {k: [v] for k, v in q.items()})

    def test_known_art_never_404s(self):
        for rel in ("avatar", "stage", "sprites/default.webp", "sprites/joy.webp", "sprites/bust/joy.webp"):
            code, body, ctype, cache = self.get(rel, provider="agy")
            self.assertEqual((code, ctype), (200, "image/webp"), rel)
            self.assertTrue(body)
            self.assertIn("max-age=30", cache)                          # a placeholder is not cached for long

    def test_the_listing_is_json(self):
        code, body, ctype, _ = self.get("sprites")
        self.assertEqual((code, json.loads(body)), (200, {"framing": "full", "sprites": {}}))

    def test_other_paths_are_not_ours(self):
        for path in ("/api/characters/%s/card.json" % self.cid, "/api/characters/../x/avatar", "/api/characters",
                     "/api/characters/%s/sprites/a/b/c.webp" % self.cid, "/api/sessions/x"):
            self.assertIsNone(character_art.handle(path, {}), path)


if __name__ == "__main__":
    unittest.main()
