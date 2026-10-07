"""tests/test_card_gen.py – unit tests for character card generator and refiner.

Tests port of ST-CardGen routes/character.ts:
  - pick_missing_keys
  - filter_patch_to_missing
  - filter_patch_to_targets
  - equal_normalized
  - regenerate_fields (UUID regen_nonce, 3-attempt verification loop)
  - fill_missing_fields
  - build_chara_v2_card
  - build_visual_md
  - save_character_package
  - orchestrate_card_generation & CLI
"""
import json
import re
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, List

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import card_prompt  # noqa: E402
from tools import card_gen  # noqa: E402


class PickMissingKeysTest(unittest.TestCase):
    def test_empty_card_returns_all_fields(self):
        card: Dict[str, Any] = {}
        missing = card_gen.pick_missing_keys(card)
        self.assertEqual(missing, card_prompt.CARD_FIELDS)

    def test_partially_filled_card(self):
        card = {
            "name": "Koko",
            "description": "Genius hacker",
            "personality": "Sassy",
            "first_message": "Hey there mid-scene!",
            "tags": ["hacker", "tech"],
        }
        missing = card_gen.pick_missing_keys(card)
        self.assertNotIn("name", missing)
        self.assertNotIn("description", missing)
        self.assertNotIn("personality", missing)
        self.assertNotIn("first_message", missing)
        self.assertNotIn("tags", missing)
        self.assertIn("scenario", missing)
        self.assertIn("system_prompt", missing)
        self.assertIn("creator_notes", missing)
        self.assertIn("message_examples", missing)
        self.assertIn("alternate_greetings", missing)
        self.assertIn("image_prompt", missing)
        self.assertIn("negative_prompt", missing)

    def test_alias_support_for_first_mes_and_mes_example(self):
        card = {
            "first_mes": "Opening scene...",
            "mes_example": "<START>\nDialogue sample",
        }
        missing = card_gen.pick_missing_keys(card)
        self.assertNotIn("first_message", missing)
        self.assertNotIn("message_examples", missing)

    def test_chara_v2_nested_data(self):
        card = {
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": {
                "name": "Ruru",
                "description": "Secretary",
            },
        }
        missing = card_gen.pick_missing_keys(card)
        self.assertNotIn("name", missing)
        self.assertNotIn("description", missing)
        self.assertIn("personality", missing)

    def test_extensions_chatbot_fields_not_missing(self):
        card = card_gen.build_chara_v2_card({
            "name": "AnchorChar",
            "image_prompt": "Portrait of anchor girl",
            "negative_prompt": "blurry, low quality",
        })
        missing = card_gen.pick_missing_keys(card)
        self.assertNotIn("image_prompt", missing)
        self.assertNotIn("negative_prompt", missing)

    def test_custom_keys_subset(self):
        card = {"name": "Test", "personality": ""}
        missing = card_gen.pick_missing_keys(card, keys=["name", "personality", "scenario"])
        self.assertEqual(missing, ["personality", "scenario"])

    def test_empty_types_considered_missing(self):
        card = {
            "name": "   ",
            "tags": [],
            "description": None,
            "personality": "Cool",
        }
        missing = card_gen.pick_missing_keys(card, keys=["name", "tags", "description", "personality"])
        self.assertEqual(missing, ["name", "tags", "description"])


