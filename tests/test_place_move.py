"""The way into the private room is a place move (PLACE_MOVE_v1, docs/plans/private-mode.md §8.8, W6): the destination
decides the room -- the office is the work room, any other place a private one -- and the engine settles it from
`/move <place>`. The engine's move chip asks first with a door card (nothing of the private room is loaded before
"move"); the user's own move menu and "to the office" go at once; the heart and /private are dev mode's.
Run: engine/run-tests.sh test_place_move
"""
import json
import shutil
import subprocess
import unittest
from unittest import mock

from tests.page_source import i18n_prelude  # noqa: E402
from tests._paths import ENGINE, REPO  # noqa: E402

import personal_turn  # noqa: E402
import route_sessions  # noqa: E402

STATIC = REPO / "static"


class FakeReq:
    def __init__(self, sid, text):
        self.arg, self.body, self.out = sid, {"text": text, "client_mid": "m1"}, None

    def json(self, obj, code=200):
        self.out = (code, obj)
        return self.out


class FakeSess:
    character = ""

    def maybe_swap_provider(self, _p):
        pass

    def maybe_swap_model(self, _m):
        pass


class MoveTarget(unittest.TestCase):
    def test_the_office_is_the_work_room_and_any_other_place_a_private_one(self):
        self.assertEqual(personal_turn.move_target("office"), "/private off")
        self.assertEqual(personal_turn.move_target(" Office "), "/private off")
        self.assertEqual(personal_turn.move_target("stairwell"), "/private on the stairwell")   # id -> catalog name
        self.assertEqual(personal_turn.move_target("신사 뒤뜰"), "/private on 신사 뒤뜰")         # a place of its own

    def test_move_goes_through_the_room_switch(self):
        seen = []
        with mock.patch.object(route_sessions.REG, "get", return_value=FakeSess()), \
             mock.patch.object(route_sessions, "_switch_room", side_effect=lambda req, s, sid, text, mid: seen.append(text)):
            route_sessions.message(FakeReq("w1", "/move rooftop"))
            route_sessions.message(FakeReq("p1", "/move office"))
            bare = FakeReq("w1", "/move  ")
            route_sessions.message(bare)
        self.assertEqual(seen, ["/private on the rooftop terrace", "/private off"])
        self.assertEqual(bare.out[0], 400)

    def test_the_chip_and_the_choice_channel_speak_move(self):
        mcp = (ENGINE / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn('"/move")', mcp)
        server = (ENGINE / "server.py").read_text(encoding="utf-8")
        self.assertIn('"name": "/move"', server)
        self.assertNotIn('"name": "/private on"', server, "the slash list offers /move; /private stays typed (dev)")
        self.assertIn('("/api/sessions/*/places", route_sessions.places)', server)


class VisitPlace(unittest.TestCase):
    def test_the_header_learns_the_visit_s_place_with_its_catalog_id(self):
        import tempfile, threshold
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            sess = type("S", (), {"meta_path": Path(d) / "meta.json", "character": ""})()
            self.assertEqual(threshold.place_of(sess), {})
            (Path(d) / threshold.SCENE_FILE).write_text(json.dumps({"kind": "visit", "place": "the rooftop terrace"}))
            self.assertEqual(threshold.place_of(sess), {"name": "the rooftop terrace", "id": "rooftop"})
            (Path(d) / threshold.SCENE_FILE).write_text(json.dumps({"kind": "visit", "place": "신사 뒤뜰"}))
            self.assertEqual(threshold.place_of(sess), {"name": "신사 뒤뜰", "id": ""})

    def test_the_private_state_is_muted_and_the_office_is_one_key_away(self):
        css = (STATIC / "shell.css").read_text(encoding="utf-8")
        self.assertNotIn("body.private-session #shellPresence{color:var(--accent2)}", css)
        self.assertIn(".shell-row-preview.is-private{color:var(--muted)}", css)
        js = (STATIC / "app-move.js").read_text(encoding="utf-8")
        self.assertIn("e.code === 'KeyO' && moveShown().office", js)
        rs = (ENGINE / "route_sessions.py").read_text(encoding="utf-8")
        self.assertEqual(rs.count("threshold.place_of(sess)"), 2, "both session reads carry the place")


HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const sent = [], switched = [], notices = [];
function el(tag) {
  return { tag, children: [], className: '', textContent: '', listeners: {}, classList: { add() {} },
           appendChild(c) { this.children.push(c); return c; }, addEventListener(k, f) { this.listeners[k] = f; },
           querySelector() { return this.children[0] && this.children[0].children[0]; }, focus() {}, remove() { this.gone = true; } };
}
const document = { createElement: el, body: { classList: { contains: () => false } } };
const window = {};
let sessionId = 'w1';
const myPendingMids = new Set();
function _newClientMid() { return 'm1'; }
async function api(url, opts) {
  if (opts) sent.push(JSON.parse(opts.body).text);
  else sent.push('GET ' + url);
  return url.endsWith('/places') ? { places: [{ id: 'rooftop', name: 'the rooftop terrace' }] } : { session: { id: 'p1' } };
}
async function applyModeSwitch(res) { switched.push(res.session.id); }
function addNotice(kind, text) { const n = el('div'); n.kind = kind; n.text = text; notices.push(n); return n; }
eval(src.replace(/^const MOVE_TEXT.*$/m, "const MOVE_TEXT = i18nTable('move');"));
(async () => {
  await moveLoadPlaces();
  moveDoor('/move rooftop');                         // the chip: a card first, nothing sent
  const card = notices[0], buttons = card.children[0].children;
  const before = sent.slice();
  buttons[0].listeners.click();                      // "move"
  await new Promise(r => setTimeout(r, 0));
  const door = { text: card.text, labels: buttons.map(b => b.textContent), before, after: sent.slice(), switched: switched.slice() };
  moveDoor('/move rooftop');
  notices[1].children[0].children[1].listeners.click();   // "stay"
  const stayed = { sent: sent.length, gone: Boolean(notices[1].gone) };
  await moveMenu();                                 // the user's own: a list, picking one moves
  const menu = notices[2].children[0].children.map(b => b.textContent);
  notices[2].children[0].children[0].listeners.click();
  await new Promise(r => setTimeout(r, 0));
  window.sessionPlace = { name: 'the rooftop terrace', id: 'rooftop' };
  const here = movePlaceNow();
  window.sessionPlace = null;
  const none = movePlaceNow();
  console.log(JSON.stringify({ door, stayed, menu, last: sent[sent.length - 1], here, none }));
})().catch(e => { console.error(e); process.exit(1); });
"""


class Page(unittest.TestCase):
    def test_the_door_card_asks_before_anything_is_loaded(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        proc = subprocess.run([node, "-e", i18n_prelude() + HARNESS, str(STATIC / "app-move.js")], capture_output=True,
                              text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        cat = json.loads((STATIC / "i18n" / "ko.json").read_text(encoding="utf-8"))
        place = cat["place.rooftop"]
        self.assertEqual(out["door"]["text"], cat["move.door"].replace("{place}", place))
        self.assertEqual(out["door"]["labels"], [cat["move.go"], cat["move.stay"]])
        self.assertEqual(out["door"]["before"], ["GET /api/sessions/w1/places"], "the card sends nothing")
        self.assertEqual(out["door"]["after"][-1], "/move rooftop")
        self.assertEqual(out["door"]["switched"], ["p1"])
        self.assertEqual(out["stayed"]["sent"], 2, "'stay' sends nothing")
        self.assertTrue(out["stayed"]["gone"])
        self.assertEqual(out["menu"], [place, cat["move.stay"]])
        self.assertEqual(out["last"], "/move rooftop")
        self.assertEqual(out["here"], place, "the header names the place by its catalog word")
        self.assertEqual(out["none"], cat["shelltext.privateRoom"])

    def test_the_heart_is_dev_only_and_the_chip_opens_the_door(self):
        css = (STATIC / "shell.css").read_text(encoding="utf-8")
        self.assertIn("html.shell2 body:not(.dev-mode) #shellHeart,html.shell2 body:not(.dev-mode) #privateBtn{display:none", css)
        md = (STATIC / "markdown.js").read_text(encoding="utf-8")
        self.assertIn("typeof moveDoor === 'function') return moveDoor(cmdText);", md)


if __name__ == "__main__":
    unittest.main()
