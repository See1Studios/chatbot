"""Macros in cards, lorebooks and role packs (CARD_MACROS_v1, characters.render_macros): {{user}} and {{char}} as in
SillyTavern and the card spec (imported cards use them), {{title}}, {{default}} and {{role:<id>}} for the team. They are
resolved when a prompt is rendered -- the files keep them -- and the engine names no role itself.
Run: engine/run-tests.sh test_card_macros
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import characters as C  # noqa: E402
import identity  # noqa: E402
import instructions as I  # noqa: E402


class Macros(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        (self.ws / "memory").mkdir()
        (self.ws / "memory" / "MEMORY.md").write_text("# Memory\n- the {{user}} macro is literal here\n", encoding="utf-8")
        (self.ws / "AGENTS.md").write_text("charter", encoding="utf-8")
        (self.ws / "roles" / "build").mkdir(parents=True)
        (self.ws / "roles" / "build" / "ROLE.md").write_text(
            "---\ntitle: Builder\n---\nYou build; {{default}} confirms. Plans go to {{role:design}}.", encoding="utf-8")
        (self.ws / "roles" / "design").mkdir(parents=True)
        (self.ws / "roles" / "design" / "ROLE.md").write_text("---\ntitle: Designer\n---\nYou design.", encoding="utf-8")
        self.boss, self.kit = sorted(C.new_id() for _ in range(2))
        C.save(self.boss, C.new_card("Boss", display={"user_title": "Coach"}), self.ws)
        card = C.new_card("Kit", description="{{char}} adores {{user}}. {{char}} is the {{title}}.",
                          display={"user_title": "Master"})
        card["data"]["system_prompt"] = "{{char}} whispers to {{User}}."
        C.save(self.kit, card, self.ws)
        C.save_team({"default": self.boss, "members": {self.boss: [], self.kit: ["build"]}}, self.ws)
        self.saved = (I.WORKSPACE, I.MEMORY_FILE, identity.WORKSPACE)
        I.WORKSPACE, I.MEMORY_FILE, identity.WORKSPACE = self.ws, self.ws / "memory" / "MEMORY.md", self.ws

    def tearDown(self):
        I.WORKSPACE, I.MEMORY_FILE, identity.WORKSPACE = self.saved
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_each_macro_resolves_from_the_data(self):
        r = lambda t: C.render_macros(t, self.kit, self.ws)  # noqa: E731
        self.assertEqual(r("{{char}}/{{user}}/{{title}}/{{default}}/{{role:design}}"), "Kit/Master/Builder/Boss/Designer")
        self.assertEqual(r("{{ USER }} and {{Char}}"), "Master and Kit", "case and spaces as SillyTavern allows")
        self.assertEqual(r("{{role:nope}} {{random}} {user} {{"), "{{role:nope}} {{random}} {user} {{",
                         "what cannot be resolved stays as written")

    def test_a_character_without_its_own_address_uses_the_default_s(self):
        other = C.new_id()
        C.save(other, C.new_card("Plain"), self.ws)
        self.assertEqual(C.render_macros("{{user}}", other, self.ws), "Coach")

    def test_the_work_bundle_resolves_card_and_role_text_but_not_memory(self):
        text = I.build_instruction_bundle(character=self.kit)["text"]
        self.assertIn("Kit adores Master. Kit is the Builder.", text)
        self.assertIn("You build; Boss confirms. Plans go to Designer.", text)
        self.assertIn("the {{user}} macro is literal here", text, "memory is the user's record, not a template")

    def test_the_private_bundle_and_the_worker_persona_resolve_too(self):
        text = I.build_instruction_bundle(mode="private", character=self.kit)["text"]
        self.assertIn("Kit whispers to Master.", text)
        self.assertIn("Kit adores Master.", identity.persona_body("build"))

    def test_the_files_keep_their_macros(self):
        I.build_instruction_bundle(character=self.kit)
        self.assertIn("{{char}} adores {{user}}", C.load(self.kit, self.ws)["data"]["description"])

    def test_a_role_less_character_is_told_who_delegates_by_name(self):
        C.save_team({"default": self.boss, "members": {self.boss: [], self.kit: []}}, self.ws)
        text = I.build_instruction_bundle(character=self.kit)["text"]
        self.assertIn("plans and handing out work are Boss's", text)
        self.assertNotIn("{{default}}", text)


if __name__ == "__main__":
    unittest.main()
