"""SSE events and the 2.5s resync both draw the log. Whichever arrives second must not redraw.
(실장님: 샛길 카드가 두 장 / 내 말·답이 두 번.)
Runs the REAL btw / user_ack / result handler blocks and the ts-identity helpers (sliced out
of static/app.js) in node against a stub DOM. Skipped when node is not installed.
Run: python3 -m unittest tests.test_sse_resync_dedupe  (from services/chatbot)
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
const helpers = slice('function msgSyncKey', 'function inFlightAssistant');
const resultBlk = slice("if (type === 'result') {", "if (type === 'session_heavy') {");
const ackBlk = slice("if (type === 'user_ack') {", "if (type === 'btw_start') {");
const btwBlk = slice("if (type === 'btw') {", "if (type === 'tool' || type === 'system'");
const resyncSrc = slice('async function resyncFromServer', 'function startSessionSyncLoop');

// --- minimal DOM -------------------------------------------------------------------------
function makeNode(cls) {
  const n = { className: cls, dataset: {}, textContent: '', children: [], parent: null, _rawHead: undefined,
    classList: { contains: c => n.className.split(/\s+/).includes(c), remove: c => { n.className = n.className.split(/\s+/).filter(x => x !== c).join(' '); } },
    remove() { if (n.parent) n.parent.children = n.parent.children.filter(x => x !== n); n.parent = null; } };
  return n;
}
function matches(n, sel) {
  // supports: .cls  [data-x]  [data-x="v"]  :not([data-x])   (all concatenated, e.g. .msg.user:not([data-ts]))
  let rest = sel;
  const re = /^(?:\.([\w-]+)|:not\(\[data-([\w-]+)\]\)|\[data-([\w-]+)(?:="([^"]*)")?\])/;
  const camel = k => k.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  while (rest) {
    const m = re.exec(rest);
    if (!m) throw new Error('selector not supported by stub: ' + sel);
    if (m[1] && !n.classList.contains(m[1])) return false;
    if (m[2] && camel(m[2]) in n.dataset) return false;
    if (m[3]) { const k = camel(m[3]); if (!(k in n.dataset)) return false; if (m[4] !== undefined && n.dataset[k] !== m[4]) return false; }
    rest = rest.slice(m[0].length);
  }
  return true;
}
const logEl = makeNode('log');
logEl.querySelectorAll = sel => logEl.children.filter(c => matches(c, sel));
logEl.querySelector = sel => logEl.querySelectorAll(sel)[0] || null;
function put(n) { n.parent = logEl; logEl.children.push(n); return n; }

const calls = { addChat: 0, addBtw: 0 };
const body = helpers + `
  let assistantNode = null, assistantBuf = '', lastSyncedTs = 0;
  let sessionId = 'S1', resyncInFlight = false, isBusy = false;
  const myPendingMids = new Set();
  let serverInfo = null;
  const api = async () => serverInfo;
  ${resyncSrc}
  const handle = function (type, data) { const text = data.text || ''; ${resultBlk}\n${ackBlk}\n${btwBlk} };
  return { handle, myPendingMids, resync: () => resyncFromServer('S1'), serve(i) { serverInfo = i; },
           helpers: { findRenderedByTs, markUntimed, adoptUntimedAssistant, adoptBareUserBubble },
           get st() { return { assistantNode, assistantBuf }; }, set live(v) { assistantNode = v.node; assistantBuf = v.buf; } };`;
const stubs = {
  logEl,
  placeMsgByTs: () => {},
  addChat: (role, text, isFinal, q, isBtw, prepend, u, d, sys, ts) => {
    calls.addChat++;
    const n = makeNode('msg ' + role + (isBtw ? ' btw-user' : ''));
    n.textContent = text; n.dataset.syncRole = isBtw ? 'btw-user' : role; if (ts) n.dataset.ts = String(ts);
    return put(n);
  },
  addBtw: (query, answer, prepend, u, d, ts) => {
    calls.addBtw++;
    const n = makeNode('msg btw-card'); n.dataset.syncRole = 'btw'; if (ts) n.dataset.ts = String(ts);
    return put(n);
  },
  setAssistantContent: (n, t) => { n.textContent = t; },
  setBusy() {}, repairMsgOrder() {}, fetchArtifacts() {}, logTurnUsage() {}, addActivity() {}, setProgress() {},
  shortToolLine: s => s,
};
const names = Object.keys(stubs);
const env = new Function(...names, body)(...names.map(k => stubs[k]));

const out = {};
const count = sel => logEl.querySelectorAll(sel).length;
const reset = () => { logEl.children = []; calls.addChat = 0; calls.addBtw = 0; env.myPendingMids.clear(); env.live = { node: null, buf: '' }; };

// 1. btw card: a resync already drew it (same ts), then the SSE event arrives
reset();
put(Object.assign(makeNode('msg btw-card'), { dataset: { syncRole: 'btw', ts: '100.5' } }));
env.handle('btw', { query: 'q', text: 'a', ts: 100.5 });
out.btwLate = { cards: count('.btw-card'), addBtw: calls.addBtw };
reset();
env.handle('btw', { query: 'q', text: 'a', ts: 101.5 });
out.btwFresh = { cards: count('.btw-card') };
env.handle('btw', { query: 'q2', text: 'a2', ts: 102.5 });
out.btwTwo = { cards: count('.btw-card') };

// 2. user_ack
reset();   // (a) mine, bare bubble
put(Object.assign(makeNode('msg user'), { textContent: '안녕', dataset: { syncRole: 'user' } }));
env.myPendingMids.add('m1');
env.handle('user_ack', { text: '안녕', ts: 200.1, client_mid: 'm1' });
out.ackMine = { users: count('.msg.user'), stamped: logEl.children[0].dataset.ts };
reset();   // (b) resync already stamped msg 1; a later bare bubble must NOT be stamped by msg 1's ack
put(Object.assign(makeNode('msg user'), { textContent: '첫째', dataset: { syncRole: 'user', ts: '300.1' } }));
put(Object.assign(makeNode('msg user'), { textContent: '둘째', dataset: { syncRole: 'user' } }));
env.myPendingMids.add('m1'); env.myPendingMids.add('m2');
env.handle('user_ack', { text: '첫째', ts: 300.1, client_mid: 'm1' });
out.ackAfterResync = { secondStamped: 'ts' in logEl.children[1].dataset, users: count('.msg.user') };
reset();   // (c) pending set was lost, same-text bare bubble exists -> adopt, don't add
put(Object.assign(makeNode('msg user'), { textContent: '그래', dataset: { syncRole: 'user' } }));
env.handle('user_ack', { text: '그래', ts: 400.1, client_mid: 'gone' });
out.ackAdopt = { users: count('.msg.user'), addChat: calls.addChat, stamped: logEl.children[0].dataset.ts };
reset();   // (d) a real message from another window is still drawn
env.handle('user_ack', { text: '다른 창', ts: 500.1, client_mid: 'other' });
out.ackForeign = { users: count('.msg.user'), addChat: calls.addChat };
env.handle('user_ack', { text: '다른 창', ts: 500.1, client_mid: 'other' });   // ...but only once
out.ackForeignTwice = { users: count('.msg.user') };

// 3. result: a resync already drew the answer (assistantNode gone), then the SSE result arrives
reset();
put(Object.assign(makeNode('msg assistant'), { dataset: { syncRole: 'assistant', ts: '600.1' } }));
env.handle('result', { text: '답변', ts: 600.1 });
out.resultLate = { assistants: count('.msg.assistant'), addChat: calls.addChat };
reset();   // normal: live bubble gets finalized and stamped
const live = put(Object.assign(makeNode('msg assistant'), { dataset: { live: '1' } }));
env.live = { node: live, buf: '부분' };
env.handle('result', { text: '완성', ts: 700.1 });
out.resultNormal = { assistants: count('.msg.assistant'), ts: live.dataset.ts, live: 'live' in live.dataset };
reset();   // no live bubble, nothing on screen: the result is drawn once
env.handle('result', { text: '단독', ts: 800.1 });
out.resultAlone = { assistants: count('.msg.assistant') };

// 4. ts-less bubble the client closed itself is adopted by the server's copy
reset();
const closed = put(makeNode('msg assistant'));
env.helpers.markUntimed(closed, '  진행하던 작업의 앞부분입니다. 계속 이어서...  ');
out.adopt = env.helpers.adoptUntimedAssistant({ ts: 900.1, text: '진행하던 작업의 앞부분입니다. 계속 이어서...\n\n*(🧭 멈췄습니다)*' });
out.adoptState = { ts: closed.dataset.ts, role: closed.dataset.syncRole, untimed: 'untimed' in closed.dataset };
out.adoptOther = env.helpers.adoptUntimedAssistant({ ts: 901.1, text: '전혀 다른 답변' });
out.adoptTwice = env.helpers.adoptUntimedAssistant({ ts: 900.1, text: '진행하던 작업의 앞부분입니다. 계속 이어서...' });

// 5. the real resyncFromServer against a server that is idle
(async () => {
  reset();   // (a) the client closed a bubble itself; the server's history holds its copy
  const b = put(makeNode('msg assistant'));
  env.helpers.markUntimed(b, '진행하던 작업의 앞부분입니다.');
  env.serve({ id: 'S1', busy: false, history: [{ role: 'assistant', ts: 1000.1, text: '진행하던 작업의 앞부분입니다. 이어서...\n\n*(멈춤)*' }] });
  await env.resync();
  out.resyncAdopts = { assistants: count('.msg.assistant'), ts: b.dataset.ts, addChat: calls.addChat };

  reset();   // (b) an idle server must not make this window forget the message it just sent
  env.myPendingMids.add('m1');
  env.serve({ id: 'S1', busy: false, history: [] });
  await env.resync();
  out.resyncKeepsMids = env.myPendingMids.has('m1');

  reset();   // (c) ...so the ack that follows is still recognised as this window's own: 1 bubble
  put(Object.assign(makeNode('msg user'), { textContent: '끼워넣기', dataset: { syncRole: 'user' } }));
  env.myPendingMids.add('m1');
  env.serve({ id: 'S1', busy: false, history: [] });
  await env.resync();
  env.handle('user_ack', { text: '끼워넣기', ts: 1100.1, client_mid: 'm1' });
  out.ackAfterIdleResync = { users: count('.msg.user'), addChat: calls.addChat };

  reset();   // (d) resync draws the btw card from history first, the SSE event comes later
  env.serve({ id: 'S1', busy: false, history: [{ role: 'btw', query: 'q', text: 'a', ts: 1200.1 }] });
  await env.resync();
  env.handle('btw', { query: 'q', text: 'a', ts: 1200.1 });
  out.resyncThenBtwEvent = { cards: count('.btw-card') };
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SseResyncDedupe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(APP)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_btw_event_that_arrives_after_the_resync_does_not_add_a_second_card(self):
        self.assertEqual(self.o["btwLate"], {"cards": 1, "addBtw": 0})

    def test_btw_events_without_a_twin_are_still_drawn(self):
        self.assertEqual(self.o["btwFresh"], {"cards": 1})
        self.assertEqual(self.o["btwTwo"], {"cards": 2})

    def test_own_ack_stamps_the_bubble_without_adding_one(self):
        self.assertEqual(self.o["ackMine"], {"users": 1, "stamped": "200.1"})

    def test_an_ack_after_the_resync_stamped_it_leaves_the_next_bubble_alone(self):
        self.assertEqual(self.o["ackAfterResync"], {"secondStamped": False, "users": 2})

    def test_an_ack_with_a_lost_pending_id_adopts_the_same_text_bubble(self):
        self.assertEqual(self.o["ackAdopt"], {"users": 1, "addChat": 0, "stamped": "400.1"})

    def test_another_windows_message_is_drawn_exactly_once(self):
        self.assertEqual(self.o["ackForeign"], {"users": 1, "addChat": 1})
        self.assertEqual(self.o["ackForeignTwice"], {"users": 1})

    def test_a_result_event_that_arrives_after_the_resync_does_not_redraw_the_answer(self):
        self.assertEqual(self.o["resultLate"], {"assistants": 1, "addChat": 0})

    def test_the_normal_result_still_finalizes_and_stamps_the_live_bubble(self):
        self.assertEqual(self.o["resultNormal"], {"assistants": 1, "ts": "700.1", "live": False})
        self.assertEqual(self.o["resultAlone"], {"assistants": 1})

    def test_a_bubble_the_client_closed_itself_is_adopted_not_duplicated(self):
        self.assertTrue(self.o["adopt"])
        self.assertEqual(self.o["adoptState"], {"ts": "900.1", "role": "assistant", "untimed": False})
        self.assertFalse(self.o["adoptOther"])
        self.assertFalse(self.o["adoptTwice"])   # already adopted: a second history copy is not swallowed

    def test_resync_adopts_a_bubble_the_client_closed_instead_of_drawing_it_again(self):
        self.assertEqual(self.o["resyncAdopts"], {"assistants": 1, "ts": "1000.1", "addChat": 0})

    def test_an_idle_resync_no_longer_forgets_the_messages_this_window_sent(self):
        self.assertTrue(self.o["resyncKeepsMids"])
        self.assertEqual(self.o["ackAfterIdleResync"], {"users": 1, "addChat": 0})

    def test_resync_first_then_the_sse_btw_event_still_gives_one_card(self):
        self.assertEqual(self.o["resyncThenBtwEvent"], {"cards": 1})


if __name__ == "__main__":
    unittest.main()
