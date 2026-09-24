"""identity.py: identity comes from the charter and the default character's card, never from code (CARD_ONLY_v1).
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

    def set_title(self, title):
        """The job title the user gives the default character (TITLE_DISPLAY_v1; the charter holds none)."""
        self._title = title
        import characters
        cid = characters.default_character(self.ws)
        if not cid:
            self.write_default()
            return
        card = characters.load(cid, self.ws)
        characters.ext(card) or card["data"].setdefault("extensions", {}).setdefault(characters.EXT, {})
        characters.ext(card).setdefault("display", {})["title"] = title
        characters.save(cid, card, self.ws)

    def write_default(self, name="", user_title="", voice="", title="", private="", description=""):
        """The team's default character (what PERSONA.md and PRIVATE.md used to be)."""
        import characters
        title = title or getattr(self, "_title", "")
        cid = characters.new_id()
        display = {k: v for k, v in (("user_title", user_title), ("voice", voice), ("title", title)) if v}
        card = characters.new_card(name, description=description, display=display)
        card["data"]["system_prompt"] = private
        characters.save(cid, card, self.ws)
        characters.save_team({"default": cid, "members": {cid: []}}, self.ws)
        return cid

    def write_character(self, role, name, description="", title="", voice="", cid=None):
        import characters
        cid = cid or characters.new_id()
        display = {k: v for k, v in (("title", title), ("voice", voice)) if v}
        characters.save(cid, characters.new_card(name, description=description, display=display), self.ws)
        team = characters.load_team(self.ws)                # roles are the roster's (TEAM_ROLES_v1)
        team["members"][cid] = [role]
        characters.save_team(team, self.ws)
        return cid


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

    def test_title_comes_from_agents_and_the_rest_from_the_card(self):
        self.set_title('프로듀서')
        self.write_default("냥피디", user_title="실장님", voice="친근한 냥체")
        i = identity.get_identity()
        self.assertEqual((i["title"], i["persona"], i["user_title"], i["voice"], i["name"]),
                         ("프로듀서", "냥피디", "실장님", "친근한 냥체", "냥피디"))

    def test_each_key_is_read_only_from_its_own_source(self):
        # the charter holds no identity; the card's own title is the job title (TITLE_DISPLAY_v1)
        self.set_title('아트디렉터')
        self.write_default("루나")
        i = identity.get_identity()
        self.assertEqual((i["title"], i["persona"]), ("아트디렉터", "루나"))
        self.write_default("루나", title="감독")
        self.assertEqual(identity.get_identity()["title"], "감독")

    def test_title_only_bot_has_no_persona_and_is_named_by_its_title(self):
        self.set_title('테크디렉터')
        self.assertEqual((identity.display_name(), identity.self_label(), identity.get_identity()["persona"]),
                         ("테크디렉터", "테크디렉터", ""))

    def test_self_label_joins_title_and_persona(self):
        self.set_title('프로듀서')
        self.write_default("냥피디")
        self.assertEqual(identity.self_label(), "프로듀서 냥피디")

    def test_two_workspaces_two_identities(self):
        other = Path(tempfile.mkdtemp())
        import characters
        oid = characters.new_id()
        characters.save(oid, characters.new_card("", display={"title": "아트디렉터"}), other)
        characters.save_team({"default": oid, "members": {oid: []}}, other)
        self.set_title('테크디렉터')
        first = identity.get_identity()["title"]
        identity.WORKSPACE = other
        second = identity.get_identity()["title"]
        self.assertEqual((first, second), ("테크디렉터", "아트디렉터"))

    def test_values_are_cleaned_and_capped(self):
        self.write_default("냥\x07\x1b피", user_title="가" * 100)
        i = identity.get_identity()
        self.assertEqual(len(i["user_title"]), 20)
        self.assertNotIn("\x07", i["persona"])
        self.assertNotIn("\x1b", i["persona"])

    def test_edit_is_picked_up_without_restart(self):
        self.set_title('하나')
        self.assertEqual(identity.get_identity()["title"], "하나")
        time.sleep(0.01)
        self.set_title('둘둘')     # different size -> cache key changes
        self.assertEqual(identity.get_identity()["title"], "둘둘")

    def test_voice_phrase(self):
        self.assertEqual(identity.voice_phrase(), "")
        self.write_default("", voice="차분한 존댓말")
        self.assertEqual(identity.voice_phrase(), "차분한 존댓말로")
        self.assertEqual(identity.voice_phrase("이다"), "차분한 존댓말이다")