class FilterPatchTest(unittest.TestCase):
    def test_filter_patch_to_missing_strips_unrequested_and_empty(self):
        patch = {
            "personality": "Quiet",
            "scenario": "Cyberpunk alley",
            "name": "ShouldBeStripped",
            "creator_notes": "   ",
            "first_message": None,
        }
        missing_keys = ["personality", "scenario", "creator_notes", "first_message"]
        filtered = card_gen.filter_patch_to_missing(patch, missing_keys)
        self.assertEqual(filtered, {
            "personality": "Quiet",
            "scenario": "Cyberpunk alley",
        })

    def test_filter_patch_to_missing_normalizes_aliases(self):
        patch = {
            "first_mes": "Scene text",
            "mes_example": "Examples text",
        }
        missing = ["first_message", "message_examples"]
        filtered = card_gen.filter_patch_to_missing(patch, missing)
        self.assertEqual(filtered, {
            "first_message": "Scene text",
            "message_examples": "Examples text",
        })

    def test_filter_patch_to_targets_keeps_only_targets(self):
        patch = {
            "first_message": "New intro",
            "personality": "More fiery",
            "scenario": "Unrelated scenario",
        }
        targets = ["first_message", "personality"]
        filtered = card_gen.filter_patch_to_targets(patch, targets)
        self.assertEqual(filtered, {
            "first_message": "New intro",
            "personality": "More fiery",
        })

class ApplyPatchTest(unittest.TestCase):
    def test_apply_patch_v2_canonical_mapping_and_no_first_message_key(self):
        card = card_gen.build_chara_v2_card({"name": "Test", "first_message": ""})
        card_gen.apply_patch(card, {"first_message": "New scene opening!"})
        self.assertEqual(card["data"]["first_mes"], "New scene opening!")
        self.assertNotIn("first_message", card["data"])

    def test_apply_patch_v2_message_examples_formatting(self):
        card = card_gen.build_chara_v2_card({"name": "Test"})
        card_gen.apply_patch(
            card,
            {"message_examples": ["<START>\n<USER> Hi\n<BOT> Hey", "<START>\n<USER> Bye\n<BOT> Bye"]},
        )
        self.assertEqual(
            card["data"]["mes_example"],
            "<START>\n<USER> Hi\n<BOT> Hey\n\n<START>\n<USER> Bye\n<BOT> Bye",
        )
        self.assertNotIn("message_examples", card["data"])

    def test_apply_patch_v2_image_prompt_in_extensions_chatbot(self):
        card = card_gen.build_chara_v2_card({"name": "Test"})
        card_gen.apply_patch(card, {"image_prompt": "1girl, hacker", "negative_prompt": "blurry"})
        self.assertEqual(card["data"]["extensions"]["chatbot"]["image_prompt"], "1girl, hacker")
        self.assertEqual(card["data"]["extensions"]["chatbot"]["negative_prompt"], "blurry")
        self.assertNotIn("image_prompt", card["data"])
        self.assertNotIn("negative_prompt", card["data"])

    def test_apply_patch_flat_card_preserves_keys(self):
        flat1 = {"name": "Flat1", "first_mes": "Old greeting"}
        card_gen.apply_patch(flat1, {"first_message": "New greeting"})
        self.assertEqual(flat1["first_mes"], "New greeting")
        self.assertNotIn("first_message", flat1)

        flat2 = {"name": "Flat2", "first_message": "Old greeting"}
        card_gen.apply_patch(flat2, {"first_message": "New greeting"})
        self.assertEqual(flat2["first_message"], "New greeting")


class EqualNormalizedTest(unittest.TestCase):
    def test_strings_with_whitespace_and_newline_differences(self):
        s1 = "Line one.\n\nLine two with   spaces.  "
        s2 = "Line one.\r\nLine two with spaces."
        self.assertTrue(card_gen.equal_normalized(s1, s2))

    def test_strings_substantively_different(self):
        s1 = "A brave knight."
        s2 = "A cowardly rogue."
        self.assertFalse(card_gen.equal_normalized(s1, s2))

    def test_empty_equivalencies(self):
        self.assertTrue(card_gen.equal_normalized("", None))
        self.assertTrue(card_gen.equal_normalized(None, "   "))
        self.assertTrue(card_gen.equal_normalized([], None))
        self.assertTrue(card_gen.equal_normalized({}, []))
        self.assertFalse(card_gen.equal_normalized("content", None))
        self.assertFalse(card_gen.equal_normalized(None, ["item"]))

    def test_lists_normalized_comparison(self):
        l1 = [" tag1 ", "tag2\n"]
        l2 = ["tag1", "tag2"]
        self.assertTrue(card_gen.equal_normalized(l1, l2))

        l3 = ["tag1", "tag3"]
        self.assertFalse(card_gen.equal_normalized(l1, l3))

    def test_dicts_normalized_comparison(self):
        d1 = {"a": " hello  world ", "b": ["x "]}
        d2 = {"a": "hello world", "b": ["x"]}
        self.assertTrue(card_gen.equal_normalized(d1, d2))

        d3 = {"a": "other"}
        self.assertFalse(card_gen.equal_normalized(d1, d3))


