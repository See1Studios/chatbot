"""card_parse.py: dual parser and fallback machine for LLM card output.

Run: engine/run-tests.sh test_card_parse
     engine/run-tests.sh test_card_parse
"""
import json
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
import card_parse as CP  # noqa: E402
import card_prompt as prompt_mod  # noqa: E402


# ── extract_json_block ──────────────────────────────────────────────

class ExtractJsonBlockTest(unittest.TestCase):
    def test_basic_json_fence(self):
        raw = 'Some text\n```json\n{"name":"A"}\n```\nmore'
        self.assertEqual(CP.extract_json_block(raw), '{"name":"A"}')

    def test_case_insensitive(self):
        raw = '```JSON\n{"x":1}\n```'
        self.assertEqual(CP.extract_json_block(raw), '{"x":1}')

    def test_no_fence(self):
        self.assertIsNone(CP.extract_json_block('just plain text'))

    def test_whitespace_after_json_keyword(self):
        raw = '```json   \n  {"y":2}  \n```'
        self.assertEqual(CP.extract_json_block(raw), '{"y":2}')

    def test_multiple_fences_returns_first(self):
        raw = '```json\n{"a":1}\n```\n```json\n{"b":2}\n```'
        self.assertEqual(CP.extract_json_block(raw), '{"a":1}')


# ── try_parse_json ──────────────────────────────────────────────────

class TryParseJsonTest(unittest.TestCase):
    def test_pure_json(self):
        raw = '{"name":"Test","value":42}'
        result = CP.try_parse_json(raw)
        self.assertEqual(result["name"], "Test")
        self.assertEqual(result["value"], 42)

    def test_json_in_fence(self):
        raw = 'Here is the card:\n```json\n{"name":"Fenced"}\n```'
        result = CP.try_parse_json(raw)
        self.assertEqual(result["name"], "Fenced")

    def test_fence_preferred_over_raw(self):
        """When both a fence and raw JSON exist, fence wins."""
        raw = '{"raw":true}\n```json\n{"fenced":true}\n```'
        result = CP.try_parse_json(raw)
        self.assertTrue(result.get("fenced"))

    def test_garbage_returns_none(self):
        self.assertIsNone(CP.try_parse_json("not json at all"))

    def test_empty_string(self):
        self.assertIsNone(CP.try_parse_json(""))

    def test_whitespace_only(self):
        self.assertIsNone(CP.try_parse_json("   \n\n  "))

    def test_array_json(self):
        result = CP.try_parse_json('[1, 2, 3]')
        self.assertEqual(result, [1, 2, 3])

    def test_broken_fence_with_trailing_json_returns_none(self):
        """Broken fence AND valid JSON in tail — neither candidate parses
        because the raw string includes fence markup around the JSON."""
        raw = '```json\n{broken\n```\n\n{"name":"fallback"}'
        result = CP.try_parse_json(raw)
        self.assertIsNone(result)

    def test_json_with_surrounding_prose(self):
        raw = '  \n  {"key":"value"}  \n  '
        result = CP.try_parse_json(raw)
        self.assertEqual(result, {"key": "value"})

    def test_nested_json(self):
        obj = {"a": {"b": [1, 2]}, "c": "hello"}
        raw = json.dumps(obj)
        self.assertEqual(CP.try_parse_json(raw), obj)


# ── classify_raw_failure ────────────────────────────────────────────

