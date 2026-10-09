"""#896: SillyTavern card fields keep their meaning. PE's private-mode rules live in extensions.chatbot.private_rules
(the ST system_prompt is read only for a card not moved yet), PE's working notes in extensions.chatbot.work.instructions
(a work layer of its own, never in a private bundle); the move goes through the settings store, a version kept.
Run: engine/run-tests.sh test_card_pe_fields
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import characters  # noqa: E402
from character_settings import migrate as M  # noqa: E402
from character_settings import store as S  # noqa: E402


def card(**data):
    base = {"name": "Kit", "description": "who", "personality": "warm", "system_prompt": "",
            "extensions": {"chatbot": {"display": {"user_title": "coach"}}}}
    base.update(data)
    return {"spec": "chara_card_v2", "spec_version": "2.0", "data": base}


class Reading(unittest.TestCase):
    def test_private_rules_come_from_pe_first_and_the_st_field_as_before(self):
        c = card(system_prompt="old rules")
        self.assertEqual(characters.private_text(c), "old rules", "a card not moved behaves as before")
        c["data"]["extensions"]["chatbot"]["private_rules"] = "pe rules"
        self.assertEqual(characters.private_text(c), "pe rules")

    def test_work_notes_stay_out_of_the_persona(self):
        # they reach work bundles as their own layer (test_context_layers); the persona is in private bundles too
        c = card()
        c["data"]["extensions"]["chatbot"]["work"] = {"instructions": "harness notes"}
        self.assertNotIn("harness notes", characters.persona_text(c))


class Moving(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.ws = self.data / "workspace"
        self.cid = characters.new_id()
        (self.ws / "characters" / self.cid).mkdir(parents=True)
        (self.ws / "characters" / self.cid / "card.json").write_text(
            json.dumps(card(system_prompt="# Private rules\nx", first_mes="hi")), encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_the_rules_move_once_with_a_version_kept_and_nothing_else_changes(self):
        before = characters.private_text(characters.load(self.cid, self.ws))
        self.assertEqual(M.move_private_rules(self.cid, self.ws), ["card.system_prompt", "pe.private_rules"])
        c = characters.load(self.cid, self.ws)
        self.assertEqual(c["data"]["system_prompt"], "")
        self.assertEqual(characters.private_text(c), before, "the character hears the same rules")
        self.assertEqual(c["data"]["first_mes"], "hi")
        self.assertEqual(len(S.versions(self.cid, "pe.private_rules", self.ws)), 1)
        self.assertEqual(M.move_private_rules(self.cid, self.ws), [], "moved once")

    def test_pe_fields_are_settings_too(self):
        S.patch(self.cid, {"pe.work_instructions": "notes"}, self.ws)
        fields = {f["key"]: f for f in S.read(self.cid, self.ws)}
        self.assertEqual(fields["pe.work_instructions"]["value"], "notes")
        self.assertEqual(fields["pe.work_instructions"]["tab"], "settings")
        self.assertEqual((fields["pe.private_rules"]["tab"], fields["pe.private_rules"]["sensitive"]), ("relationship", True))
        self.assertEqual(characters.load(self.cid, self.ws)["data"]["extensions"]["chatbot"]["display"],
                         {"user_title": "coach"}, "the rest of the PE fields stay")


if __name__ == "__main__":
    unittest.main()
