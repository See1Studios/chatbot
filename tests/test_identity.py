"""identity.py: identity comes from the instruction files, never from code.
Run: python3 -m unittest tests.test_identity  (from services/chatbot)
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import identity  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.orig = identity.WORKSPACE
        identity.WORKSPACE = self.ws
        identity._cache.clear()

    def tearDown(self):
        identity.WORKSPACE = self.orig
        identity._cache.clear()

    def write(self, name, text):
        (self.ws / name).write_text(text, encoding="utf-8")


class ParseTest(unittest.TestCase):
    def test_basic_quotes_comments_and_blank_lines(self):
        fm = identity.parse_frontmatter(
            '---\n# a comment\n\ntitle: 프로듀서   # trailing note\nvoice: "친근한 냥체(~냥, ✦)"\n'
            "persona: '냥피디'\nnoise line without colon\n---\n# body\n")
        self.assertEqual(fm, {"title": "프로듀서", "voice": "친근한 냥체(~냥, ✦)", "persona": "냥피디"})

    def test_value_containing_a_hash_without_space_is_kept(self):
        self.assertEqual(identity.parse_frontmatter("---\nvoice: C#\n---\n")["voice"], "C#")

    def test_no_or_unclosed_or_late_frontmatter_is_empty(self):
        self.assertEqual(identity.parse_frontmatter("# 제목\n---\ntitle: x\n---\n"), {})   # not at the very top
        self.assertEqual(identity.parse_frontmatter("---\ntitle: x\nno closing fence\n"), {})
        self.assertEqual(identity.parse_frontmatter(""), {})

    def test_bom_and_crlf(self):
        self.assertEqual(identity.parse_frontmatter("﻿---\r\ntitle: 프로듀서\r\n---\r\nbody"), {"title": "프로듀서"})


class IdentityTest(Base):
    def test_neutral_defaults_when_nothing_exists(self):
        self.assertEqual(identity.get_identity(),
                         {"title": "Assistant", "persona": "", "user_title": "사용자", "voice": "", "name": "Assistant"})

    def test_title_comes_from_agents_and_the_rest_from_persona(self):
        self.write("AGENTS.md", "---\ntitle: 프로듀서\n---\n# 헌장\n")
        self.write("PERSONA.md", "---\npersona: 냥피디\nuser_title: 실장님\nvoice: 친근한 냥체\n---\n# 페르소나\n")
        i = identity.get_identity()
        self.assertEqual((i["title"], i["persona"], i["user_title"], i["voice"], i["name"]),
                         ("프로듀서", "냥피디", "실장님", "친근한 냥체", "냥피디"))

    def test_each_key_is_read_only_from_its_own_file(self):
        # a title in PERSONA.md or a persona in AGENTS.md must be ignored
        self.write("AGENTS.md", "---\ntitle: 아트디렉터\npersona: 몰래\n---\n")
        self.write("PERSONA.md", "---\ntitle: 가짜\npersona: 루나\n---\n")
        i = identity.get_identity()
        self.assertEqual((i["title"], i["persona"]), ("아트디렉터", "루나"))

    def test_title_only_bot_has_no_persona_and_is_named_by_its_title(self):
        self.write("AGENTS.md", "---\ntitle: 테크디렉터\n---\n")
        self.assertEqual((identity.display_name(), identity.self_label(), identity.get_identity()["persona"]),
                         ("테크디렉터", "테크디렉터", ""))

    def test_self_label_joins_title_and_persona(self):
        self.write("AGENTS.md", "---\ntitle: 프로듀서\n---\n")
        self.write("PERSONA.md", "---\npersona: 냥피디\n---\n")
        self.assertEqual(identity.self_label(), "프로듀서 냥피디")

    def test_two_workspaces_two_identities(self):
        other = Path(tempfile.mkdtemp())
        (other / "AGENTS.md").write_text("---\ntitle: 아트디렉터\n---\n", encoding="utf-8")
        self.write("AGENTS.md", "---\ntitle: 테크디렉터\n---\n")
        first = identity.get_identity()["title"]
        identity.WORKSPACE = other
        second = identity.get_identity()["title"]
        self.assertEqual((first, second), ("테크디렉터", "아트디렉터"))

    def test_values_are_cleaned_and_capped(self):
        self.write("PERSONA.md", "---\nuser_title: " + "가" * 100 + "\npersona: 냥\x07\x1b피\n---\n")
        i = identity.get_identity()
        self.assertEqual(len(i["user_title"]), 20)
        self.assertNotIn("\x07", i["persona"])
        self.assertNotIn("\x1b", i["persona"])

    def test_edit_is_picked_up_without_restart(self):
        self.write("AGENTS.md", "---\ntitle: 하나\n---\n")
        self.assertEqual(identity.get_identity()["title"], "하나")
        time.sleep(0.01)
        self.write("AGENTS.md", "---\ntitle: 둘둘\n---\n")     # different size -> cache key changes
        self.assertEqual(identity.get_identity()["title"], "둘둘")

    def test_voice_phrase(self):
        self.assertEqual(identity.voice_phrase(), "")
        self.write("PERSONA.md", "---\nvoice: 차분한 존댓말\n---\n")
        self.assertEqual(identity.voice_phrase(), "차분한 존댓말로")
        self.assertEqual(identity.voice_phrase("이다"), "차분한 존댓말이다")


class ScriptSafetyTest(Base):
    def test_script_json_cannot_break_out_of_an_inline_script(self):
        self.write("AGENTS.md", "---\ntitle: </script><script>alert(1)</script>\n---\n")
        out = identity.script_json()
        for bad in ("<", ">", "</script"):
            self.assertNotIn(bad, out)
        self.assertEqual(json.loads(out)["title"], "</script><script>alert(1)</script>")   # round-trips intact

    def test_line_separators_are_escaped(self):
        self.write("PERSONA.md", "---\npersona: a b\n---\n")
        self.assertNotIn(" ", identity.script_json())


class SeedTest(Base):
    def test_seeds_only_when_missing_and_never_overwrites(self):
        tpl = Path(tempfile.mkdtemp()); (tpl / "PERSONA.md").write_text("template", encoding="utf-8")
        self.assertEqual(identity.seed_workspace_files(tpl, self.ws), ["PERSONA.md"])
        self.assertEqual((self.ws / "PERSONA.md").read_text(encoding="utf-8"), "template")
        self.write("PERSONA.md", "MY OWN PERSONA")
        self.assertEqual(identity.seed_workspace_files(tpl, self.ws), [])
        self.assertEqual((self.ws / "PERSONA.md").read_text(encoding="utf-8"), "MY OWN PERSONA")

    def test_shipped_template_is_neutral_and_parses(self):
        tpl = Path(identity.__file__).parent / "templates" / "PERSONA.md"
        fm = identity.parse_frontmatter(tpl.read_text(encoding="utf-8"))
        self.assertEqual((fm.get("persona"), fm.get("user_title")), ("", "사용자"))
        self.assertNotIn("냥피디", tpl.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
