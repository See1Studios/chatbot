"""Tests for tools/st_import.py (SillyTavern PNG card parser & importer).

Run: python3 -m unittest tests.test_st_import
"""
import base64
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import characters  # noqa: E402
from tools.st_import import (  # noqa: E402
    convert_st_card,
    create_st_png_bytes,
    extract_chara_raw,
    extract_st_card,
    import_st_path,
    import_st_png_bytes,
    main,
    make_slug,
    new_character_id,
)

try:
    from PIL import Image
except ImportError:
    Image = None


class StImportTest(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def sample_v2_flat_card(self):
        return {
            "name": "Aria",
            "description": "A brilliant network researcher.",
            "personality": "Curious, witty, and sharp-tongued.",
            "scenario": "A cyberpunk laboratory workstation.",
            "first_mes": "System online. What do you need?",
            "mes_example": "<START>\n{{user}}: Help me.\n{{char}}: Fine.",
            "creator_notes": "Character concept notes.",
            "system_prompt": "You are Aria, an autonomous agent.",
            "post_history_instructions": "Keep answers concise.",
            "alternate_greetings": ["Greetings, user.", "Back so soon?"],
            "tags": ["sci-fi", "assistant"],
            "creator": "Tester",
            "character_version": "1.0.0",
            "extensions": {"depth_prompt": {"prompt": "Be deep"}},
        }

    def sample_v3_card(self):
        return {
            "spec": "chara_card_v3",
            "spec_version": "3.0",
            "data": {
                "name": "Elena",
                "description": "Strategic operations specialist.",
                "personality": "Calm and calculated.",
                "scenario": "Operations briefing room.",
                "first_mes": "All systems nominal.",
                "mes_example": "<START>\n{{user}}: Status?\n{{char}}: All green.",
                "creator_notes": "V3 test card.",
                "system_prompt": "Act as operations lead.",
                "post_history_instructions": "Focus on clarity.",
                "alternate_greetings": ["Ready when you are."],
                "tags": ["tactical", "operations"],
                "creator": "Studio Lead",
                "character_version": "2.1",
                "extensions": {"voice": {"pitch": 1.1}},
            },
        }

    # ------------------------------------------------------------------ PNG Chunk Parser

    def test_extract_valid_chara_chunk(self):
        card = self.sample_v2_flat_card()
        png_bytes = create_st_png_bytes(card)
        raw_bytes = extract_chara_raw(png_bytes)
        self.assertTrue(len(raw_bytes) > 0)
        parsed = extract_st_card(png_bytes)
        self.assertEqual(parsed["name"], "Aria")
        self.assertEqual(parsed["creator"], "Tester")

    def test_extract_invalid_png_signature(self):
        with self.assertRaises(ValueError) as ctx:
            extract_chara_raw(b"not a valid png file at all")
        self.assertIn("signature", str(ctx.exception).lower())

    def test_extract_png_without_chara_chunk(self):
        # Build 1x1 PNG without chara chunk
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
        raw_data = zlib.compress(b"\x00\xff\xff\xff")
        idat = struct.pack(">I", len(raw_data)) + b"IDAT" + raw_data + struct.pack(">I", zlib.crc32(b"IDAT" + raw_data))
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
        empty_png = sig + ihdr + idat + iend

        with self.assertRaises(ValueError) as ctx:
            extract_chara_raw(empty_png)
        self.assertIn("no 'ccv3' or 'chara' text chunk", str(ctx.exception).lower())

    def test_extract_corrupted_json_payload(self):
        # Create a PNG with chara chunk containing invalid base64/JSON
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
        payload = b"not-valid-base64-or-json@@@@"
        text_data = b"chara\x00" + payload
        text_chunk = struct.pack(">I", len(text_data)) + b"tEXt" + text_data + struct.pack(">I", zlib.crc32(b"tEXt" + text_data))
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
        corrupt_png = sig + ihdr + text_chunk + iend

        with self.assertRaises(ValueError) as ctx:
            extract_st_card(corrupt_png)
        self.assertIn("failed to decode", str(ctx.exception).lower())

    # ------------------------------------------------------------------ Card Conversion

    def test_convert_v2_flat_to_see1(self):
        raw = self.sample_v2_flat_card()
        see1 = convert_st_card(raw)

        self.assertEqual(see1["spec"], "chara_card_v2")
        self.assertEqual(see1["spec_version"], "2.0")
        data = see1["data"]
        self.assertEqual(data["name"], "Aria")
        self.assertEqual(data["description"], "A brilliant network researcher.")
        self.assertEqual(data["personality"], "Curious, witty, and sharp-tongued.")
        self.assertEqual(data["alternate_greetings"], ["Greetings, user.", "Back so soon?"])
        self.assertEqual(data["tags"], ["sci-fi", "assistant"])
        self.assertEqual(data["creator"], "Tester")
        self.assertEqual(data["extensions"], {"depth_prompt": {"prompt": "Be deep"}})

    def test_convert_v3_to_see1(self):
        raw = self.sample_v3_card()
        see1 = convert_st_card(raw)

        self.assertEqual(see1["spec"], "chara_card_v2")
        self.assertEqual(see1["spec_version"], "2.0")
        data = see1["data"]
        self.assertEqual(data["name"], "Elena")
        self.assertEqual(data["scenario"], "Operations briefing room.")
        self.assertEqual(data["first_mes"], "All systems nominal.")
        self.assertEqual(data["tags"], ["tactical", "operations"])
        self.assertEqual(data["extensions"], {"voice": {"pitch": 1.1}})

    def test_convert_fallbacks_and_empty_fields(self):
        minimal = {
            "name": "Cipher",
            "creatorcomment": "Using legacy creator comment",
            "tags": "cyber, stealth, scout",
            "alternate_greetings": "Single greeting line",
        }
        see1 = convert_st_card(minimal)
        data = see1["data"]
        self.assertEqual(data["name"], "Cipher")
        self.assertEqual(data["creator_notes"], "Using legacy creator comment")
        self.assertEqual(data["tags"], ["cyber", "stealth", "scout"])
        self.assertEqual(data["alternate_greetings"], ["Single greeting line"])
        self.assertEqual(data["description"], "")
        self.assertEqual(data["extensions"], {})

    # ------------------------------------------------------------------ Directory & ID

    def test_slug_generation(self):
        self.assertEqual(make_slug("Cipher Fox"), "cipher-fox")
        self.assertEqual(make_slug("Agent_007 - Alpha!"), "agent-007-alpha")
        self.assertEqual(make_slug(""), "character")
        self.assertEqual(make_slug("   "), "character")

    def test_new_character_id_format(self):
        cid = new_character_id()
        self.assertTrue(cid.startswith("char_"))
        self.assertTrue(characters.ID_RE.match(cid) is not None)

    # ------------------------------------------------------------------ End-to-End Import

    def test_import_st_png_bytes_end_to_end(self):
        card = self.sample_v2_flat_card()
        png_bytes = create_st_png_bytes(card)

        res = import_st_png_bytes(png_bytes, ws=self.ws)
        cid = res["id"]
        self.assertTrue(cid.startswith("char_"))
        self.assertEqual(res["name"], "Aria")
        self.assertEqual(res["slug"], "aria")

        char_dir = self.ws / "characters" / cid
        self.assertTrue(char_dir.is_dir())

        # card.json
        card_file = char_dir / "card.json"
        self.assertTrue(card_file.is_file())
        loaded = characters.load(cid, ws=self.ws)
        self.assertEqual(characters.name(loaded), "Aria")

        # avatar_master.png
        master_file = char_dir / "avatar_master.png"
        self.assertTrue(master_file.is_file())
        self.assertEqual(master_file.read_bytes(), png_bytes)

        # avatar.webp
        webp_file = char_dir / "avatar.webp"
        self.assertTrue(webp_file.is_file())
        if Image:
            with Image.open(webp_file) as im:
                self.assertEqual(im.size, (512, 512))

        # visual.md
        vis_file = char_dir / "visual.md"
        self.assertTrue(vis_file.is_file())
        vis_text = vis_file.read_text(encoding="utf-8")
        self.assertIn("# Aria visual lock sheet", vis_text)
        self.assertIn("Reference `avatar_master.png`", vis_text)

        # check_art format verification
        art_problems = characters.check_art(cid, providers=["agy"], ws=self.ws)
        self.assertEqual(art_problems, [])

    def test_import_st_png_bytes_dry_run(self):
        card = self.sample_v3_card()
        png_bytes = create_st_png_bytes(card)

        res = import_st_png_bytes(png_bytes, ws=self.ws, dry_run=True)
        self.assertEqual(res["name"], "Elena")
        self.assertEqual(res["slug"], "elena")

        char_dir = Path(res["dir"])
        self.assertFalse(char_dir.exists())

    # ------------------------------------------------------------------ CLI

    def test_cli_single_file(self):
        card = self.sample_v2_flat_card()
        card["name"] = "Valkyrie"
        png_bytes = create_st_png_bytes(card)
        file_path = self.ws / "valkyrie.png"
        file_path.write_bytes(png_bytes)

        ret = main([str(file_path), "--workspace", str(self.ws)])
        self.assertEqual(ret, 0)

        imported = characters.listing(self.ws)
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["name"], "Valkyrie")

    def test_cli_directory_import(self):
        cards_dir = self.ws / "cards_source"
        cards_dir.mkdir(parents=True, exist_ok=True)

        for name in ("Zephyr", "Apex"):
            card = self.sample_v2_flat_card()
            card["name"] = name
            (cards_dir / f"{name.lower()}.png").write_bytes(create_st_png_bytes(card))

        ret = main([str(cards_dir), "--workspace", str(self.ws)])
        self.assertEqual(ret, 0)

        imported = characters.listing(self.ws)
        self.assertEqual(len(imported), 2)
        names = {c["name"] for c in imported}
        self.assertEqual(names, {"Zephyr", "Apex"})

    def test_cli_dry_run(self):
        card = self.sample_v2_flat_card()
        card["name"] = "Ghost"
        png_bytes = create_st_png_bytes(card)
        file_path = self.ws / "ghost.png"
        file_path.write_bytes(png_bytes)

        ret = main([str(file_path), "--dry-run", "--workspace", str(self.ws)])
        self.assertEqual(ret, 0)

        imported = characters.listing(self.ws)
        self.assertEqual(len(imported), 0)



