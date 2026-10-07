"""characters.py: TypeIDs, Character Card V2 files, lookup by role, migration from experts/ (CHARACTERS_v1).
Run: python3 -m unittest tests.test_characters  (from services/chatbot)
"""
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
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


class PrivateMemoryTest(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("P", "pd"), self.ws)

    def test_kept_apart_short_unique_and_free_of_secrets(self):
        self.assertEqual(C.read_private_memory(self.cid, self.ws), "")
        self.assertEqual(C.remember_private(self.cid, ["좋아하는 차는 보리차", "my password is x"], "2026-01-01", self.ws), 1)
        self.assertEqual(C.remember_private(self.cid, ["좋아하는 차는 보리차"], "2026-01-02", self.ws), 0)
        text = C.read_private_memory(self.cid, self.ws)
        self.assertIn("- [2026-01-01] 좋아하는 차는 보리차", text)
        self.assertNotIn("password", text)
        for i in range(200):
            C.remember_private(self.cid, ["moment %d with padding words" % i], "2026-01-03", self.ws)
        self.assertLessEqual(len(C.private_memory_path(self.cid, self.ws).read_bytes()), C.PRIVATE_MEMORY_CAP)
        self.assertFalse((self.ws / "characters" / self.cid / "memory.md").exists())   # work memory untouched

    def test_the_private_turns_since_the_last_digest(self):
        history = [{"role": "user", "text": "old", "ts": 10}, {"role": "assistant", "text": "old reply", "ts": 11},
                   {"role": "user", "text": "오늘 좀 피곤해", "ts": 20}, {"role": "assistant", "text": "err", "ts": 21,
                                                                       "notice": "error"},
                   {"role": "assistant", "text": "푹 쉬어", "ts": 22}, {"role": "system", "text": "x", "ts": 23}]
        seg = C.private_segment(history, since=11)
        self.assertEqual([h["text"] for h in seg], ["오늘 좀 피곤해", "푹 쉬어"])
        self.assertEqual(len(C.private_segment(history)), 4)
        prompt = C.private_digest_prompt(seg, "U", "P")
        self.assertIn("U: 오늘 좀 피곤해", prompt)
        self.assertNotIn("old", prompt)
        self.assertEqual(C.parse_memory_lines("- a\n- b\nnoise\n- c\n- d"), ["a", "b", "c"])
        self.assertEqual(C.parse_memory_lines("NONE"), [])
        self.assertEqual(C.private_segment(history, since=99), [])

if __name__ == "__main__":
    unittest.main()
