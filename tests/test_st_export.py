"""tests/test_st_export.py — SillyTavern PNG export (cgs/E).

The packaged PNG round-trips through tools/st_import.py. Card JSON stays the
Chara V2 object on disk; roster grants are not part of the exported chunk.
"""
import base64
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from tools.st_export import (  # noqa: E402
    card_json_text,
    embed_card_into_png,
    encode_png,
    export_files,
    extract_card_from_png,
    main,
    parse_png_chunks,
)
from tools.st_import import (  # noqa: E402
    create_st_png_bytes,
    extract_st_card,
    import_st_png_bytes,
)


def _chunk(ctype, data):
    crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)


def _with_extra(png, extras):
    """Insert (type, data) chunks immediately before IEND."""
    chunks = parse_png_chunks(png)
    iend = next(i for i, (ctype, _) in enumerate(chunks) if ctype == b"IEND")
    for extra in reversed(extras):
        chunks.insert(iend, extra)
    return encode_png(chunks)


def _ztxt(keyword, text):
    return (b"zTXt", keyword.encode("latin-1") + b"\x00\x00" + zlib.compress(text))


def _itxt(keyword, text):
    # compression flag 0, method 0, empty language and translated keyword
    return (b"iTXt", keyword.encode("latin-1") + b"\x00\x00\x00\x00\x00" + text)


class EmbedCardTest(unittest.TestCase):
    def test_reencode_keeps_a_plain_png(self):
        raw = create_st_png_bytes({"name": "Aria"})
        self.assertEqual(encode_png(parse_png_chunks(raw)), raw)

    def test_chara_lands_before_iend_and_pixels_stay(self):
        raw = create_st_png_bytes({"name": "Old"}, width=2, height=2)
        old_idat = next(data for ctype, data in parse_png_chunks(raw) if ctype == b"IDAT")
        packed = embed_card_into_png(raw, json.dumps({"spec": "chara_card_v2", "data": {"name": "New"}}))
        chunks = parse_png_chunks(packed)
        self.assertEqual(chunks[-2][0], b"tEXt")
        self.assertTrue(chunks[-2][1].startswith(b"chara\x00"))
        self.assertEqual(chunks[-1][0], b"IEND")
        self.assertEqual(next(data for ctype, data in chunks if ctype == b"IDAT"), old_idat)
        keywords = [chunks[i][1].split(b"\x00", 1)[0] for i, (ctype, _) in enumerate(chunks) if ctype == b"tEXt"]
        self.assertEqual(keywords, [b"chara"])

    def test_compressed_ccv3_cannot_hide_the_new_card(self):
        old = base64.b64encode(json.dumps({"data": {"name": "Old"}}).encode("utf-8"))
        raw = _with_extra(create_st_png_bytes({"name": "AlsoOld"}), [
            _ztxt("ccv3", old),
            _itxt("Chara", old),
            (b"tEXt", b"Comment\x00keep-me"),
        ])
        card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": {"name": "노노", "description": "설명"}}
        packed = embed_card_into_png(raw, json.dumps(card, ensure_ascii=False))
        kinds = [(ctype, (data.split(b"\x00", 1)[0] if b"\x00" in data else b""))
                 for ctype, data in parse_png_chunks(packed) if ctype in (b"tEXt", b"zTXt", b"iTXt")]
        self.assertIn((b"tEXt", b"Comment"), kinds)
        self.assertNotIn((b"zTXt", b"ccv3"), [(c, k.lower()) for c, k in kinds])
        self.assertEqual(extract_st_card(packed)["data"]["name"], "노노")
        imported = import_st_png_bytes(packed, ws=Path(tempfile.mkdtemp()), dry_run=True)
        self.assertEqual(imported["data"]["name"], "노노")
        self.assertEqual(imported["data"]["description"], "설명")

    def test_a_broken_chara_chunk_is_skipped(self):
        chunks = [c for c in parse_png_chunks(create_st_png_bytes({"name": "Seed"})) if c[0] != b"tEXt"]
        good = b"chara\x00" + base64.b64encode(json.dumps({"name": "Ok"}).encode("utf-8"))
        iend = next(i for i, (ctype, _) in enumerate(chunks) if ctype == b"IEND")
        chunks.insert(iend, (b"tEXt", good))
        chunks.insert(iend, (b"tEXt", b"chara\x00!!!!"))
        raw = encode_png(chunks)
        self.assertEqual(json.loads(extract_card_from_png(raw))["name"], "Ok")

    def test_missing_iend_and_a_non_png_are_refused(self):
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = _chunk(b"IHDR", b"\x00" * 13)
        with self.assertRaises(ValueError):
            embed_card_into_png(sig + ihdr, "{}")
        with self.assertRaises(ValueError):
            embed_card_into_png(b"not a png", "{}")
        with self.assertRaises(ValueError):
            embed_card_into_png(create_st_png_bytes({"name": "A"}), "")

    def test_roster_grants_are_not_in_the_chunk(self):
        card = {
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": {
                "name": "Nono",
                "extensions": {"chatbot": {"voice": "banmal", "role": "lead", "roles": ["a"],
                                           "tools": ["shell"], "skills": ["x"], "user_title": "coach"}},
            },
        }
        packed = embed_card_into_png(create_st_png_bytes({"name": "x"}), card_json_text(card))
        ours = extract_st_card(packed)["data"]["extensions"]["chatbot"]
        self.assertEqual(ours["voice"], "banmal")
        self.assertEqual(ours["user_title"], "coach")
        for key in ("role", "roles", "tools", "skills"):
            self.assertNotIn(key, ours)


class ExportCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _folder(self):
        folder = self.tmp / "char_x"
        folder.mkdir()
        card = {
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": {"name": "Mika", "first_mes": "안녕", "extensions": {"chatbot": {"voice": "soft", "role": "lead"}}},
        }
        (folder / "card.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        (folder / "avatar_master.png").write_bytes(create_st_png_bytes({"name": "placeholder"}))
        return folder

    def test_dir_round_trip_through_st_import(self):
        out = self.tmp / "mika.png"
        self.assertEqual(main(["--dir", str(self._folder()), "-o", str(out)]), 0)
        got = extract_st_card(out.read_bytes())
        self.assertEqual(got["data"]["name"], "Mika")
        self.assertEqual(got["data"]["first_mes"], "안녕")
        self.assertNotIn("role", got["data"]["extensions"]["chatbot"])
        imported = import_st_png_bytes(out.read_bytes(), ws=self.tmp / "ws", dry_run=True)
        self.assertEqual(imported["spec"], "chara_card_v2")
        self.assertEqual(imported["data"]["name"], "Mika")

    def test_card_and_image_flags_and_overwrite(self):
        folder = self._folder()
        out = self.tmp / "out.png"
        rc = main(["--card", str(folder / "card.json"), "--image", str(folder / "avatar_master.png"),
                   "-o", str(out)])
        self.assertEqual(rc, 0)
        self.assertEqual(main(["--card", str(folder / "card.json"), "--image", str(folder / "avatar_master.png"),
                               "-o", str(out)]), 1)
        self.assertEqual(main(["--card", str(folder / "card.json"), "--image", str(folder / "avatar_master.png"),
                               "-o", str(out), "--force"]), 0)

    def test_missing_master_image_fails(self):
        folder = self._folder()
        (folder / "avatar_master.png").unlink()
        self.assertEqual(main(["--dir", str(folder), "-o", str(self.tmp / "x.png")]), 1)

    def test_export_files_writes_the_same_bytes_the_reader_expects(self):
        folder = self._folder()
        out = export_files(folder / "card.json", folder / "avatar_master.png", self.tmp / "a.png")
        text = extract_card_from_png(out.read_bytes())
        self.assertEqual(json.loads(text)["data"]["name"], "Mika")


if __name__ == "__main__":
    unittest.main()
