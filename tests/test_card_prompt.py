"""card_prompt.py: profile specs, prompt builders, image prompt.

Run: engine/run-tests.sh test_card_prompt
     engine/run-tests.sh test_card_prompt
"""
import json
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import card_prompt as CP  # noqa: E402


# ── PROFILE_SPECS ───────────────────────────────────────────────────

class ProfileSpecsTest(unittest.TestCase):
    def test_three_profiles_exist(self):
        self.assertEqual(sorted(CP.PROFILE_SPECS),
                         ["detailed", "short", "verbose"])

    def test_each_profile_has_all_fields(self):
        expected = {
            "description", "personality", "first_message", "scenario",
            "system_prompt", "creator_notes", "message_examples",
            "alternate_greetings", "tags",
        }
        for name, spec in CP.PROFILE_SPECS.items():
            self.assertEqual(set(spec.keys()), expected, name)

    def test_verbose_is_bigger_than_short(self):
        short = CP.PROFILE_SPECS["short"]
        verbose = CP.PROFILE_SPECS["verbose"]
        for field in ("description", "personality", "first_message"):
            self.assertGreater(verbose[field]["max_words"],
                               short[field]["max_words"],
                               field)

    def test_first_message_has_range_fields(self):
        """ST-CardGen fieldDetail.ts: min/max words, min chars, paragraphs."""
        for profile in CP.PROFILE_SPECS.values():
            fm = profile["first_message"]
            for key in ("min_words", "max_words", "min_chars",
                        "min_paragraphs", "max_paragraphs"):
                self.assertIn(key, fm, key)
            self.assertLess(fm["min_words"], fm["max_words"])
            self.assertGreater(fm["min_chars"], 0)

    def test_tags_have_count_ranges(self):
        """ST-CardGen: tags short(4-8), detailed(6-10), verbose(8-12)."""
        expected = {
            "short":    (4, 8),
            "detailed": (6, 10),
            "verbose":  (8, 12),
        }
        for name, (mn, mx) in expected.items():
            tags = CP.PROFILE_SPECS[name]["tags"]
            self.assertEqual(tags["min_count"], mn, name)
            self.assertEqual(tags["max_count"], mx, name)

    def test_message_examples_have_pair_ranges(self):
        for name, spec in CP.PROFILE_SPECS.items():
            me = spec["message_examples"]
            self.assertIn("min_pairs", me, name)
            self.assertIn("max_pairs", me, name)

    def test_detailed_first_message_matches_spec(self):
        """ST-CardGen: detailed first_mes = 220-360 words, min 900 chars."""
        fm = CP.PROFILE_SPECS["detailed"]["first_message"]
        self.assertEqual(fm["min_words"], 220)
        self.assertEqual(fm["max_words"], 360)
        self.assertEqual(fm["min_chars"], 900)

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            CP.build_field_detail_lines(profile="nonexistent")


# ── _resolve_specs ──────────────────────────────────────────────────

class ResolveSpecsTest(unittest.TestCase):
    def test_returns_copy(self):
        specs = CP._resolve_specs("detailed")
        # mutating the result must not affect the original
        specs["description"]["min_words"] = 99999
        self.assertNotEqual(
            CP.PROFILE_SPECS["detailed"]["description"]["min_words"],
            99999)

    def test_overrides_apply(self):
        specs = CP._resolve_specs(
            "short", overrides={"description": {"min_words": 777}})
        self.assertEqual(specs["description"]["min_words"], 777)

    def test_overrides_add_new_field(self):
        specs = CP._resolve_specs(
            "short", overrides={"custom_field": {"min_words": 42}})
        self.assertEqual(specs["custom_field"]["min_words"], 42)


# ── build_field_detail_lines ────────────────────────────────────────