class ClassifyRawFailureTest(unittest.TestCase):
    def test_truncated_no_closing_brace(self):
        raw = '{"name": "Alice", "desc'
        self.assertEqual(CP.classify_raw_failure(raw), "truncated")

    def test_truncated_unclosed_string(self):
        raw = '{"name": "Alice", "description": "'
        self.assertEqual(CP.classify_raw_failure(raw), "truncated")

    def test_truncated_unclosed_array_in_object(self):
        raw = '{"name": "Alice", "tags": ["warrior", "hero"'
        self.assertEqual(CP.classify_raw_failure(raw), "truncated")

    def test_truncated_unclosed_array_no_closing_bracket(self):
        # Starts with [ but lacks closing ]
        raw = '[1, 2'
        self.assertEqual(CP.classify_raw_failure(raw), "truncated")

    def test_truncated_unclosed_fence(self):
        # Opening code fence with no closing fence
        raw = '```json\n{"name": "Alice", "desc'
        self.assertEqual(CP.classify_raw_failure(raw), "truncated")

    def test_truncated_closed_fence_unclosed_inner_object(self):
        # Fence is closed, but inner JSON object lacks closing brace
        raw = '```json\n{"a":1\n```'
        self.assertEqual(CP.classify_raw_failure(raw), "truncated")

    def test_object_with_trailing_prose_classified_invalid_json(self):
        raw = '{"name": "Alice"} extra stuff without closing'
        self.assertEqual(CP.classify_raw_failure(raw), "invalid_json")

    def test_array_with_trailing_prose_classified_invalid_json(self):
        raw = '["tag1", "tag2"] trailing extra'
        self.assertEqual(CP.classify_raw_failure(raw), "invalid_json")

    def test_truncated_whitespace_handling(self):
        raw = '  {"name": "truncated  '
        self.assertEqual(CP.classify_raw_failure(raw), "truncated")

    def test_schema_mismatch_empty_object(self):
        # Valid JSON object but missing required character fields
        self.assertEqual(CP.classify_raw_failure("{}"), "schema_mismatch")

    def test_schema_mismatch_partial_fields(self):
        raw = '{"name": "Alice", "description": "brave"}'
        self.assertEqual(CP.classify_raw_failure(raw), "schema_mismatch")

    def test_schema_mismatch_with_parsed_arg(self):
        parsed = {"name": "Alice"}
        self.assertEqual(CP.classify_raw_failure("...", parsed=parsed), "schema_mismatch")

    def test_invalid_json_plain_prose(self):
        raw = "not json at all"
        self.assertEqual(CP.classify_raw_failure(raw), "invalid_json")

    def test_invalid_json_syntax_error(self):
        raw = '{ this is not valid json }'
        self.assertEqual(CP.classify_raw_failure(raw), "invalid_json")

    def test_invalid_json_broken_brackets(self):
        raw = '}{'
        self.assertEqual(CP.classify_raw_failure(raw), "invalid_json")

    def test_invalid_json_empty_string(self):
        self.assertEqual(CP.classify_raw_failure(""), "invalid_json")


# ── parse_tagged_sections ──────────────────────────────────────────

class ParseTaggedSectionsTest(unittest.TestCase):
    def test_basic_two_sections(self):
        raw = "#NAME#\nAlice\n#DESCRIPTION#\nA brave warrior"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["NAME"], "Alice")
        self.assertEqual(result["DESCRIPTION"], "A brave warrior")

    def test_multiline_content(self):
        raw = "#FIRST_MESSAGE#\nLine one\nLine two\nLine three"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["FIRST_MESSAGE"],
                         "Line one\nLine two\nLine three")

    def test_content_before_first_tag_ignored(self):
        raw = "Some preamble\n#NAME#\nBob"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["NAME"], "Bob")
        self.assertNotIn("preamble", str(result))

    def test_unknown_tag_treated_as_text(self):
        raw = "#NAME#\nAlice\n#UNKNOWN_TAG#\nstill Alice content\n#DESCRIPTION#\nDesc"
        result = CP.parse_tagged_sections(raw)
        self.assertIn("#UNKNOWN_TAG#", result["NAME"])
        self.assertEqual(result["DESCRIPTION"], "Desc")

    def test_empty_section(self):
        raw = "#NAME#\n#DESCRIPTION#\nSome desc"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["NAME"], "")
        self.assertEqual(result["DESCRIPTION"], "Some desc")

    def test_all_pe_tags(self):
        parts = []
        for tag in CP.TAGS:
            parts.append(f"#{tag}#")
            parts.append(f"content of {tag}")
        raw = "\n".join(parts)
        result = CP.parse_tagged_sections(raw)
        for tag in CP.TAGS:
            self.assertEqual(result[tag], f"content of {tag}")

    def test_windows_line_endings(self):
        raw = "#NAME#\r\nAlice\r\n#DESCRIPTION#\r\nA character"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["NAME"], "Alice")
        self.assertEqual(result["DESCRIPTION"], "A character")

    def test_tag_with_leading_whitespace(self):
        """Tags with leading spaces on the line are still recognised."""
        raw = "  #NAME#  \nAlice"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["NAME"], "Alice")

    def test_escaped_quotes_in_content(self):
        raw = '#NAME#\nShe said \\"hello\\"'
        result = CP.parse_tagged_sections(raw)
        self.assertIn('\\"hello\\"', result["NAME"])

    def test_empty_input(self):
        self.assertEqual(CP.parse_tagged_sections(""), {})

    def test_pe_extension_tags(self):
        raw = "#SYSTEM_PROMPT#\nBe helpful\n#ALTERNATE_GREETINGS#\nHi\nHey"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["SYSTEM_PROMPT"], "Be helpful")
        self.assertEqual(result["ALTERNATE_GREETINGS"], "Hi\nHey")

    def test_message_examples_tag(self):
        raw = "#MESSAGE_EXAMPLES#\n- Hello\n- Hi there"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["MESSAGE_EXAMPLES"], "- Hello\n- Hi there")

    def test_content_trimmed(self):
        raw = "#NAME#\n\n  Alice  \n\n#DESCRIPTION#\n  Desc  \n"
        result = CP.parse_tagged_sections(raw)
        self.assertEqual(result["NAME"], "Alice")
        self.assertEqual(result["DESCRIPTION"], "Desc")


