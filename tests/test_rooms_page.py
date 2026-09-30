"""Group rooms, the page half (static/app-rooms.js, plan evt/E-2): the @mention being typed and its completion, how a
message shows (the user's own vs a member's), and the wiring (tray button, page includes). The REAL functions run in
node. Run: python3 -m unittest tests.test_rooms_page  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const { roomMentionAt, roomApplyMention, roomMessageView, ROOM_TEXT } =
  new Function(src + '; return { roomMentionAt, roomApplyMention, roomMessageView, ROOM_TEXT };')();
const names = { a: 'Kit', b: 'Kiki', c: 'Ari' };
console.log(JSON.stringify({
  ki: roomMentionAt('hello @Ki', 9, names),
  none: roomMentionAt('mail me@x', 9, names),
  start: roomMentionAt('@', 1, names),
  apply: roomApplyMention('hi @ki there', 6, 'Kiki'),
  applyEnd: roomApplyMention('hi @ki', 6, 'Kiki'),
  user: roomMessageView({ who: 'user', text: 'yo' }, names, '코치'),
  member: roomMessageView({ who: 'c', text: 'hey' }, names, '코치'),
  labels: ['natural', 'list', 'manual'].every(k => ROOM_TEXT[k]),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RoomsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-rooms.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_mention_being_typed_offers_matching_members(self):
        self.assertEqual((self.o["ki"]["query"], sorted(self.o["ki"]["options"]), self.o["ki"]["start"]), ("ki", ["a", "b"], 6))
        self.assertIsNone(self.o["none"], "an @ inside a word is not a mention")
        self.assertEqual(sorted(self.o["start"]["options"]), ["a", "b", "c"])

    def test_picking_a_member_completes_the_mention(self):
        self.assertEqual(self.o["apply"], {"text": "hi @Kiki there", "caret": 9}, "no doubled space")
        self.assertEqual(self.o["applyEnd"], {"text": "hi @Kiki ", "caret": 9})

    def test_the_user_s_own_message_and_a_member_s(self):
        self.assertEqual(self.o["user"], {"mine": True, "who": "코치", "text": "yo", "id": ""})
        self.assertEqual(self.o["member"], {"mine": False, "who": "Ari", "text": "hey", "id": "c"})
        self.assertTrue(self.o["labels"])


class Wiring(unittest.TestCase):
    def test_the_page_loads_it_and_the_tray_opens_it(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("./app-rooms.js", page)
        self.assertIn("./rooms.css", page)
        self.assertLess(page.index("./app-rooms.js"), page.index("./app.js?"))
        self.assertIn("openRooms();", (STATIC / "app-characters.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