class RegenerateFieldsTest(unittest.TestCase):
    def test_uuid_regen_nonce_injected_per_attempt(self):
        nonces_seen: List[str] = []

        def mock_llm(sys_prompt: str, user_prompt: str) -> str:
            m = re.search(r"Use the nonce ([a-f0-9-]+) as a creativity seed", sys_prompt)
            if m:
                nonces_seen.append(m.group(1))
            return json.dumps({"personality": "New take %d" % len(nonces_seen)})

        existing = {"personality": "Original take"}
        patch = card_gen.regenerate_fields(
            "Rabbit hacker",
            existing,
            ["personality"],
            mock_llm,
        )
        self.assertEqual(len(nonces_seen), 1)
        self.assertEqual(patch["personality"], "New take 1")
        # Ensure it is a valid UUID
        uuid.UUID(nonces_seen[0])

    def test_retries_until_substantive_change(self):
        calls = 0

        def mock_llm(sys_prompt: str, user_prompt: str) -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                # Same text with slight whitespace variations
                return json.dumps({"first_message": "Original intro   "})
            return json.dumps({"first_message": "Completely new opening scene!"})

        existing = {"first_message": "Original intro"}
        patch = card_gen.regenerate_fields(
            "Idea",
            existing,
            ["first_message"],
            mock_llm,
            max_retries=3,
        )
        self.assertEqual(calls, 3)
        self.assertEqual(patch["first_message"], "Completely new opening scene!")

    def test_three_attempts_fail_returns_last_or_raises(self):
        calls = 0

        def mock_llm(sys_prompt: str, user_prompt: str) -> str:
            nonlocal calls
            calls += 1
            return json.dumps({"description": "Unchanged description"})

        existing = {"description": "Unchanged description"}
        # Without raise_on_failure: returns last patch after 3 attempts
        patch = card_gen.regenerate_fields(
            "Idea",
            existing,
            ["description"],
            mock_llm,
            max_retries=3,
            raise_on_failure=False,
        )
        self.assertEqual(calls, 3)
        self.assertEqual(patch["description"], "Unchanged description")

        # With raise_on_failure: raises RuntimeError
        calls = 0
        with self.assertRaises(RuntimeError):
            card_gen.regenerate_fields(
                "Idea",
                existing,
                ["description"],
                mock_llm,
                max_retries=3,
                raise_on_failure=True,
            )
        self.assertEqual(calls, 3)


class FillMissingFieldsTest(unittest.TestCase):
    def test_fills_only_missing_fields(self):
        called_missing: List[str] = []

        def mock_llm(sys_prompt: str, user_prompt: str) -> str:
            m = re.search(r"Missing keys to fill:\s*([\w, ]+)", user_prompt)
            if m:
                called_missing.extend([k.strip() for k in m.group(1).split(",")])
            return json.dumps({
                "scenario": "Training arena",
                "system_prompt": "Always stay in character.",
                "name": "IgnoredOverwrite",
            })

        card = {
            "name": "ExistingName",
            "personality": "Brave",
            "scenario": "",
            "system_prompt": "",
        }
        patch = card_gen.fill_missing_fields(
            "Warrior",
            card,
            mock_llm,
            missing_keys=["scenario", "system_prompt"],
        )
        self.assertIn("scenario", called_missing)
        self.assertIn("system_prompt", called_missing)
        self.assertNotIn("name", called_missing)
        self.assertEqual(patch, {
            "scenario": "Training arena",
            "system_prompt": "Always stay in character.",
        })

    def test_no_missing_fields_skips_llm(self):
        mock_called = False

        def mock_llm(sys_prompt: str, user_prompt: str) -> str:
            nonlocal mock_called
            mock_called = True
            return "{}"

        card = {k: "Filled" for k in card_prompt.CARD_FIELDS}
        patch = card_gen.fill_missing_fields("Warrior", card, mock_llm)
        self.assertFalse(mock_called)
        self.assertEqual(patch, {})


