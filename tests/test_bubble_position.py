"""The user's own bubble must stay where they put it when its ack / the resync arrives.
(실장님: 보낸 말풍선이 화면에서 사라졌다가 새로고침하니 제대로 보임 -- it had jumped above the
session greeting, i.e. to the top of the log.)
Runs the REAL adoptBareUserBubble / inFlightAssistant / placeMsgByTs (sliced out of static/app.js)
in node against a stub DOM. Skipped when node is not installed.
Run: python3 -m unittest tests.test_bubble_position  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "static" / "app.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a + from.length);
  if (a < 0 || b < 0) throw new Error('marker missing: ' + from + ' .. ' + to);
  return src.slice(a, b);
}
const code = slice('function msgSyncKey', 'function addBtwQuestionBubble');   // ts helpers, adopt*, inFlightAssistant, placeMsgByTs, repairMsgOrder

const camel = k => k.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
function detach(c) { if (c.parent) c.parent.children = c.parent.children.filter(x => x !== c); c.parent = null; }
function node(cls, label) {
  const n = { label, className: cls, dataset: {}, children: [], parent: null, textContent: '',
    classList: { contains: c => n.className.split(/\s+/).includes(c) },
    get nextElementSibling() { const s = n.parent.children; return s[s.indexOf(n) + 1] || null; } };
  return n;
}
// supports: .cls  :not(.cls)  [data-x]  [data-x="v"]  :not([data-x])  concatenated
function matches(n, sel) {
  let rest = sel;
  const re = /^(?:\.([\w-]+)|:not\(\.([\w-]+)\)|:not\(\[data-([\w-]+)\]\)|\[data-([\w-]+)(?:="([^"]*)")?\])/;
  while (rest) {
    const m = re.exec(rest);
    if (!m) throw new Error('selector not supported by stub: ' + sel);
    if (m[1] && !n.classList.contains(m[1])) return false;
    if (m[2] && n.classList.contains(m[2])) return false;
    if (m[3] && camel(m[3]) in n.dataset) return false;
    if (m[4]) { const k = camel(m[4]); if (!(k in n.dataset)) return false; if (m[5] !== undefined && n.dataset[k] !== m[5]) return false; }
    rest = rest.slice(m[0].length);
  }
  return true;
}
function mkLog() {
  const l = node('log', 'log');
  l.querySelectorAll = s => l.children.filter(c => matches(c, s));
  l.querySelector = s => l.querySelectorAll(s)[0] || null;
  l.appendChild = n => { detach(n); n.parent = l; l.children.push(n); };
  l.insertBefore = (n, ref) => { detach(n); n.parent = l; const i = ref ? l.children.indexOf(ref) : -1; if (i < 0) l.children.push(n); else l.children.splice(i, 0, n); };
  return l;
}
function run(build) {
  const logEl = mkLog();
  const f = new Function('logEl', 'parkSessionBanner', 'scrollChatToBottom', code + ';return { adoptBareUserBubble, placeMsgByTs };')(logEl, () => {}, () => {});
  const add = (cls, label, ts, text) => { const n = node(cls, label); if (ts) n.dataset.ts = String(ts); n.textContent = text || label; logEl.appendChild(n); return n; };
  const extra = build(logEl, add, f);
  return { order: logEl.children.map(c => c.label), extra };
}

const out = {};
// 1. the ack for my bubble arrives with no answer bubble in flight, a greeting sits at the top
out.ackNoLive = run((log, add, f) => {
  add('msg assistant system', 'GREETING'); add('msg user', 'U1', 100); add('msg assistant', 'A1', 105);
  const u = add('msg user', 'U2', 0, '인사해주랑');
  const r = f.adoptBareUserBubble('인사해주랑', 110);
  return { adopted: r, ts: u.dataset.ts, role: u.dataset.syncRole };
});
// 2. same, plain log
out.ackPlain = run((log, add, f) => {
  add('msg user', 'U1', 100); add('msg assistant', 'A1', 105); add('msg user', 'U2', 0, '다음');
  f.adoptBareUserBubble('다음', 110);
});
// 3. a resync-style placement of a fresh message (ts newer than everything): end of log, not above the greeting
out.placeWithGreeting = run((log, add, f) => {
  add('msg assistant system', 'GREETING'); add('msg user', 'U1', 100); add('msg assistant', 'A1', 105);
  const n = add('msg user', 'NEW', 0, 'x'); f.placeMsgByTs(n, 120);
});
// 4. a bubble the client closed itself (untimed) is not a turn in flight either
out.placeWithUntimed = run((log, add, f) => {
  add('msg user', 'U1', 100);
  const p = add('msg assistant', 'PARTIAL(untimed)'); p.dataset.untimed = '1';
  const n = add('msg user', 'NEW', 0, 'x'); f.placeMsgByTs(n, 120);
});
// 5. a real in-flight bubble is still honoured
out.placeWithLive = run((log, add, f) => {
  add('msg assistant system', 'GREETING'); add('msg user', 'U1', 100);
  const L = add('msg assistant', 'LIVE'); L.dataset.live = '1';
  const n = add('msg user', 'NEW', 0, 'x'); f.placeMsgByTs(n, 120);
});
// 6. a genuine ts-less unfinished (non-system) bubble still counts as in flight
out.placeWithBareAssistant = run((log, add, f) => {
  add('msg user', 'U1', 100); add('msg assistant', 'STREAMING(no ts)');
  const n = add('msg user', 'NEW', 0, 'x'); f.placeMsgByTs(n, 120);
});
// 7. stamping never moves the bubble, whatever the ts order says (a ts-based re-placement would hop over A1)
out.adoptNeverMoves = run((log, add, f) => {
  add('msg user', 'U1', 100); add('msg assistant', 'A1', 300); add('msg user', 'U2', 0, '끼워넣기');
  f.adoptBareUserBubble('끼워넣기', 110);
});
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class BubblePosition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(APP)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_my_bubble_stays_put_when_its_ack_arrives_with_no_answer_in_flight(self):
        self.assertEqual(self.o["ackNoLive"]["order"], ["GREETING", "U1", "A1", "U2"])
        self.assertEqual(self.o["ackNoLive"]["extra"], {"adopted": True, "ts": "110", "role": "user"})
        self.assertEqual(self.o["ackPlain"]["order"], ["U1", "A1", "U2"])

    def test_stamping_a_bubble_never_moves_it(self):
        self.assertEqual(self.o["adoptNeverMoves"]["order"], ["U1", "A1", "U2"])

    def test_a_new_message_is_not_placed_above_the_session_greeting(self):
        self.assertEqual(self.o["placeWithGreeting"]["order"], ["GREETING", "U1", "A1", "NEW"])

    def test_a_bubble_the_client_closed_itself_is_not_taken_for_a_turn_in_flight(self):
        self.assertEqual(self.o["placeWithUntimed"]["order"], ["U1", "PARTIAL(untimed)", "NEW"])

    def test_a_real_turn_in_flight_still_keeps_new_messages_above_it(self):
        self.assertEqual(self.o["placeWithLive"]["order"], ["GREETING", "U1", "NEW", "LIVE"])
        self.assertEqual(self.o["placeWithBareAssistant"]["order"], ["U1", "NEW", "STREAMING(no ts)"])


if __name__ == "__main__":
    unittest.main()
