"""Developer-edition character delete: one chosen folder, nothing else.

Run: python3 -m unittest tests.test_dev_delete_character
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import characters  # noqa: E402


class DevDeleteCharacterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.home = characters.new_id()
        self.other = characters.new_id()
        characters.save(self.home, characters.new_card("Home"), self.ws)
        characters.save(self.other, characters.new_card("Guest"), self.ws)
        characters.save_team({"default": self.home, "members": {self.home: [], self.other: ["staff"]}}, self.ws)
        folder = self.ws / "characters" / self.other
        (folder / "memory.md").write_text("remember\n", encoding="utf-8")
        (folder / "visual.md").write_text("look\n", encoding="utf-8")
        (folder / "state.json").write_text("{}\n", encoding="utf-8")
        (folder / "brain-override.json").write_text("{}\n", encoding="utf-8")
        self.dialogs = self.tmp / "dialogs"
        self.dialogs.mkdir()
        self.dialog = self.dialogs / (self.other + ".log.jsonl")
        self.dialog.write_text("keep\n", encoding="utf-8")
        self.sessions = self.tmp / "sessions"
        self.sessions.mkdir()
        (self.sessions / "meta.json").write_text("{}\n", encoding="utf-8")
        self.rooms = self.ws / "rooms"
        self.rooms.mkdir()
        (self.rooms / "room.json").write_text("{}\n", encoding="utf-8")
        outside = self.tmp / "outside"
        outside.mkdir()
        self.secret = outside / "secret.txt"
        self.secret.write_text("no\n", encoding="utf-8")
        (folder / "linked").symlink_to(self.secret)

    def _gone(self):
        self.assertFalse((self.ws / "characters" / self.other).exists())
        self.assertTrue((self.ws / "characters" / self.home / "card.json").is_file())
        self.assertEqual(self.dialog.read_text(encoding="utf-8"), "keep\n")
        self.assertTrue((self.sessions / "meta.json").is_file())
        self.assertTrue((self.rooms / "room.json").is_file())
        self.assertEqual(self.secret.read_text(encoding="utf-8"), "no\n")
        team = json.loads((self.ws / "team.json").read_text(encoding="utf-8"))
        self.assertEqual(team["default"], self.home)
        self.assertNotIn(self.other, team["members"])
        self.assertIn(self.home, team["members"])

    def test_chosen_folder_only(self):
        status, payload = characters.dev_delete(self.other, {"confirm": True}, self.ws, "dev")
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], self.other)
        self._gone()

    def test_home_character_stays(self):
        status, payload = characters.dev_delete(self.home, {"confirm": True}, self.ws, "dev")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "home-character")
        self.assertTrue((self.ws / "characters" / self.home / "card.json").is_file())
        self.assertTrue((self.ws / "characters" / self.other / "card.json").is_file())

    def test_shipped_edition_refuses(self):
        status, payload = characters.dev_delete(self.other, {"confirm": True}, self.ws, "shipped")
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "developer-edition-only")
        self.assertTrue((self.ws / "characters" / self.other / "memory.md").is_file())

    def test_confirm_must_be_json_true(self):
        for body in ({}, {"confirm": "true"}, {"confirm": 1}, None):
            status, payload = characters.dev_delete(self.other, body, self.ws, "dev")
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "confirm-required")
        self.assertTrue((self.ws / "characters" / self.other / "card.json").is_file())

    def test_bad_id_and_missing_and_symlink(self):
        status, payload = characters.dev_delete("../" + self.other, {"confirm": True}, self.ws, "dev")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "not-a-character-id")
        missing = characters.new_id()
        status, payload = characters.dev_delete(missing, {"confirm": True}, self.ws, "dev")
        self.assertEqual(status, 404)
        link_id = characters.new_id()
        (self.ws / "characters" / link_id).symlink_to(self.tmp / "outside")
        status, payload = characters.dev_delete(link_id, {"confirm": True}, self.ws, "dev")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "no-such-character")
        self.assertTrue(self.secret.is_file())
        self.assertTrue((self.ws / "characters" / self.other).is_dir())


class DevDeletePageTest(unittest.TestCase):
    def test_button_is_dev_mode_only_and_confirms(self):
        js = (ROOT / "static" / "app-dev-delete.js").read_text(encoding="utf-8")
        shell = (ROOT / "static" / "app-shell.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "shell.css").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("function shellDevDeleteButton", js)
        self.assertIn("shell-dev shell-dev-delete", js)
        self.assertIn("shellDevOn()", js)
        self.assertIn("window.confirm", js)
        self.assertIn("/dev-delete", js)
        self.assertIn("confirm: true", js)
        self.assertNotIn("dialogs", js)
        self.assertNotIn("unsummon", js)
        self.assertIn("shellDevDeleteButton(panel, c)", shell)
        self.assertIn("html.shell2 body:not(.dev-mode) .shell-dev{display:none}", css)
        self.assertIn(".shell-dev-delete{margin-top:1rem}", css)
        self.assertLess(html.index('src="./app-shell.js'), html.index('src="./app-dev-delete.js'))
        self.assertLess(html.index('src="./app-dev-delete.js'), html.index('src="./app.js'))
        self.assertIn('"/api/characters/*/dev-delete"', server)
        self.assertIn("EDITION", server)