class BuildCharaV2CardTest(unittest.TestCase):
    def test_chara_v2_structure_and_extensions(self):
        raw = {
            "name": "Koko",
            "description": "Tech prodigy",
            "personality": "Tsundere",
            "first_message": "Mid-scene greeting",
            "message_examples": ["<USER> Hi\n<BOT> Hello", "<USER> Bye\n<BOT> See ya"],
            "tags": ["hacker", "tech"],
            "image_prompt": "Anime girl with rabbit ears",
            "negative_prompt": "blurry",
        }
        card = card_gen.build_chara_v2_card(
            raw,
            user_title="코치",  # l10n-ok
            voice="새침한 어조",  # l10n-ok
            role="staff",
        )
        self.assertEqual(card["spec"], "chara_card_v2")
        self.assertEqual(card["spec_version"], "2.0")
        data = card["data"]
        self.assertEqual(data["name"], "Koko")
        self.assertEqual(data["first_mes"], "Mid-scene greeting")
        self.assertIn("<USER> Hi\n<BOT> Hello", data["mes_example"])
        self.assertEqual(data["tags"], ["hacker", "tech"])

        ext = data["extensions"]["chatbot"]
        self.assertEqual(ext["role"], "staff")
        self.assertEqual(ext["display"]["user_title"], "코치")  # l10n-ok
        self.assertEqual(ext["display"]["voice"], "새침한 어조")  # l10n-ok
        self.assertEqual(ext["image_prompt"], "Anime girl with rabbit ears")
        self.assertEqual(ext["negative_prompt"], "blurry")


class BuildVisualMdTest(unittest.TestCase):
    def test_anchor_sections_present(self):
        card = {
            "name": "Mimi",
            "image_prompt": "Fox girl maid holding a tray",
            "negative_prompt": "low quality, watermark",
        }
        text = card_gen.build_visual_md("Mimi", "char_123", card=card)
        self.assertIn("# Mimi visual lock sheet", text)
        self.assertIn("### 1. Style Anchor", text)
        self.assertIn("### 2. Character Anchor (Mimi)", text)
        self.assertIn("### 3. Generation Rule", text)
        self.assertIn("### 4. Framing & Composition", text)
        self.assertIn("### 5. Negative Lock", text)
        self.assertIn("Fox girl maid holding a tray", text)
        self.assertIn("low quality, watermark", text)


