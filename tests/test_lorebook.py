"""Unit tests for the SillyTavern-compatible lorebook (World Info) engine.

Tests:
- characters.py: lorebook_path, normalize_lorebook, load_lorebook, save_lorebook
- instructions.py: match_lorebook_entries, lorebook_context, build_instruction_bundle injection

Run:
    python3 -m unittest tests.test_lorebook
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import characters as C  # noqa: E402
import instructions as I  # noqa: E402


class LorebookTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "workspace"
        self.ws.mkdir(parents=True, exist_ok=True)
        (self.ws / "AGENTS.md").write_text("# Charter\nCHARTER-MARK", encoding="utf-8")

        self.cid = C.new_id()
        card = C.new_card("Alice", description="A wandering archivist.")
        C.save(self.cid, card, self.ws)
        C.save_team({"default": self.cid, "members": {self.cid: []}}, self.ws)

        self._orig_ws = I.WORKSPACE
        I.WORKSPACE = self.ws

    def tearDown(self):
        I.WORKSPACE = self._orig_ws


class LoadLorebookTests(LorebookTestCase):
    def test_load_lorebook_missing_returns_none(self):
        self.assertIsNone(C.load_lorebook(self.cid, self.ws))
        self.assertIsNone(C.load_lorebook("char_00000000000000000000000000", self.ws))
        self.assertIsNone(C.load_lorebook("", self.ws))
        self.assertIsNone(C.load_lorebook("invalid_id", self.ws))

    def test_load_lorebook_canonical_format(self):
        payload = {
            "name": "Eldoria World Info",
            "entries": [
                {
                    "id": 1,
                    "keys": ["dragon", "drake"],
                    "content": "Dragons are powerful fire-breathing beasts.",
                    "enabled": True,
                    "priority": 20,
                    "position": "after_char",
                },
                {
                    "id": 2,
                    "keys": ["kingdom"],
                    "content": "Eldoria is an ancient realm.",
                    "enabled": False,
                    "priority": 10,
                    "position": "before_char",
                },
            ],
        }
        C.save_lorebook(self.cid, payload, self.ws)
        loaded = C.load_lorebook(self.cid, self.ws)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "Eldoria World Info")
        self.assertEqual(len(loaded["entries"]), 2)
        e1 = loaded["entries"][0]
        self.assertEqual(e1["id"], 1)
        self.assertEqual(e1["keys"], ["dragon", "drake"])
        self.assertEqual(e1["content"], "Dragons are powerful fire-breathing beasts.")
        self.assertTrue(e1["enabled"])
        self.assertEqual(e1["priority"], 20)
        self.assertEqual(e1["position"], "after_char")

    def test_load_lorebook_sillytavern_format(self):
        # SillyTavern native export with dict entries, uid, order, disable, position numeric
        st_payload = {
            "name": "ST Native Lore",
            "entries": {
                "0": {
                    "uid": 10,
                    "key": ["magic", "mana"],
                    "content": "Mana flows through all living things.",
                    "disable": False,
                    "order": 50,
                    "position": 0,
                },
                "1": {
                    "uid": 11,
                    "key": "relic, artifact",
                    "content": "Ancient relics hold forgotten powers.",
                    "disable": True,
                    "order": 15,
                    "position": 1,
                },
            },
        }
        lb_file = C.lorebook_path(self.cid, self.ws)
        lb_file.write_text(json.dumps(st_payload), encoding="utf-8")

        loaded = C.load_lorebook(self.cid, self.ws)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "ST Native Lore")
        self.assertEqual(len(loaded["entries"]), 2)

        e0 = loaded["entries"][0]
        self.assertEqual(e0["keys"], ["magic", "mana"])
        self.assertEqual(e0["priority"], 50)
        self.assertEqual(e0["position"], "before_char")
        self.assertTrue(e0["enabled"])

        e1 = loaded["entries"][1]
        self.assertEqual(e1["keys"], ["relic", "artifact"])
        self.assertEqual(e1["priority"], 15)
        self.assertEqual(e1["position"], "after_char")
        self.assertFalse(e1["enabled"])

    def test_save_lorebook_atomic(self):
        payload = {"name": "Test Lore", "entries": []}
        C.save_lorebook(self.cid, payload, self.ws)
        self.assertTrue(C.lorebook_path(self.cid, self.ws).is_file())
        loaded = C.load_lorebook(self.cid, self.ws)
        self.assertEqual(loaded["name"], "Test Lore")


class MatchLorebookEntriesTests(unittest.TestCase):
    def test_keyword_matching_and_case_insensitivity(self):
        lorebook = {
            "entries": [
                {"id": 1, "keys": ["Dragon"], "content": "Big dragon", "enabled": True, "priority": 10},
                {"id": 2, "keys": ["castle"], "content": "Stone castle", "enabled": True, "priority": 10},
            ]
        }
        history = [{"role": "user", "text": "I see a dragon in the sky."}]
        matched = I.match_lorebook_entries(lorebook, history)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["id"], 1)

    def test_disabled_entries_skipped(self):
        lorebook = {
            "entries": [
                {"id": 1, "keys": ["sword"], "content": "Sharp blade", "enabled": False, "priority": 10},
                {"id": 2, "keys": ["shield"], "content": "Sturdy shield", "disable": True, "priority": 10},
                {"id": 3, "keys": ["potion"], "content": "Healing brew", "enabled": True, "priority": 10},
            ]
        }
        history = [{"role": "user", "text": "Take the sword, shield, and potion."}]
        matched = I.match_lorebook_entries(lorebook, history)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["id"], 3)

    def test_priority_sorting_and_max_three_limit(self):
        lorebook = {
            "entries": [
                {"id": 1, "keys": ["item"], "content": "Common item", "priority": 5, "enabled": True},
                {"id": 2, "keys": ["item"], "content": "Mythic item", "priority": 100, "enabled": True},
                {"id": 3, "keys": ["item"], "content": "Rare item", "priority": 50, "enabled": True},
                {"id": 4, "keys": ["item"], "content": "Uncommon item", "priority": 20, "enabled": True},
                {"id": 5, "keys": ["item"], "content": "Legendary item", "priority": 80, "enabled": True},
            ]
        }
        history = [{"role": "user", "text": "Show me an item."}]
        matched = I.match_lorebook_entries(lorebook, history, max_entries=3)
        self.assertEqual(len(matched), 3)
        # Should be sorted highest priority first: 100, 80, 50
        self.assertEqual([e["id"] for e in matched], [2, 5, 3])

    def test_content_truncation_500_chars(self):
        long_content = "X" * 700
        lorebook = {
            "entries": [
                {"id": 1, "keys": ["long"], "content": long_content, "priority": 10, "enabled": True}
            ]
        }
        history = [{"role": "user", "text": "Tell me a long story."}]
        matched = I.match_lorebook_entries(lorebook, history, max_chars=500)
        self.assertEqual(len(matched), 1)
        self.assertEqual(len(matched[0]["content"]), 500)

    def test_scan_depth_last_n_messages(self):
        lorebook = {
            "entries": [
                {"id": 1, "keys": ["old_secret"], "content": "Ancient secret", "priority": 10, "enabled": True},
                {"id": 2, "keys": ["new_secret"], "content": "Fresh secret", "priority": 10, "enabled": True},
            ]
        }
        # 7 messages total; scan_depth = 3 scans only the last 3
        history = [
            {"role": "user", "text": "old_secret happened here"},
            {"role": "assistant", "text": "Noted"},
            {"role": "user", "text": "Another talk"},
            {"role": "assistant", "text": "Another answer"},
            {"role": "user", "text": "new_secret is now here"},
            {"role": "assistant", "text": "I see"},
            {"role": "user", "text": "Final question"},
        ]
        matched = I.match_lorebook_entries(lorebook, history, scan_depth=3)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["id"], 2)


class LorebookContextAndBundleTests(LorebookTestCase):
    def test_lorebook_context_partitioning(self):
        payload = {
            "entries": [
                {"id": 1, "keys": ["forest"], "content": "Dark Forest", "position": "before_char", "priority": 30, "enabled": True},
                {"id": 2, "keys": ["tower"], "content": "High Tower", "position": "after_char", "priority": 20, "enabled": True},
            ]
        }
        C.save_lorebook(self.cid, payload, self.ws)
        history = [{"role": "user", "text": "We journey through the forest towards the tower."}]
        ctx = I.lorebook_context(self.cid, history, ws=self.ws)
        self.assertEqual(ctx["before_char"], "Dark Forest")
        self.assertEqual(ctx["after_char"], "High Tower")

    def test_build_instruction_bundle_injects_before_and_after_char(self):
        payload = {
            "entries": [
                {"id": 1, "keys": ["forest"], "content": "BEFORE_LORE_MARK", "position": "before_char", "priority": 30, "enabled": True},
                {"id": 2, "keys": ["tower"], "content": "AFTER_LORE_MARK", "position": "after_char", "priority": 20, "enabled": True},
            ]
        }
        C.save_lorebook(self.cid, payload, self.ws)
        history = [{"role": "user", "text": "Enter the forest and reach the tower."}]

        bundle = I.build_instruction_bundle(character=self.cid, history=history)
        text = bundle["text"]

        self.assertIn("BEFORE_LORE_MARK", text)
        self.assertIn("AFTER_LORE_MARK", text)
        self.assertIn("# Persona", text)

        before_idx = text.index("BEFORE_LORE_MARK")
        persona_idx = text.index("# Persona")
        after_idx = text.index("AFTER_LORE_MARK")

        self.assertLess(before_idx, persona_idx)
        self.assertLess(persona_idx, after_idx)

    def test_build_instruction_bundle_without_history_no_lorebook(self):
        payload = {
            "entries": [
                {"id": 1, "keys": ["forest"], "content": "FOREST_LORE", "position": "after_char", "priority": 10, "enabled": True}
            ]
        }
        C.save_lorebook(self.cid, payload, self.ws)

        bundle = I.build_instruction_bundle(character=self.cid)
        self.assertNotIn("FOREST_LORE", bundle["text"])


if __name__ == "__main__":
    unittest.main()
