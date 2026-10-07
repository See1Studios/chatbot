"""Relationship slots stay out of work and out of the static bundle hash."""
import shutil
import tempfile
import unittest
from pathlib import Path

import characters as C
import instructions as I
import memory_relationship as M


class RelationshipMemory(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        (self.ws / "memory").mkdir()
        (self.ws / "AGENTS.md").write_text("charter\n\n## Scope\n\nkeep\n", encoding="utf-8")
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("P", "pd", description="persona body"), self.ws)
        C.save_team({"default": self.cid, "members": {self.cid: []}}, self.ws)
        self.saved = (I.WORKSPACE, I.MEMORY_FILE)
        I.WORKSPACE, I.MEMORY_FILE = self.ws, self.ws / "memory" / "MEMORY.md"

    def tearDown(self):
        I.WORKSPACE, I.MEMORY_FILE = self.saved
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_explicit_tags_are_stored_and_not_in_work(self):
        added = M.remember_slots(self.cid, [
            "promise: next time the roof",
            "pref: barley tea",
            "taboo: do not mention the office",
            "progress: yesterday we stopped at the stairs",
            "my password is x",
            "just a moment",
        ], self.ws)
        self.assertEqual(added, 4)
        self.assertNotIn("password", M.path(self.cid, self.ws).read_text(encoding="utf-8"))
        text = I.build_instruction_bundle(mode="private", character=self.cid)["text"]
        self.assertIn("[Relationship]", text)
        self.assertIn("Promises: next time the roof", text)
        self.assertIn("Preferences: barley tea", text)
        self.assertIn("Taboos: do not mention the office", text)
        self.assertIn("Progress: yesterday we stopped at the stairs", text)
        self.assertNotIn("just a moment", text)
        work = I.build_instruction_bundle(character=self.cid)["text"]
        self.assertNotIn("next time the roof", work)
        self.assertNotIn("[Relationship]", work)

    def test_slots_are_dynamic_and_private_bullets_stay_compact(self):
        C.remember_private(self.cid, ["pref: likes tea", "walked home together"], "2026-01-01", self.ws)   # NO_GUESS_SLOT_v1: by tag only
        before = I.build_instruction_bundle(mode="private", character=self.cid)
        M.remember_slots(self.cid, ["promise: bring the scarf"], self.ws)
        after = I.build_instruction_bundle(mode="private", character=self.cid)
        self.assertEqual(before["hash"], after["hash"])
        self.assertIn("likes tea", after["text"])
        self.assertIn("Preferences:", after["text"])
        self.assertIn("walked home together", after["text"])
        self.assertIn("Continuity:", after["text"])
        self.assertEqual(after["text"].count("likes tea"), 1)
        self.assertIn("bring the scarf", after["text"])

    def test_another_character_does_not_inherit_slots(self):
        M.remember_slots(self.cid, ["promise: only with P"], self.ws)
        other = C.new_id()
        C.save(other, C.new_card("Other", "staff", description="other body"), self.ws)
        text = I.build_instruction_bundle(mode="private", character=other)["text"]
        self.assertNotIn("only with P", text)

    def test_the_digest_asks_for_slot_tags(self):
        prompt = C.private_digest_prompt(
            [{"role": "user", "text": "hi", "ts": 1}], "U", "P")
        self.assertIn("promise:", prompt)
        self.assertIn("taboo:", prompt)


if __name__ == "__main__":
    unittest.main()
