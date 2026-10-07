"""HANDOFF_BOARD_v1: handoffs on the page. GET /api/handoffs lists every open handoff and those closed in the last
BOARD_RECENT_SEC; the page draws them above the work cards with a cancel button on the open ones, and names every
state. The REAL page functions run in node against stubs.
Run: python3 -m unittest tests.test_handoff_bar  (from services/chatbot)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
STATIC = ROOT / "static"
sys.path.insert(0, str(ENGINE))
import dialog_handoff as H  # noqa: E402


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = mock.patch.dict(os.environ, {"CHATBOT_HANDOFFS_FILE": str(self.tmp / "handoffs.jsonl")})
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def row(self, hid, state, at, **kw):
        H._append({"id": hid, "state": "sent", "at": at, "from": "a", "to": "b", "role": "dev", "task": "do %d" % hid})
        if state != "sent":
            H._append(dict({"id": hid, "state": state, "state_at": at + 5}, **kw))

    def test_open_ones_and_the_just_closed_newest_first(self):
        now = 10000.0
        self.row(1, "done", now - H.BOARD_RECENT_SEC - 100, result="old")
        self.row(2, "done", now - 60, result="fixed it\nmore")
        self.row(3, "running", now - 5000, started=now - 5000)
        self.row(4, "sent", now - 10)
        with mock.patch.object(H, "_title", lambda cid, role="": role.upper()):
            got = H.board(now)
        self.assertEqual([x["id"] for x in got], [4, 3, 2])
        done = got[2]
        self.assertEqual((done["open"], done["result"], done["role"]), (False, "fixed it\nmore", "DEV"),
                         "the result as written: no line is picked as its summary")
        self.assertTrue(got[1]["open"])
        self.assertEqual(got[1]["since"], now - 5000)
        self.assertEqual(got[0]["task"], "do 4")

    def test_the_route_serves_it(self):
        src = (ENGINE / "server.py").read_text(encoding="utf-8")
        self.assertIn('("/api/handoffs", _handoffs)', src)


HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const log = { posts: [], notices: [] };
const doc = { el: {} };
function node(tag, cls, text) { return { tag, className: cls || '', textContent: text || '', children: [], style: {},
  appendChild(c) { this.children.push(c); return c; }, addEventListener(e, f) { this['on' + e] = f; } }; }
const env = { obsNode: node, workElapsed: s => Math.round(s) + 's', confirm: () => true, obsErrorText: String, tr: k => k,
  addNotice: (k, t) => log.notices.push(k + ':' + t),
  api: async (p, o) => { if (o && o.method === 'POST') log.posts.push(p); return { handoffs: [] }; },
  document: { getElementById: () => null } };
const names = Object.keys(env);
const m = new Function(...names, src + '; return { handoffCard, cancelHandoff };')(...names.map(k => env[k]));
const open = m.handoffCard({ id: 7, state: 'running', open: true, from: 'Lead', to: 'Kit', role: 'Dev', task: 'fix it', since: 0, result: '' });
const closed = m.handoffCard({ id: 8, state: 'partial', open: false, from: 'Lead', to: 'Kit', role: 'Dev', task: 'read', since: 0, result: 'note first\n2 of 10' });
const buttons = c => c.children[0].children.filter(x => x.tag === 'button').length;
(async () => {
  await m.cancelHandoff({ id: 7 }, { disabled: false });
  console.log(JSON.stringify({ openButtons: buttons(open), closedButtons: buttons(closed),
    closedTag: closed.children[1].tag, closedResult: closed.children[1].children[1].textContent,
    posts: log.posts, badge: open.children[0].children[2].textContent }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-handoffs.js")], capture_output=True, text=True,
                           timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_an_open_handoff_has_a_cancel_button_and_a_closed_one_its_result_as_written(self):
        self.assertEqual((self.o["openButtons"], self.o["closedButtons"]), (1, 0))
        self.assertEqual((self.o["closedTag"], self.o["closedResult"]), ("details", "note first\n2 of 10"))

    def test_cancel_posts_to_the_handoffs_cancel_route(self):
        self.assertEqual(self.o["posts"], ["/api/handoffs/7/cancel"])

    def test_every_state_has_a_name_in_every_language(self):
        self.assertEqual(self.o["badge"], "handoff.state.running")   # the badge is the state's catalog key
        for cat in sorted((STATIC / "i18n").glob("*.json")):
            keys = json.loads(cat.read_text(encoding="utf-8"))
            self.assertEqual({s for s in H.OPEN + H.CLOSED if "handoff.state." + s not in keys}, set(), cat.name)

    def test_it_is_drawn_above_the_work_cards_and_refreshed_with_them(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('id="handoffBar"'), html.index('id="workBar"'))
        self.assertLess(html.index('src="./app-evolution.js'), html.index('src="./app-handoffs.js'))
        evo = (STATIC / "app-evolution.js").read_text(encoding="utf-8")
        load = evo[evo.index("async function loadWork"):]
        self.assertIn("loadHandoffs()", load[:400])


if __name__ == "__main__":
    unittest.main()