# ── build_character_from_tagged ─────────────────────────────────────

class BuildCharacterFromTaggedTest(unittest.TestCase):
    def _full_sections(self, **overrides):
        base = {
            "NAME": "Alice",
            "DESCRIPTION": "Brave warrior",
            "PERSONALITY": "Determined",
            "FIRST_MESSAGE": "The torch flickers.",
            "SCENARIO": "In a dungeon",
            "SYSTEM_PROMPT": "Be immersive",
            "CREATOR_NOTES": "Test card",
            "MESSAGE_EXAMPLES": "- Hi\n- Hello",
            "ALTERNATE_GREETINGS": "- Hey there",
            "TAGS": "fantasy, warrior, dungeon",
            "IMAGE_PROMPT": "female warrior",
            "NEGATIVE_PROMPT": "blurry",
        }
        base.update(overrides)
        return base

    def test_basic_mapping(self):
        result = CP.build_character_from_tagged(self._full_sections())
        self.assertEqual(result["name"], "Alice")
        self.assertEqual(result["description"], "Brave warrior")
        self.assertEqual(result["personality"], "Determined")
        self.assertEqual(result["first_message"], "The torch flickers.")
        self.assertEqual(result["scenario"], "In a dungeon")
        self.assertEqual(result["system_prompt"], "Be immersive")
        self.assertEqual(result["creator_notes"], "Test card")
        self.assertEqual(result["image_prompt"], "female warrior")
        self.assertEqual(result["negative_prompt"], "blurry")

    def test_keys_order_matches_card_prompt_fields(self):
        result = CP.build_character_from_tagged(self._full_sections())
        self.assertEqual(list(result.keys()), prompt_mod.CARD_FIELDS)

    def test_tags_parsed_as_list(self):
        result = CP.build_character_from_tagged(
            self._full_sections(TAGS="tag1, tag2, tag3"))
        self.assertEqual(result["tags"], ["tag1", "tag2", "tag3"])

    def test_tags_newline_separated(self):
        result = CP.build_character_from_tagged(
            self._full_sections(TAGS="tag1\ntag2\ntag3"))
        self.assertEqual(result["tags"], ["tag1", "tag2", "tag3"])

    def test_tags_mixed_separators(self):
        result = CP.build_character_from_tagged(
            self._full_sections(TAGS="a, b\nc"))
        self.assertEqual(result["tags"], ["a", "b", "c"])

    def test_empty_tags(self):
        result = CP.build_character_from_tagged(
            self._full_sections(TAGS=""))
        self.assertEqual(result["tags"], [])

    def test_pov_tag_not_recognised_e2e(self):
        """#POV# is not in TAGS — the parser treats it as body text."""
        raw = "#NAME#\nAlice\n#POV#\nfirst\n#DESCRIPTION#\nBrave"
        sections = CP.parse_tagged_sections(raw)
        # #POV# line absorbed into NAME body, not a separate section.
        self.assertNotIn("POV", sections)
        self.assertIn("#POV#", sections["NAME"])
        result = CP.build_character_from_tagged(sections)
        self.assertNotIn("pov", result)
        self.assertEqual(result["description"], "Brave")

    def test_no_pov_field_in_output(self):
        """A full tagged response never produces a 'pov' field."""
        result = CP.build_character_from_tagged(self._full_sections())
        self.assertNotIn("pov", result)

    def test_missing_section_defaults_to_empty(self):
        result = CP.build_character_from_tagged({"NAME": "Solo"})
        self.assertEqual(result["name"], "Solo")
        self.assertEqual(result["description"], "")
        self.assertEqual(result["tags"], [])


# ── parse_character_response ────────────────────────────────────────

