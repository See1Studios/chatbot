"""inbox/E (D8, D12): in a character's work window, what a coworker said to it shows as the coworker's own face bubble,
what it did as a centre stage direction, and what the character sent as one "-> name" line, placed by time; never
twice, never in a private talk or a meeting room's screen. The host serves the window its dms and, when the tool
server says one was sent, pushes it to both coworkers' windows. The page's REAL functions run in node.
Run: python3 -m unittest tests.test_office_page  (from services/chatbot)
"""
import json
import os
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
os.environ.setdefault("CHATBOT_EVENTS_DIR", tempfile.mkdtemp())   # never the live mailbox
os.environ.setdefault("CHATBOT_DIALOGS_DIR", tempfile.mkdtemp())  # nor the live dialogs

PAGE = r"""
const mk = () => ({ dataset: {}, style: { setProperty(k, v) { this[k] = v; } }, kids: [],
  insertBefore(c) { this.kids.unshift(c); return c; } });
const drawn = [];
const logEl = { querySelectorAll: (sel) => drawn.map(d => d.node).filter(n => n.dataset.office) };
const addChat = (role, text, isFinal, q, btw, prepend, usage, dur, sys, ts) => {
  const n = mk(); drawn.push({ role, text, ts, node: n }); return n; };
const roomEl = (tag, cls, text) => ({ cls, text });
let runs = 0; const roomMarkRuns = () => { runs++; };
let roomOpen = ''; const roomOpenId = () => roomOpen;
let sessionMode = 'work', sessionCharacter = 'b', archiveBrowse = false;
const BASE_PATH = '';
const calls = [];
const api = async (path) => { calls.push(path); return { messages: [
  { dialog_id: 'dm:a:b', n: 1, ts: 10, who: 'a', who_name: 'Nono', to_name: 'Lili', kind: 'say', text: 'check the build?', mine: false },
  { dialog_id: 'dm:a:b', n: 2, ts: 11, who: 'a', who_name: 'Nono', to_name: 'Lili', kind: 'action', text: 'sets a coffee down', mine: false },
  { dialog_id: 'dm:a:b', n: 3, ts: 12, who: 'b', who_name: 'Lili', to_name: 'Nono', kind: 'say', text: 'on it', mine: true }] }; };
"""

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const run = new Function(process.argv[2] + src + `;
return (async () => {
  await officeLoad();
  const first = drawn.map(d => ({ role: d.role, text: d.text, ts: d.ts, who: d.node.dataset.roomWho || '',
    sync: d.node.dataset.syncRole, key: d.node.dataset.office, avatar: d.node.style['--char-avatar'] || '' }));
  await officeLoad();                                  // opened again: nothing twice
  const again = drawn.length;
  sessionMode = 'private';
  const privateDraw = officeDraw({ dialog_id: 'dm:a:b', n: 4, ts: 13, who: 'a', who_name: 'Nono', kind: 'say', text: 'x' });
  sessionMode = 'work'; roomOpen = 'room_1';
  const roomDraw = officeDraw({ dialog_id: 'dm:a:b', n: 5, ts: 14, who: 'a', who_name: 'Nono', kind: 'say', text: 'y' });
  roomOpen = ''; sessionCharacter = '';
  await officeLoad();
  return { first, again, privateDraw, roomDraw, calls, runs };
})();`);
run().then(o => console.log(JSON.stringify(o)));
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class Page(unittest.TestCase):
    def test_a_coworkers_turn_in_the_window(self):
        out = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-office.js"), PAGE], capture_output=True, text=True,
                             timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        o = json.loads(out.stdout)
        say, act, mine = o["first"]
        self.assertEqual((say["role"], say["text"], say["who"], say["ts"]), ("assistant", "check the build?", "a", 10))
        self.assertIn("/api/characters/a/avatar", say["avatar"], "the coworker's own face")
        self.assertEqual((act["role"], act["text"]), ("action", "✦ Nono — sets a coffee down"))
        self.assertEqual((mine["role"], mine["text"]), ("action", "→ Nono: on it"))
        self.assertEqual({d["sync"] for d in o["first"]}, {"office"}, "never taken for the 1:1's own message")
        self.assertEqual([d["key"] for d in o["first"]], ["dm:a:b#1", "dm:a:b#2", "dm:a:b#3"])
        self.assertEqual(o["again"], 3, "opened again: nothing twice")
        self.assertIsNone(o["privateDraw"], "a private talk is undisturbed")
        self.assertIsNone(o["roomDraw"], "a meeting room's screen is its own")
        self.assertEqual(o["calls"], ["/api/office?character=b", "/api/office/opened?character=b"] * 2,
                         "each open draws, then tells the host the window is open; no character: no call")

    def test_the_page_loads_it_and_the_stream_and_the_session_use_it(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('src="./app-rooms.js'), html.index('src="./app-office.js'))
        self.assertLess(html.index('src="./app-office.js'), html.index('src="./app.js'))
        sse = (STATIC / "app-sse.js").read_text(encoding="utf-8")
        self.assertIn("type === 'office'", sse)
        opened = sse[sse.index("es.onopen"):]
        self.assertIn("officeLoad()", opened[:opened.index("};")], "every stream open, so a host restart redraws them")