class FieldDetailLinesTest(unittest.TestCase):
    def test_contains_range_format(self):
        """Output uses range format like '220\u2013360 words'."""
        out = CP.build_field_detail_lines("detailed")
        self.assertIn("220\u2013360 words", out)

    def test_contains_min_chars(self):
        out = CP.build_field_detail_lines("detailed")
        self.assertIn("min 900 characters", out)

    def test_paragraph_separator_hint(self):
        out = CP.build_field_detail_lines("detailed")
        self.assertIn("\\n\\n between paragraphs", out)

    def test_fields_filter(self):
        out = CP.build_field_detail_lines("detailed",
                                          fields=["first_message"])
        self.assertIn("first_message", out)
        self.assertNotIn("- description:", out)
        self.assertNotIn("- personality:", out)

    def test_all_fields_present_without_filter(self):
        out = CP.build_field_detail_lines("detailed")
        for field in CP.PROFILE_SPECS["detailed"]:
            self.assertIn(field, out, field)

    def test_tags_show_item_range(self):
        out = CP.build_field_detail_lines("detailed")
        self.assertIn("tags", out)
        self.assertIn("items", out)

    def test_empty_spec_omitted_from_detail_lines(self):
        out = CP.build_field_detail_lines("short", overrides={"empty_field": {}})
        self.assertNotIn("empty_field", out)

    def test_unrecognized_keys_spec_skipped(self):
        self.assertIsNone(CP._format_spec_line("foo", {"bar": 123}))


# ── build_character_gen_prompt ──────────────────────────────────────

