"""card_prompt.py: profile specs, prompt builders, image prompt.

Run: python3 -m unittest tests.test_card_prompt  (from services/chatbot)
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import card_prompt as CP  # noqa: E402


# ── PROFILE_SPECS ───────────────────────────────────────────────────

class ProfileSpecsTest(unittest.TestCase):
    def test_three_profiles_exist(self):
        self.assertEqual(sorted(CP.PROFILE_SPECS), ["detailed", "short", "verbose"])

    def test_each_profile_has_all_fields(self):
        expected = {
            "description", "personality", "first_message", "scenario",
            "system_prompt", "creator_notes", "message_examples",
            "alternate_greetings",
        }
        for name, spec in CP.PROFILE_SPECS.items():
            self.assertEqual(set(spec.keys()), expected, name)

    def test_verbose_is_bigger_than_short(self):
        for field in ("description", "personality", "first_message"):
            s = CP.PROFILE_SPECS["short"][field]["words"]
            v = CP.PROFILE_SPECS["verbose"][field]["words"]
            self.assertGreater(v, s, field)


# ── build_field_detail_lines ────────────────────────────────────────

class FieldDetailLinesTest(unittest.TestCase):
    def test_returns_string_with_dash_lines(self):
        out = CP.build_field_detail_lines("short")
        self.assertIsInstance(out, str)
        for line in out.splitlines():
            self.assertTrue(line.startswith("- "), line)

    def test_override_merges(self):
        out = CP.build_field_detail_lines("short",
                                          overrides={"description": {"words": 999}})
        self.assertIn("999", out)

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            CP.build_field_detail_lines("nonexistent")


# ── build_character_gen_prompt ──────────────────────────────────────

class CharacterGenPromptTest(unittest.TestCase):
    def test_returns_system_and_user(self):
        sys_p, usr_p = CP.build_character_gen_prompt("a fox maid")
        self.assertIsInstance(sys_p, str)
        self.assertIsInstance(usr_p, str)

    def test_system_contains_format_block(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn('"name"', sys_p)
        self.assertIn('"image_prompt"', sys_p)

    def test_system_contains_rules(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn("In Medias Res", sys_p)
        self.assertIn("puppeting", sys_p)

    def test_user_contains_idea(self):
        _, usr_p = CP.build_character_gen_prompt("a dragon knight")
        self.assertIn("a dragon knight", usr_p)

    def test_profile_parameter(self):
        sys_p, _ = CP.build_character_gen_prompt("test", profile="verbose")
        # verbose description is 400 words
        self.assertIn("400", sys_p)


# ── build_tagged_prompt ─────────────────────────────────────────────

class TaggedPromptTest(unittest.TestCase):
    def test_contains_markers(self):
        out = CP.build_tagged_prompt("a pirate")
        for tag in ("#NAME#", "#DESCRIPTION#", "#PERSONALITY#",
                    "#FIRST_MESSAGE#", "#SCENARIO#", "#SYSTEM_PROMPT#",
                    "#CREATOR_NOTES#", "#MESSAGE_EXAMPLES#",
                    "#ALTERNATE_GREETINGS#", "#TAGS#", "#IMAGE_PROMPT#"):
            self.assertIn(tag, out, tag)

    def test_contains_idea(self):
        out = CP.build_tagged_prompt("space cowboy")
        self.assertIn("space cowboy", out)

    def test_contains_detail_lines(self):
        out = CP.build_tagged_prompt("test", profile="short")
        self.assertIn("words", out)


# ── build_fill_missing_prompt ───────────────────────────────────────

class FillMissingPromptTest(unittest.TestCase):
    def setUp(self):
        self.card = {"name": "Luna", "description": "a healer"}
        self.missing = ["personality", "first_message"]

    def test_returns_system_and_user(self):
        sys_p, usr_p = CP.build_fill_missing_prompt(
            "test", self.card, self.missing)
        self.assertIsInstance(sys_p, str)
        self.assertIsInstance(usr_p, str)

    def test_system_mentions_missing_only(self):
        sys_p, _ = CP.build_fill_missing_prompt(
            "test", self.card, self.missing)
        self.assertIn("missing", sys_p.lower())

    def test_user_contains_existing_card(self):
        _, usr_p = CP.build_fill_missing_prompt(
            "test", self.card, self.missing)
        self.assertIn("Luna", usr_p)

    def test_user_lists_missing_keys(self):
        _, usr_p = CP.build_fill_missing_prompt(
            "test", self.card, self.missing)
        self.assertIn("personality", usr_p)
        self.assertIn("first_message", usr_p)


# ── build_regenerate_prompt ─────────────────────────────────────────

class RegeneratePromptTest(unittest.TestCase):
    def setUp(self):
        self.card = {"name": "Luna", "personality": "kind"}
        self.targets = ["personality"]

    def test_returns_system_and_user(self):
        sys_p, usr_p = CP.build_regenerate_prompt(
            "test", self.card, self.targets)
        self.assertIsInstance(sys_p, str)
        self.assertIsInstance(usr_p, str)

    def test_system_contains_nonce(self):
        sys_p, _ = CP.build_regenerate_prompt(
            "test", self.card, self.targets, regen_nonce="abc123")
        self.assertIn("abc123", sys_p)

    def test_user_contains_target_keys(self):
        _, usr_p = CP.build_regenerate_prompt(
            "test", self.card, self.targets)
        self.assertIn("personality", usr_p)

    def test_user_contains_existing_card(self):
        _, usr_p = CP.build_regenerate_prompt(
            "test", self.card, self.targets)
        self.assertIn("Luna", usr_p)


# ── build_image_prompt ──────────────────────────────────────────────

class ImagePromptTest(unittest.TestCase):
    def test_with_image_prompt_field(self):
        card = {"name": "Luna", "image_prompt": "silver hair elf girl"}
        out = CP.build_image_prompt(card)
        self.assertIn("Luna", out)
        self.assertIn("silver hair elf girl", out)
        self.assertIn("Anime-style", out)

    def test_without_image_prompt_falls_back_to_description(self):
        card = {"name": "Luna", "description": "A tall elf with silver hair."}
        out = CP.build_image_prompt(card)
        self.assertIn("Luna", out)
        self.assertIn("A tall elf with silver hair.", out)

    def test_empty_card(self):
        out = CP.build_image_prompt({})
        self.assertIn("character", out)
        self.assertIn("Anime-style", out)

    def test_image_prompt_preferred_over_description(self):
        card = {
            "name": "X",
            "description": "fallback text here",
            "image_prompt": "primary prompt here",
        }
        out = CP.build_image_prompt(card)
        self.assertIn("primary prompt here", out)
        # description visual cues should NOT appear when image_prompt is set
        self.assertNotIn("fallback text", out)


# ── CARD_FIELDS ─────────────────────────────────────────────────────

class CardFieldsTest(unittest.TestCase):
    def test_canonical_fields(self):
        expected = [
            "name", "description", "personality", "first_message",
            "scenario", "system_prompt", "creator_notes",
            "message_examples", "alternate_greetings",
            "tags", "image_prompt",
        ]
        self.assertEqual(CP.CARD_FIELDS, expected)


if __name__ == "__main__":
    unittest.main()