class ParseCharacterResponseTest(unittest.TestCase):
    def _minimal_card(self, **overrides):
        card = {
            "name": "Test",
            "description": "A test character",
            "personality": "Calm",
            "first_message": "Hello world.",
            "scenario": "Test scenario",
        }
        card.update(overrides)
        return card

    def test_json_parse(self):
        raw = json.dumps(self._minimal_card())
        result = CP.parse_character_response(raw)
        self.assertEqual(result["name"], "Test")

    def test_json_in_fence(self):
        raw = "Here is the result:\n```json\n" + \
              json.dumps(self._minimal_card()) + "\n```"
        result = CP.parse_character_response(raw)
        self.assertEqual(result["name"], "Test")

    def test_tagged_fallback(self):
        raw = (
            "#NAME#\nAlice\n"
            "#DESCRIPTION#\nA brave warrior\n"
            "#PERSONALITY#\nDetermined and fierce\n"
            "#FIRST_MESSAGE#\nThe torch flickers.\n"
            "#SCENARIO#\nDeep in a dungeon"
        )
        result = CP.parse_character_response(raw)
        self.assertEqual(result["name"], "Alice")
        self.assertEqual(result["description"], "A brave warrior")

    def test_garbage_raises(self):
        with self.assertRaises(ValueError) as ctx:
            CP.parse_character_response("completely unparseable output")
        self.assertIn("failure class: invalid_json", str(ctx.exception))

    def test_truncated_raises(self):
        raw = '{"name": "Alice", "desc'
        with self.assertRaises(ValueError) as ctx:
            CP.parse_character_response(raw)
        self.assertIn("failure class: truncated", str(ctx.exception))

    def test_tagged_missing_required_raises(self):
        raw = "#NAME#\nAlice\n#DESCRIPTION#\nSome desc"
        with self.assertRaises(ValueError) as ctx:
            CP.parse_character_response(raw)
        self.assertIn("missing required", str(ctx.exception).lower())
        self.assertIn("failure class: schema_mismatch", str(ctx.exception))

    def test_json_missing_required_falls_through_to_tagged(self):
        """JSON with missing required fields → schema_mismatch, not
        invalid_json."""
        partial = {"name": "X", "description": "Y"}
        raw = json.dumps(partial)
        # No tagged sections either, so it should raise with schema_mismatch.
        with self.assertRaises(ValueError) as ctx:
            CP.parse_character_response(raw)
        self.assertIn("failure class: schema_mismatch", str(ctx.exception))

    def test_full_tagged_with_pe_extensions(self):
        raw = (
            "#NAME#\nBob\n"
            "#DESCRIPTION#\nA wizard\n"
            "#PERSONALITY#\nWise\n"
            "#FIRST_MESSAGE#\nBob adjusts his glasses.\n"
            "#SCENARIO#\nMagic tower\n"
            "#SYSTEM_PROMPT#\nBe mysterious\n"
            "#MESSAGE_EXAMPLES#\n- How?\n- Like this.\n"
            "#ALTERNATE_GREETINGS#\n- Greetings.\n"
            "#TAGS#\nwizard, magic\n"
            "#IMAGE_PROMPT#\nold wizard portrait\n"
            "#NEGATIVE_PROMPT#\nblurry"
        )
        result = CP.parse_character_response(raw)
        self.assertEqual(result["name"], "Bob")
        self.assertEqual(result["system_prompt"], "Be mysterious")
        self.assertEqual(result["tags"], ["wizard", "magic"])
        self.assertEqual(result["image_prompt"], "old wizard portrait")

    def test_json_with_extra_fields_preserved(self):
        card = self._minimal_card(custom_field="extra")
        raw = json.dumps(card)
        result = CP.parse_character_response(raw)
        self.assertEqual(result["custom_field"], "extra")


# ── tag registry ────────────────────────────────────────────────────

class TagRegistryTest(unittest.TestCase):
    def test_tag_set_matches_list(self):
        self.assertEqual(CP._TAG_SET, frozenset(CP.TAGS))

    def test_pe_extensions_present(self):
        self.assertIn("SYSTEM_PROMPT", CP._TAG_SET)
        self.assertIn("ALTERNATE_GREETINGS", CP._TAG_SET)
        self.assertIn("MESSAGE_EXAMPLES", CP._TAG_SET)

    def test_no_duplicate_tags(self):
        self.assertEqual(len(CP.TAGS), len(set(CP.TAGS)))

    def test_tags_align_with_card_prompt_fields(self):
        self.assertEqual([t.lower() for t in CP.TAGS], prompt_mod.CARD_FIELDS)

    def test_required_fields_align_with_card_prompt(self):
        self.assertEqual(list(CP._REQUIRED_FIELDS), prompt_mod.CARD_FIELDS[:5])


if __name__ == "__main__":
    unittest.main()
