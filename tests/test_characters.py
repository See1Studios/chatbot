"""characters.py: TypeIDs, Character Card V2 files, lookup by role, migration from experts/ (CHARACTERS_v1).
Run: python3 -m unittest tests.test_characters  (from services/chatbot)
"""
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402


class TypeIdTest(unittest.TestCase):
    def test_the_spec_vectors(self):
        # https://github.com/jetify-com/typeid/blob/main/spec/valid.yml
        self.assertEqual(C.encode(0), "00000000000000000000000000")
        self.assertEqual(C.encode(uuid.UUID("0110c853-1d09-52d8-d73e-1194e95b5f19").int), "0123456789abcdefghjkmnpqrs")
        self.assertEqual(C.encode(uuid.UUID("01890a5d-ac96-774b-bcce-b302099a8057").int), "01h455vb4pex5vsknk084sn02q")

    def test_new_ids_are_uuid7_and_sort_by_time(self):
        a, b = C.new_id(now_ms=1_700_000_000_000), C.new_id(now_ms=1_700_000_000_001)
        self.assertTrue(C.ID_RE.match(a) and C.ID_RE.match(b))
        self.assertLess(a, b)
        u = uuid.UUID(int=C.uuid7(now_ms=1_700_000_000_000))
        self.assertEqual((u.version, u.variant), (7, uuid.RFC_4122))


class CardTest(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())

    def test_save_load_list_and_find_by_role(self):
        cid = C.new_id()
        C.save(cid, C.new_card("루루", "staff", "a staff member", "curt",
                               display={"title": "막내 스태프"}, brains={"work": [{"provider": "agy"}]}), self.ws)
        (self.ws / "characters" / "junk").mkdir()                     # not a character id: ignored
        [c] = C.listing(self.ws)
        self.assertEqual((c["id"], c["name"], c["role"]), (cid, "루루", "staff"))
        self.assertEqual(C.by_role("staff", self.ws), cid)
        self.assertEqual(C.resolve(cid, self.ws), cid)
        self.assertEqual(C.resolve("staff", self.ws), cid)
        self.assertIsNone(C.resolve("pd", self.ws))
        card = C.load(cid, self.ws)
        self.assertEqual(card["spec"], "chara_card_v2")
        self.assertEqual(C.brains(card), [{"provider": "agy"}])
        self.assertIn("Voice: curt", C.work_text(card))

    def test_bad_ids_and_foreign_cards(self):
        for bad in ("../x", "char_", "char_8" + "0" * 25, "user_" + "0" * 26):
            with self.assertRaises(ValueError):
                C.card_path(bad, self.ws)
        cid = C.new_id()
        C.card_path(cid, self.ws).parent.mkdir(parents=True)
        C.card_path(cid, self.ws).write_text(json.dumps({"spec": "chara_card_v3", "data": {}}))
        self.assertEqual(C.listing(self.ws), [])
        self.assertEqual(C.ext({"data": {"extensions": {}}}), {})     # a card from elsewhere has no work side

    def test_experts_move_to_character_folders(self):
        d = self.ws / "experts" / "staff"
        d.mkdir(parents=True)
        (d / "expert.md").write_text("---\npersona: 루루\ntitle: 막내 스태프\n---\n# body\nworks hard\n")
        (d / "brain.json").write_text(json.dumps({"chain": [{"provider": "agy", "model": "m"}]}))
        (d / "memory.md").write_text("# Memory\n- [2026-01-01] x\n")
        [cid] = C.migrate_experts(self.ws)
        card = C.load(cid, self.ws)
        self.assertEqual((card["data"]["name"], C.ext(card)["role"], C.ext(card)["display"]["title"]),
                         ("루루", "staff", "막내 스태프"))
        self.assertIn("works hard", card["data"]["description"])
        self.assertEqual(C.brains(card)[0]["model"], "m")
        self.assertIn("- [2026-01-01] x", C.memory_path(cid, self.ws).read_text())
        self.assertFalse(d.exists())
        self.assertEqual(C.migrate_experts(self.ws), [])               # nothing left to move


if __name__ == "__main__":
    unittest.main()