class CharacterGenPromptTest(unittest.TestCase):
    def test_returns_system_and_user(self):
        sys_p, usr_p = CP.build_character_gen_prompt("a pirate")
        self.assertIsInstance(sys_p, str)
        self.assertIsInstance(usr_p, str)

    def test_user_contains_idea(self):
        _, usr_p = CP.build_character_gen_prompt("a pirate")
        self.assertIn("a pirate", usr_p)

    def test_system_has_format_block(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn('"name"', sys_p)
        self.assertIn('"image_prompt"', sys_p)

    def test_overrides_flow(self):
        sys_p, _ = CP.build_character_gen_prompt(
            "test", overrides={"description": {"min_words": 777}})
        self.assertIn("777", sys_p)

    def test_system_has_all_detail_fields(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        for field in ("description", "personality", "first_message",
                      "scenario", "message_examples"):
            self.assertIn(field, sys_p, field)

    def test_in_medias_res_rule(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn("In Medias Res", sys_p)

    def test_anti_puppeting_rule(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn("Anti-puppeting", sys_p)

    def test_hook_rule(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn("Hook", sys_p)

    def test_sensory_detail_rule(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn("sensory", sys_p)

    def test_quoted_dialogue_rule(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn("quoted character dialogue", sys_p)

    def test_negative_prompt_in_format(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertIn("negative_prompt", sys_p)

    def test_use_default_negative(self):
        sys_p, _ = CP.build_character_gen_prompt(
            "test", use_default_negative=True)
        self.assertIn("Omit negative_prompt", sys_p)

    def test_default_no_omit_negative(self):
        sys_p, _ = CP.build_character_gen_prompt("test")
        self.assertNotIn("Omit negative_prompt", sys_p)


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

    def test_system_contains_only_missing_field_details(self):
        sys_p, _ = CP.build_fill_missing_prompt(
            "test", self.card, self.missing)
        # requested fields present
        self.assertIn("personality", sys_p)
        self.assertIn("first_message", sys_p)
        # non-requested field absent from detail section
        self.assertNotIn("- scenario:", sys_p)
        self.assertNotIn("- description:", sys_p)
        self.assertNotIn("- creator_notes:", sys_p)

    def test_system_instructs_only_missing(self):
        sys_p, _ = CP.build_fill_missing_prompt(
            "test", self.card, self.missing)
        self.assertIn("ONLY the missing fields", sys_p)
        self.assertIn("ONLY the keys listed below", sys_p)

    def test_user_contains_existing_card(self):
        _, usr_p = CP.build_fill_missing_prompt(
            "test", self.card, self.missing)
        self.assertIn("Luna", usr_p)

    def test_user_lists_missing_keys(self):
        _, usr_p = CP.build_fill_missing_prompt(
            "test", self.card, self.missing)
        self.assertIn("personality", usr_p)
        self.assertIn("first_message", usr_p)

    def test_overrides_flow_into_fill_missing(self):
        sys_p, _ = CP.build_fill_missing_prompt(
            "test", self.card, ["personality"],
            overrides={"personality": {"min_words": 555}})
        self.assertIn("555", sys_p)

    def test_overrides_positional_in_fill_missing(self):
        sys_p, _ = CP.build_fill_missing_prompt(
            "test", self.card, ["personality"], "detailed",
            {"personality": {"min_words": 444}})
        self.assertIn("444", sys_p)

    def test_fill_missing_mentions_negative_prompt(self):
        sys_p, _ = CP.build_fill_missing_prompt(
            "test", self.card, ["personality"])
        self.assertIn("negative_prompt in English", sys_p)


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

    def test_nonce_positional_5th_arg(self):
        """Spec signature: (idea, card, keys, profile, nonce)."""
        sys_p, _ = CP.build_regenerate_prompt(
            "test", self.card, self.targets, "detailed", "pos-nonce-99")
        self.assertIn("pos-nonce-99", sys_p)

    def test_empty_nonce_still_works(self):
        sys_p, _ = CP.build_regenerate_prompt(
            "test", self.card, self.targets, regen_nonce="")
        self.assertNotIn("nonce", sys_p.lower())
        self.assertIn("The output must differ from the current version.", sys_p)

    def test_system_contains_only_target_field_details(self):
        sys_p, _ = CP.build_regenerate_prompt(
            "test", self.card, ["personality"])
        self.assertIn("- personality:", sys_p)
        self.assertNotIn("- scenario:", sys_p)
        self.assertNotIn("- description:", sys_p)
        self.assertNotIn("- first_message:", sys_p)

    def test_user_contains_target_keys(self):
        _, usr_p = CP.build_regenerate_prompt(
            "test", self.card, self.targets)
        self.assertIn("personality", usr_p)

    def test_user_contains_existing_card(self):
        _, usr_p = CP.build_regenerate_prompt(
            "test", self.card, self.targets)
        self.assertIn("Luna", usr_p)

    def test_overrides_keyword_only(self):
        """overrides is keyword-only; passing 6 positional args should fail."""
        with self.assertRaises(TypeError):
            CP.build_regenerate_prompt(
                "test", self.card, self.targets, "detailed", "nonce",
                {"personality": {"min_words": 999}})

    def test_overrides_flow_into_regen(self):
        sys_p, _ = CP.build_regenerate_prompt(
            "test", self.card, ["personality"], regen_nonce="x",
            overrides={"personality": {"min_words": 333}})
        self.assertIn("333", sys_p)

    def test_regenerate_mentions_negative_prompt(self):
        sys_p, _ = CP.build_regenerate_prompt(
            "test", self.card, ["personality"])
        self.assertIn("negative_prompt in English", sys_p)


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

    def test_empty_or_whitespace_name_falls_back(self):
        out = CP.build_image_prompt({"name": "   "})
        self.assertIn("Portrait of character.", out)

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

    def test_korean_description_omits_visual_cue(self):
        card = {"name": "루나", "description": "은발을 가진 엘프 치유사이다."}  # l10n-ok
        out = CP.build_image_prompt(card)
        self.assertIn("루나", out)  # l10n-ok
        self.assertNotIn("은발", out)  # l10n-ok
        self.assertEqual(
            out,
            "Portrait of 루나. Anime-style character portrait, "  # l10n-ok
            "upper body, detailed face, soft lighting.",
        )

    def test_korean_image_prompt_omitted(self):
        card = {"name": "Luna", "image_prompt": "은발 엘프 소녀"}  # l10n-ok
        out = CP.build_image_prompt(card)
        self.assertNotIn("은발", out)  # l10n-ok
        self.assertEqual(
            out,
            "Portrait of Luna. Anime-style character portrait, "
            "upper body, detailed face, soft lighting.",
        )


# ── CARD_FIELDS ─────────────────────────────────────────────────────

class CardFieldsTest(unittest.TestCase):
    def test_canonical_fields(self):
        expected = [
            "name", "description", "personality", "first_message",
            "scenario", "system_prompt", "creator_notes",
            "message_examples", "alternate_greetings",
            "tags", "image_prompt", "negative_prompt",
        ]
        self.assertEqual(CP.CARD_FIELDS, expected)


# ── DEFAULT_NEGATIVE_PROMPT ─────────────────────────────────────────

class DefaultNegativePromptTest(unittest.TestCase):
    def test_is_nonempty_english(self):
        self.assertIsInstance(CP.DEFAULT_NEGATIVE_PROMPT, str)
        self.assertGreater(len(CP.DEFAULT_NEGATIVE_PROMPT), 10)

    def test_contains_common_negatives(self):
        neg = CP.DEFAULT_NEGATIVE_PROMPT
        self.assertIn("low quality", neg)
        self.assertIn("blurry", neg)


if __name__ == "__main__":
    unittest.main()