FIT = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const nodes = [];
const msg = (ts, office) => { const n = { dataset: { ts: String(ts) }, hidden: false };
  if (office) n.dataset.office = office; nodes.push(n); return n; };
const logEl = { querySelectorAll: sel => nodes.filter(n => sel.includes('data-office') ? n.dataset.office : n.dataset.ts) };
const placed = []; const placeMsgByTs = (n, ts) => placed.push(ts);
let scrollbackExhausted = false;
new Function('logEl', 'placeMsgByTs', 'getExhausted', src.replace(/typeof scrollbackExhausted === 'undefined' \|\| !scrollbackExhausted/,
  '!getExhausted()') + `;
  const dm = msg(50, 'dm:a:b#1');            // yesterday's dm
  msg(100); msg(110);                        // today's turns: all that is loaded
  officeFit(); const whileAbove = dm.hidden;
  msg(40);                                   // scrollback reached older than the dm
  officeFit(); const reached = dm.hidden;
  console.log(JSON.stringify({ whileAbove, reached, placed }));
`)(logEl, placeMsgByTs, () => scrollbackExhausted);
"""


class OfficeFitTest(unittest.TestCase):
    def test_an_older_dm_waits_for_scrollback_to_reach_its_time(self):
        # 2026-10-04: yesterday's dm was placed above today's loaded turns, then older sessions were prepended over it
        out = subprocess.run(["node", "-e", FIT, str(STATIC / "app-office.js")], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"whileAbove": True, "reached": False, "placed": [50]})

    def test_each_scrollback_hop_refits_them(self):
        src = (STATIC / "app-session.js").read_text(encoding="utf-8")
        body = src[src.index("async function loadOlderHistory("):]
        self.assertIn("officeFit()", body[:body.index("\nasync function ") if "\nasync function " in body else len(body)])


class FakeReq:
    def __init__(self, **q):
        self.qd, self.out = q, None

    def q(self, name, default=""):
        return self.qd.get(name, default)

    def json(self, obj):
        self.out = (200, obj)

    def send(self, code, body, ctype):
        self.out = (code, body)


class Routes(unittest.TestCase):
    def setUp(self):
        import characters as C
        import dialog_log as D
        import room_chat as RC
        self.C, self.D = C, D
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        ws = self.tmp / "workspace"
        self.a, self.b, self.c = sorted(C.new_id() for _ in range(3))
        for cid, name in ((self.a, "Nono"), (self.b, "Lili"), (self.c, "Ari")):
            C.save(cid, C.new_card(name), ws)
        self.patches = [mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.tmp / "ev")}),
                        mock.patch.object(C, "_default_ws", return_value=ws),
                        mock.patch.object(D, "_dir", lambda: self.tmp / "dialogs"),
                        mock.patch.object(RC, "_dir", lambda: self.tmp / "rooms")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_window_gets_its_dms_and_a_sent_one_is_pushed_to_both(self):
        import route_sessions as RS
        ab, bc = self.D.dm_id(self.a, self.b), self.D.dm_id(self.b, self.c)
        self.D.append(ab, self.a, "check the build?")
        self.D.append(ab, self.a, "sets a coffee down", kind="action")
        self.D.append(bc, self.b, "lunch?")
        req = FakeReq(character=self.b)
        RS.office(req)
        rows = req.out[1]["messages"]
        self.assertEqual([(r["who_name"], r["kind"], r["mine"], r["to_name"]) for r in rows],
                         [("Nono", "say", False, "Lili"), ("Nono", "action", False, "Lili"), ("Lili", "say", True, "Ari")])
        self.assertEqual(rows[1]["how"], "came by your desk")
        bad = FakeReq(character="nobody")
        RS.office(bad)
        self.assertEqual(bad.out[0], 400)

        class Sess:
            def __init__(self):
                self.got = []

            def _emit(self, ev):
                self.got.append(ev)
        windows = {self.a: Sess(), self.b: Sess()}
        with mock.patch.object(RS.REG, "_newest", side_effect=lambda mode, character: windows.get(character)), \
                mock.patch("event_react.react_once") as react:
            req = FakeReq(dialog=ab, n="2")
            RS.office_notify(req)
            self.assertEqual(req.out, (200, {"ok": True}))
            for t in __import__("threading").enumerate():
                if t.name == "office-react":
                    t.join(5)
        self.assertEqual(windows[self.b].got[0]["msg"]["mine"], False)
        self.assertEqual(windows[self.a].got[0]["msg"]["mine"], True, "the sender's window shows its own line")
        self.assertEqual(windows[self.b].got[0]["event"], "office")
        react.assert_called_once()
        with mock.patch("event_react.react_on_open") as on_open:
            req = FakeReq(character=self.b)
            RS.office_opened(req)
            self.assertEqual(req.out, (200, {"ok": True}))
            for t in __import__("threading").enumerate():
                if t.name == "office-open-check":
                    t.join(5)
        self.assertEqual(on_open.call_args[0][1], self.b)
        bad = FakeReq(character="x")
        RS.office_opened(bad)
        self.assertEqual(bad.out[0], 400)
        for q in ({"dialog": ab, "n": "9"}, {"dialog": "room_x", "n": "1"}, {"dialog": ab}):
            req = FakeReq(**q)
            RS.office_notify(req)
            self.assertIn(req.out[0], (400, 404), q)


if __name__ == "__main__":
    unittest.main()
