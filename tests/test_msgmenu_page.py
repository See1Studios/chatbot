"""The message menu (static/app-msgmenu.js, plan ux/S6): which bubbles it serves, its rows for each (a row of
short acts on a character's lines, copy, send again -- none of that while a turn runs or, for acts and actions, in
a group room), what "send again" puts in the box, which bubble a waiting retry marks, and the wiring. The REAL
functions run in node against stubs.
Run: python3 -m unittest tests.test_msgmenu_page  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
SRC = (STATIC / "app-msgmenu.js").read_text(encoding="utf-8")

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const el = (...cls) => ({ classList: { contains: c => cls.includes(c) } });
eval(src + `;
const kinds = ['theirs', 'mine', 'act'];
const o = {
  kind: [el('md-say'), el('md-narr'), el('msg', 'user'), el('msg', 'action'), el('msg', 'assistant'), null].map(msgKind),
  idle: kinds.map(k => msgMenuItems({ kind: k, busy: false, room: false, mode: 'work' }).map(r => r.k)),
  busy: kinds.map(k => msgMenuItems({ kind: k, busy: true, room: false, mode: 'work' }).map(r => r.k)),
  room: kinds.map(k => msgMenuItems({ kind: k, busy: false, room: true, mode: 'work' }).map(r => r.k)),
  actsWork: msgMenuItems({ kind: 'theirs', busy: false, room: false, mode: 'work' })[0].acts,
  actsPrivate: msgMenuItems({ kind: 'theirs', busy: false, room: false, mode: 'private' })[0].acts,
  resend: [msgResendText('mine', 'hi'), msgResendText('act', 'nods')],
  failed: [
    msgFailedIndex(['a', 'b', 'a'], 'a'),
    msgFailedIndex(['a', 'nods'], '/act nods'),
    msgFailedIndex(['a'], 'zzz'),
    msgFailedIndex(['a'], ''),
  ],
};
console.log(JSON.stringify(o));`);
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class MsgMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-msgmenu.js")], capture_output=True, text=True, timeout=30)
        assert p.returncode == 0, p.stderr
        cls.o = json.loads(p.stdout.strip().splitlines()[-1])

    def test_which_bubbles_it_serves(self):
        # a character's bubble or narration, the user's line and action line; not a whole message, nothing else
        self.assertEqual(self.o["kind"], ["theirs", "theirs", "mine", "act", "", ""])

    def test_rows(self):
        self.assertEqual(self.o["idle"], [["acts", "copy"], ["copy", "resend"], ["copy", "resend"]])
        self.assertEqual(self.o["busy"], [["copy"], ["copy"], ["copy"]])          # a turn is running: copy only
        self.assertEqual(self.o["room"], [["copy"], ["copy", "resend"], ["copy"]])  # a room takes plain text only

    def test_the_acts_differ_by_room(self):
        self.assertEqual(len(self.o["actsWork"]), 4)
        self.assertEqual(len(self.o["actsPrivate"]), 4)
        self.assertNotEqual(self.o["actsWork"], self.o["actsPrivate"])

    def test_send_again_keeps_an_action_an_action(self):
        self.assertEqual(self.o["resend"], ["hi", "/act nods"])

    def test_the_failed_mark_goes_on_the_newest_matching_bubble(self):
        self.assertEqual(self.o["failed"], [2, 1, -1, -1])

    def test_no_delete_yet(self):
        # deleting is its own decision (what it erases: the record, the brain's memory) -- not offered for now
        self.assertNotIn("'delete'", SRC)

    def test_wiring(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('src="./app-shell.js'), html.index('src="./app-msgmenu.js'))
        self.assertLess(html.index('src="./app-msgmenu.js'), html.index('src="./app.js'))
        self.assertIn("msgMenuInit()", (STATIC / "app-shell.js").read_text(encoding="utf-8"))
        self.assertIn("if (sel && !sel.isCollapsed && el.contains(sel.anchorNode)) return;", SRC)   # a selection keeps the browser's menu
        css = (STATIC / "shell.css").read_text(encoding="utf-8")
        self.assertIn(".shell-msg-menu.sheet{", css)


if __name__ == "__main__":
    unittest.main()