class ScriptSafetyTest(Base):
    def test_script_json_cannot_break_out_of_an_inline_script(self):
        self.set_title('</script><script>alert(1)</script>')
        out = identity.script_json()
        for bad in ("<", ">", "</script"):
            self.assertNotIn(bad, out)
        self.assertEqual(json.loads(out)["title"], "</script><script>alert(1)</script>")   # round-trips intact

    def test_line_separators_are_escaped(self):
        self.write_default("a\u2028b")
        self.assertNotIn(" ", identity.script_json())


class SeedTest(Base):
    def test_a_new_install_starts_with_one_neutral_card_as_the_default(self):
        import characters
        (self.ws / "roles" / "pd").mkdir(parents=True)
        (self.ws / "roles" / "pd" / "role.md").write_text("---\ntitle: PD\n---\nPlan and delegate.\n", encoding="utf-8")
        self.assertEqual(identity.seed_workspace_files(workspace=self.ws), ["card"])
        cid = characters.default_character(self.ws)
        self.assertTrue(cid)
        self.assertEqual(characters.roles_of(cid, self.ws), ["pd"])
        self.assertEqual((identity.get_identity()["persona"], identity.get_identity()["user_title"]), ("", "사용자"))
        self.assertEqual(identity.get_identity()["title"], "PD")          # no title on the card: the role pack's
        card = characters.load(cid, self.ws)
        card["data"]["name"] = "MY OWN"
        characters.save(cid, card, self.ws)
        self.assertEqual(identity.seed_workspace_files(workspace=self.ws), [])   # an existing character is never touched
        self.assertEqual(identity.get_identity()["persona"], "MY OWN")

    def test_private_rules_and_body_come_from_the_card(self):
        self.write_default("하나", voice="밝게", private="# 사적 모드\nrule one", description="## Identity\nx")
        self.assertEqual(identity.private_rules(), "# 사적 모드\nrule one")
        self.assertEqual(identity.get_identity()["voice"], "밝게")
        self.assertIn("## Identity\nx", identity.persona_body())

    def test_nothing_without_a_card(self):
        self.assertEqual((identity.private_rules(), identity.persona_body()), ("", ""))

    def test_the_charter_names_no_title(self):
        # TITLE_DISPLAY_v1: a job title is the user's display value; the charter defines no name
        charter = (Path(identity.__file__).parent / "data" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(identity.parse_frontmatter(charter).get("title"), None)

    def test_shipped_template_is_a_neutral_card(self):
        import characters
        tpl = json.loads((Path(identity.__file__).parent / "templates" / "character.json").read_text(encoding="utf-8"))
        self.assertEqual(tpl["spec"], characters.SPEC)
        self.assertEqual(tpl["data"]["name"], "")
        self.assertNotIn("냥", json.dumps(tpl, ensure_ascii=False))
        self.assertNotIn("role", characters.ext(tpl))


class RoleTest(Base):
    """Another character (characters/<id>/card.json), asked by role or id, e.g. the staff member of delegation."""

    def test_a_character_by_role_or_id_and_the_title_fallback(self):
        self.set_title('프로듀서')
        self.write_default("하나", voice="밝게", user_title="주인님", description="body one")
        cid = self.write_character("reviewer", "두리", "a curt reviewer", voice="새침하게")
        for ref in ("reviewer", cid):
            r = identity.get_identity(ref)
            self.assertEqual((r["persona"], r["voice"], r["title"], r["name"], r["user_title"]),
                             ("두리", "새침하게", "프로듀서", "두리", "주인님"))
        self.assertEqual(identity.get_identity()["persona"], "하나")
        self.assertEqual(identity.persona_body("reviewer"), "a curt reviewer")
        self.write_character("reviewer", "두리", title="QA", cid=cid)
        self.assertEqual(identity.self_label("reviewer"), "QA 두리")

    def test_missing_character_is_neutral(self):
        r = identity.get_identity("reviewer")
        self.assertEqual(r["persona"], "")
        self.assertEqual(identity.persona_body("reviewer"), "")

    def test_role_must_be_an_id(self):
        for bad in ("../AGENTS", "Reviewer", "a/b", "x" * 40):
            with self.assertRaises(ValueError):
                identity.persona_file(bad)


if __name__ == "__main__":
    unittest.main()