class PackageAndOrchestrationTest(unittest.TestCase):
    def test_save_character_package(self):
        card = card_gen.build_chara_v2_card({"name": "TestChar"})
        visual = card_gen.build_visual_md("TestChar", "char_test")
        with tempfile.TemporaryDirectory() as td:
            pkg = card_gen.save_character_package(card, visual, ws=td, cid="char_test123")
            char_dir = Path(pkg["dir"])
            self.assertTrue(char_dir.is_dir())
            card_json = char_dir / "card.json"
            visual_md = char_dir / "visual.md"
            self.assertTrue(card_json.is_file())
            self.assertTrue(visual_md.is_file())

            loaded = json.loads(card_json.read_text(encoding="utf-8"))
            self.assertEqual(loaded["data"]["name"], "TestChar")
            self.assertIn("# TestChar visual lock sheet", visual_md.read_text(encoding="utf-8"))

    def test_orchestrate_card_generation_dry_run(self):
        def mock_llm(s: str, u: str) -> str:
            return json.dumps({
                "name": "Nono",
                "description": "Producer rabbit",
                "personality": "Calm leader",
                "first_message": "Working hard today!",
                "scenario": "Studio desk",
                "system_prompt": "Support the team",
                "creator_notes": "Created for testing",
                "message_examples": ["Hello"],
                "alternate_greetings": ["Hi"],
                "tags": ["producer"],
                "image_prompt": "Rabbit girl in studio",
                "negative_prompt": "distorted",
            })

        res = card_gen.orchestrate_card_generation(
            "Producer girl",
            mock_llm,
            dry_run=True,
        )
        self.assertIsNone(res["dir"])
        self.assertIn("card", res)
        self.assertEqual(res["card"]["data"]["name"], "Nono")
        self.assertIn("visual_md", res)

    def test_cli_dry_run_idea(self):
        sample_card = {
            "name": "CliTest",
            "description": "Desc",
            "personality": "Pers",
            "first_message": "Intro",
            "scenario": "Scen",
            "system_prompt": "Sys",
            "creator_notes": "Notes",
            "message_examples": ["Ex"],
            "alternate_greetings": ["Alt"],
            "tags": ["tag"],
            "image_prompt": "Portrait of CliTest.",
            "negative_prompt": "bad",
        }
        import io
        import contextlib
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as f:
            json.dump(sample_card, f)
            tmp_input = f.name

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ret = card_gen.main(["TestIdea", "--dry-run", "--input-file", tmp_input])
            self.assertEqual(ret, 0)
            parsed = json.loads(buf.getvalue())
            self.assertEqual(parsed["data"]["name"], "CliTest")
        finally:
            Path(tmp_input).unlink(missing_ok=True)

    def test_cli_fill_missing(self):
        import io
        import contextlib
        card = card_gen.build_chara_v2_card({"name": "TargetCard", "personality": ""})
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fc:
            json.dump(card, fc)
            card_path = fc.name
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fi:
            json.dump({"personality": "Now filled via CLI"}, fi)
            input_path = fi.name

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ret = card_gen.main([
                    "--fill-missing",
                    "--card", card_path,
                    "--input-file", input_path,
                ])
            self.assertEqual(ret, 0)
            patch = json.loads(buf.getvalue())
            self.assertEqual(patch.get("personality"), "Now filled via CLI")

            # Check card was updated on disk
            updated = json.loads(Path(card_path).read_text(encoding="utf-8"))
            self.assertEqual(updated["data"]["personality"], "Now filled via CLI")
        finally:
            Path(card_path).unlink(missing_ok=True)
            Path(input_path).unlink(missing_ok=True)

    def test_cli_regenerate(self):
        import io
        import contextlib
        card = card_gen.build_chara_v2_card({"name": "TargetCard", "personality": "Old pers"})
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fc:
            json.dump(card, fc)
            card_path = fc.name
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fi:
            json.dump({"personality": "Brand new personality!"}, fi)
            input_path = fi.name

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ret = card_gen.main([
                    "--regenerate", "personality",
                    "--card", card_path,
                    "--input-file", input_path,
                ])
            self.assertEqual(ret, 0)
            patch = json.loads(buf.getvalue())
            self.assertEqual(patch.get("personality"), "Brand new personality!")

            updated = json.loads(Path(card_path).read_text(encoding="utf-8"))
            self.assertEqual(updated["data"]["personality"], "Brand new personality!")
        finally:
            Path(card_path).unlink(missing_ok=True)
            Path(input_path).unlink(missing_ok=True)

    def test_cli_fill_missing_v2_canonical_and_extensions(self):
        import io
        import contextlib
        card = card_gen.build_chara_v2_card({
            "name": "TargetCard",
            "first_message": "",
            "message_examples": "",
            "image_prompt": "",
        })
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fc:
            json.dump(card, fc)
            card_path = fc.name
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fi:
            json.dump({
                "first_message": "CLI intro scene",
                "message_examples": ["<USER> Hi\n<BOT> Hey"],
                "image_prompt": "1girl in cyber suit",
            }, fi)
            input_path = fi.name

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ret = card_gen.main([
                    "--fill-missing",
                    "--card", card_path,
                    "--input-file", input_path,
                ])
            self.assertEqual(ret, 0)
            updated = json.loads(Path(card_path).read_text(encoding="utf-8"))
            data = updated["data"]
            self.assertEqual(data["first_mes"], "CLI intro scene")
            self.assertNotIn("first_message", data)
            self.assertEqual(data["mes_example"], "<USER> Hi\n<BOT> Hey")
            self.assertNotIn("message_examples", data)
            self.assertEqual(data["extensions"]["chatbot"]["image_prompt"], "1girl in cyber suit")
            self.assertNotIn("image_prompt", data)
        finally:
            Path(card_path).unlink(missing_ok=True)
            Path(input_path).unlink(missing_ok=True)

    def test_cli_regenerate_v2_canonical(self):
        import io
        import contextlib
        card = card_gen.build_chara_v2_card({
            "name": "TargetCard",
            "first_message": "Old intro scene",
        })
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fc:
            json.dump(card, fc)
            card_path = fc.name
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fi:
            json.dump({"first_message": "Brand new intro via CLI!"}, fi)
            input_path = fi.name

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ret = card_gen.main([
                    "--regenerate", "first_message",
                    "--card", card_path,
                    "--input-file", input_path,
                ])
            self.assertEqual(ret, 0)
            updated = json.loads(Path(card_path).read_text(encoding="utf-8"))
            data = updated["data"]
            self.assertEqual(data["first_mes"], "Brand new intro via CLI!")
            self.assertNotIn("first_message", data)
        finally:
            Path(card_path).unlink(missing_ok=True)
            Path(input_path).unlink(missing_ok=True)

    def test_cli_regenerate_failure_exits_nonzero(self):
        import io
        import contextlib
        card = card_gen.build_chara_v2_card({
            "name": "TargetCard",
            "personality": "Identical personality",
        })
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fc:
            json.dump(card, fc)
            card_path = fc.name
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fi:
            json.dump({"personality": "Identical personality"}, fi)
            input_path = fi.name

        buf = io.StringIO()
        err_buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err_buf):
                ret = card_gen.main([
                    "--regenerate", "personality",
                    "--card", card_path,
                    "--input-file", input_path,
                ])
            self.assertNotEqual(ret, 0)
            self.assertIn("Failed to produce substantially different fields", err_buf.getvalue())
        finally:
            Path(card_path).unlink(missing_ok=True)
            Path(input_path).unlink(missing_ok=True)


