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

    def test_names_fall_back_by_dropping_suffixes(self):
        # ART_NAMES_v1: SillyTavern's joy-1 / joy.giggle naming, read as a chain -- no table
        self.assertEqual(C.name_chain("joy.giggle-2", "neutral"), ["joy.giggle-2", "joy.giggle", "joy", "neutral"])
        self.assertEqual(C.name_chain("../card", "neutral"), ["neutral"])
        joy = self.put("sprites/bust/joy.webp")
        self.assertEqual(C.art_file(self.cid, "sprite", framing="bust", label="joy.giggle", ws=self.ws), (joy, False))
        giggle = self.put("sprites/bust/joy.giggle.webp")
        self.assertEqual(C.art_file(self.cid, "sprite", framing="bust", label="joy.giggle", ws=self.ws), (giggle, False))
        neutral = self.put("sprites/bust/neutral.webp")
        self.assertEqual(C.art_file(self.cid, "sprite", framing="bust", label="sadness", ws=self.ws), (neutral, False))

    def test_several_pictures_of_one_expression_take_turns(self):
        import random
        a, b = self.put("sprites/bust/joy.webp"), self.put("sprites/bust/joy-1.webp")
        seen = {C.art_file(self.cid, "sprite", framing="bust", label="joy", ws=self.ws, rng=random.Random(i))[0]
                for i in range(20)}
        self.assertEqual(seen, {a, b})

    def test_a_brains_folder_comes_first_then_the_shared_one(self):
        shared = self.put("sprites/bust/joy.webp")
        wig = self.put("sprites/bust/grok/neutral.webp")
        self.assertEqual(C.art_file(self.cid, "sprite", provider="grok", framing="bust", label="joy", ws=self.ws),
                         (wig, False), "the wig's own chain first, so a face never switches outfit mid-talk")
        self.assertEqual(C.art_file(self.cid, "sprite", provider="agy", framing="bust", label="joy", ws=self.ws),
                         (shared, False))
        avatar, grok = self.put("avatar.webp"), self.put("avatar/grok.webp")
        self.assertEqual(C.art_file(self.cid, "avatar", provider="grok", ws=self.ws), (grok, False))
        self.assertEqual(C.art_file(self.cid, "avatar", provider="agy", ws=self.ws), (avatar, False))

    def test_a_stage_is_a_place_named_by_suffix(self):
        old = self.put("stage/grok.webp")
        self.assertEqual(C.art_file(self.cid, "stage", provider="grok", ws=self.ws), (old, False), "read-only compat")
        stage = self.put("stage.webp")
        self.assertEqual(C.art_file(self.cid, "stage", provider="grok", ws=self.ws), (stage, False), "a place is not per brain")
        night = self.put("stage.night.webp")
        self.assertEqual(C.art_file(self.cid, "stage", label="night", ws=self.ws), (night, False))
        self.assertEqual(C.art_file(self.cid, "stage", label="rain", ws=self.ws), (stage, False))

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