def _png_with(chunks):
    """A 1x1 PNG carrying the given (keyword, card dict) tEXt chunks, base64 like SillyTavern writes them."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    out = sig + struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    for keyword, card in chunks:
        text = keyword + b"\x00" + base64.b64encode(json.dumps(card, ensure_ascii=False).encode("utf-8"))
        out += struct.pack(">I", len(text)) + b"tEXt" + text + struct.pack(">I", zlib.crc32(b"tEXt" + text))
    raw = zlib.compress(b"\x00\xff\xff\xff")
    out += struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", zlib.crc32(b"IDAT" + raw))
    return out + struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))


class CardV3AndLorebook(unittest.TestCase):
    """sp/B (docs/plans/setting-pack.md §2): V3 PNGs are read, and a card's lorebook survives the import."""

    BOOK = {"name": "Shrine", "scan_depth": 4, "extensions": {"x": 1},
            "entries": [{"keys": ["shrine"], "content": "The shrine at dusk.", "enabled": True, "insertion_order": 5}]}

    def v3(self, name="Miko", **extra):
        data = {"name": name, "description": "d", "character_book": self.BOOK, "nickname": "Yae",
                "group_only_greetings": ["hi all"], "creation_date": 1700000000}
        data.update(extra)
        return {"spec": "chara_card_v3", "spec_version": "3.0", "data": data}

    def test_a_v3_only_png_is_read_and_v3_wins_over_the_v2_backfill(self):
        from tools.st_import import extract_st_card
        self.assertEqual(extract_st_card(_png_with([(b"ccv3", self.v3())]))["data"]["name"], "Miko")
        both = _png_with([(b"chara", {"spec": "chara_card_v2", "data": {"name": "Old"}}), (b"ccv3", self.v3())])
        self.assertEqual(extract_st_card(both)["data"]["name"], "Miko")

    def test_the_cards_lorebook_lands_where_the_engine_reads_it(self):
        from tools.st_import import import_st_png_bytes
        ws = Path(tempfile.mkdtemp())
        res = import_st_png_bytes(_png_with([(b"ccv3", self.v3())]), ws=ws)
        saved = json.loads((ws / "characters" / res["id"] / "lorebook.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, self.BOOK)                                  # as it came: book-level fields kept
        lb = characters.load_lorebook(res["id"], ws)
        self.assertEqual(lb["entries"][0]["keys"], ["shrine"])

    def test_v3_fields_a_v2_card_cannot_hold_are_kept_in_extensions(self):
        from tools.st_import import convert_st_card
        card = convert_st_card(self.v3())
        kept = card["data"]["extensions"]["chara_card_v3"]
        self.assertEqual((kept["nickname"], kept["group_only_greetings"]), ("Yae", ["hi all"]))
        self.assertEqual(card["data"]["character_book"], self.BOOK)

    def test_a_card_without_a_lorebook_writes_none(self):
        from tools.st_import import import_st_png_bytes
        ws = Path(tempfile.mkdtemp())
        card = self.v3()
        del card["data"]["character_book"]
        res = import_st_png_bytes(_png_with([(b"chara", card)]), ws=ws)
        self.assertFalse((ws / "characters" / res["id"] / "lorebook.json").exists())


if __name__ == "__main__":
    unittest.main()