class TaggedFallbackTest(unittest.TestCase):
    def test_parse_llm_response_tagged_fallback(self):
        tagged_text = """
Some conversational chatter before...
#NAME#
Tagged Girl
#DESCRIPTION#
A hacker girl living in seclusion.
#PERSONALITY#
Sassy and brilliant.
#FIRST_MESSAGE#
"Why are you bothering me now?"
#SCENARIO#
Abandoned server room.
"""
        parsed = card_gen._parse_llm_response(tagged_text)
        self.assertEqual(parsed.get("name"), "Tagged Girl")
        self.assertEqual(parsed.get("personality"), "Sassy and brilliant.")
        self.assertEqual(parsed.get("first_message"), '"Why are you bothering me now?"')

    def test_regenerate_with_tagged_response(self):
        def mock_llm(s: str, u: str) -> str:
            return (
                "#FIRST_MESSAGE#\n"
                "A dramatic mid-scene entrance with sparks flying!\n"
            )

        existing = {"first_message": "Old peaceful intro"}
        patch = card_gen.regenerate_fields(
            "Hacker",
            existing,
            ["first_message"],
            mock_llm,
        )
        self.assertIn("first_message", patch)
        self.assertEqual(
            patch["first_message"],
            "A dramatic mid-scene entrance with sparks flying!",
        )


if __name__ == "__main__":
    unittest.main()
