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
from tests.page_source import i18n_prelude  # noqa: E402
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"
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
  line: msgQuoteLine('Kit', 'see you'),
  parsed: msgQuoteParse(msgQuoteLine('Kit', 'see you') + 'me too\\nbye'),
  parsedNoName: msgQuoteParse(msgQuoteLine('', 'just a line') + 'x'),
  notQuote: [msgQuoteParse('> just a quote'), msgQuoteParse('hello')],
  snippet: [msgSnippet('  a\\n b  '), msgSnippet('x'.repeat(100)).length, msgSnippet('x'.repeat(100)).slice(-1)],
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
        p = subprocess.run(["node", "-e", i18n_prelude() + HARNESS, str(STATIC / "app-msgmenu.js")], capture_output=True, text=True, timeout=30)
        assert p.returncode == 0, p.stderr
        cls.o = json.loads(p.stdout.strip().splitlines()[-1])

    def test_which_bubbles_it_serves(self):
        # a character's bubble or narration, the user's line and action line; not a whole message, nothing else
        self.assertEqual(self.o["kind"], ["theirs", "theirs", "mine", "act", "", ""])

    def test_rows(self):
        self.assertEqual(self.o["idle"], [["acts", "reply", "copy"], ["reply", "copy", "resend"], ["reply", "copy", "resend"]])
        self.assertEqual(self.o["busy"], [["reply", "copy"], ["reply", "copy"], ["reply", "copy"]])   # a turn is running
        self.assertEqual(self.o["room"], [["reply", "copy"], ["reply", "copy", "resend"], ["reply", "copy"]])  # plain text only

    def test_the_acts_differ_by_room(self):
        self.assertEqual(len(self.o["actsWork"]), 4)
        self.assertEqual(len(self.o["actsPrivate"]), 4)
        self.assertNotEqual(self.o["actsWork"], self.o["actsPrivate"])

    def test_send_again_keeps_an_action_an_action(self):
        self.assertEqual(self.o["resend"], ["hi", "/act nods"])

    def test_the_failed_mark_goes_on_the_newest_matching_bubble(self):
        self.assertEqual(self.o["failed"], [2, 1, -1, -1])

    def test_a_reply_travels_as_a_quote_line_in_the_text(self):
        # every brain reads it as what it is, the server needs nothing, the record keeps it as sent
        self.assertEqual(self.o["line"], "> Kit: see you\n\n")
        self.assertEqual(self.o["parsed"], {"name": "Kit", "snippet": "see you", "rest": "me too\nbye"})
        self.assertEqual(self.o["parsedNoName"], {"name": "", "snippet": "just a line", "rest": "x"})
        self.assertEqual(self.o["notQuote"], [None, None])   # a quote needs the blank line after it
        self.assertEqual(self.o["snippet"], ["a b", 80, "\u2026"])

    def test_the_reply_hooks(self):
        self.assertIn("if (typeof msgQuoteDraw === 'function') msgQuoteDraw(div);", (STATIC / "app-messages.js").read_text(encoding="utf-8"))
        # a command or an action goes as it is: "/act" must stay first to be an action
        self.assertIn("if (!t.trim().startsWith('/')) inputEl.value = msgQuoteLine(msgReply.name, msgReply.snippet) + t;", SRC)
        self.assertIn("msgReplyClear()", (STATIC / "app-shell.js").read_text(encoding="utf-8"))

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
