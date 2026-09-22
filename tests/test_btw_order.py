"""A /btw answer card always lands right after its own question, whichever of the answer / the
2.5s resync (repairMsgOrder) comes first. (실장님: "첫 질문은 질문 다음에 대답이 찍혔는데 그 다음
btw는 대답이 질문 전에 찍혔어".)
Runs the REAL inFlightAssistant / placeMsgByTs / repairMsgOrder / addBtw / btw helpers (sliced out
of static/app.js) in node against a stub DOM. Skipped when node is not installed.
Run: python3 -m unittest tests.test_btw_order  (from services/chatbot)
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
const code = slice('function inFlightAssistant', 'function addChat');

const camel = k => k.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
function node(cls) {
  const n = { className: cls || '', dataset: {}, children: [], parent: null, innerHTML: '', textContent: '',
    classList: { contains: c => n.className.split(/\s+/).includes(c) },
    get nextSibling() { const s = n.parent ? n.parent.children : []; return s[s.indexOf(n) + 1] || null; },
    get nextElementSibling() { return n.nextSibling; },
    get firstChild() { return n.children[0] || null; },
    appendChild(c) { detach(c); c.parent = n; n.children.push(c); return c; },
    insertBefore(c, ref) { detach(c); c.parent = n; const i = ref ? n.children.indexOf(ref) : -1; if (i < 0) n.children.push(c); else n.children.splice(i, 0, c); return c; },
  };
  return n;
}
function detach(c) { if (c.parent) c.parent.children = c.parent.children.filter(x => x !== c); c.parent = null; }
function matches(n, sel) {
  let rest = sel;
  const re = /^(?:\.([\w-]+)|:not\(\[data-([\w-]+)\]\)|\[data-([\w-]+)(?:="([^"]*)")?\])/;
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
const logEl = node('log');
logEl.querySelectorAll = sel => logEl.children.filter(c => matches(c, sel));
logEl.querySelector = sel => logEl.querySelectorAll(sel)[0] || null;

let mid = 0;
function addChat(role, text, isFinal, q, isBtw) {            // stand-in for the real addChat: appends at the end
  const n = node('msg ' + role + (isBtw ? ' btw-user' : ''));
  n.textContent = text; n.dataset.syncRole = isBtw ? 'btw-user' : role;
  logEl.appendChild(n);
  return n;
}
const stubs = {
  logEl, addChat, document: { createElement: () => node() },
  escapeHtml: s => s, renderMarkdown: s => s, postProcessAssistant() {},
  parkSessionBanner() {}, scrollChatToBottom() {},
};
const names = Object.keys(stubs);
const api = new Function(...names, code + ';return { placeMsgByTs, repairMsgOrder, addBtw, addBtwQuestionBubble, btwQueryOf };')
  (...names.map(k => stubs[k]));

function sig(n) {
  if (n.className.includes('btw-card')) return 'A:' + (/Q\. (.*?)<\/span>/.exec(n.children[0].innerHTML) || [, '?'])[1];
  if (n.className.includes('user')) return (n.className.includes('btw-user') ? 'Q:' : 'U:') + n.textContent;
  if (n.dataset.live === '1') return 'LIVE';
  return 'M:' + (n.textContent || n.dataset.ts || '');
}
const order = () => logEl.children.map(sig);
const reset = () => { logEl.children = []; };
function user(text, ts) { const n = addChat('user', text); if (ts) n.dataset.ts = String(ts); return n; }
function live() { const n = node('msg assistant'); n.dataset.live = '1'; logEl.appendChild(n); return n; }

const out = {};
// 1. main turn streaming; the answer beats the resync tick, then the tick runs
reset(); user('작업 시작', 1); live();
api.addBtwQuestionBubble('왜 이러냐');
api.addBtw('왜 이러냐', '이유', false, null, null, 5);
api.repairMsgOrder();
out.answerFirst = order();
// 2. ...the tick runs first, then the answer
reset(); user('작업 시작', 1); live();
api.addBtwQuestionBubble('왜 이러냐');
api.repairMsgOrder();
api.addBtw('왜 이러냐', '이유', false, null, null, 5);
api.repairMsgOrder();
out.tickFirst = order();
// 3. two btw in a row, second answered before the tick (the reported case)
reset(); user('작업 시작', 1); live();
api.addBtwQuestionBubble('첫 질문');
api.addBtw('첫 질문', '답1', false, null, null, 5);
api.repairMsgOrder();
api.addBtwQuestionBubble('둘째 질문');
api.addBtw('둘째 질문', '답2', false, null, null, 8);
api.repairMsgOrder();
out.twoInARow = order();
// 4. idle session, explicit "/btw ..." (bubble text carries the prefix, the server's query does not)
reset(); user('안녕', 1);
api.addBtwQuestionBubble('/btw 머하니');
api.addBtw('머하니', '쉬는 중', false, null, null, 5);
out.idleExplicit = order();
// 5. the same question asked twice pairs oldest-first
reset(); user('시작', 1); live();
api.addBtwQuestionBubble('진행률?');
api.addBtwQuestionBubble('진행률?');
api.addBtw('진행률?', '30%', false, null, null, 5);
api.addBtw('진행률?', '60%', false, null, null, 9);
api.repairMsgOrder();
out.sameTwice = order();
// 6. no question bubble here (another window / after a reload): the old ts placement is untouched
reset(); user('작업', 1); const L = live();
api.addBtw('남의 질문', '답', false, null, null, 5);
out.noBubble = order();
// 7. history scrollback (prepend) never pairs with a bubble
reset(); user('지금 화면', 10);
api.addBtwQuestionBubble('옛 질문 아님');
api.addBtw('옛 질문 아님', '옛 답', true, null, null, 2);
out.prepend = order();
// 8. a finished-but-ts-less assistant bubble far above is NOT a live turn: the question stays at the end
reset(); const old = node('msg assistant'); logEl.appendChild(old); user('최근', 20);
api.addBtwQuestionBubble('질문');
out.notLive = order();
out.queryOf = [api.btwQueryOf('/btw x'), api.btwQueryOf('/btw\n  x  '), api.btwQueryOf('/btw'), api.btwQueryOf('그냥 질문?')];
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class BtwOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(APP)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_answer_before_the_resync_tick_still_follows_its_question(self):
        self.assertEqual(self.o["answerFirst"], ["U:작업 시작", "Q:왜 이러냐", "A:왜 이러냐", "LIVE"])

    def test_resync_tick_before_the_answer_gives_the_same_order(self):
        self.assertEqual(self.o["tickFirst"], ["U:작업 시작", "Q:왜 이러냐", "A:왜 이러냐", "LIVE"])

    def test_the_second_btw_in_a_row_is_no_longer_answer_first(self):
        self.assertEqual(self.o["twoInARow"],
                         ["U:작업 시작", "Q:첫 질문", "A:첫 질문", "Q:둘째 질문", "A:둘째 질문", "LIVE"])

    def test_explicit_btw_pairs_despite_the_prefix_and_idle_stays_in_order(self):
        self.assertEqual(self.o["idleExplicit"], ["U:안녕", "Q:/btw 머하니", "A:머하니"])

    def test_the_same_question_twice_pairs_oldest_first(self):
        self.assertEqual(self.o["sameTwice"], ["U:시작", "Q:진행률?", "A:진행률?", "Q:진행률?", "A:진행률?", "LIVE"])

    def test_a_card_without_a_question_bubble_keeps_the_old_placement(self):
        self.assertEqual(self.o["noBubble"], ["U:작업", "A:남의 질문", "LIVE"])

    def test_scrollback_cards_are_not_paired_with_a_bubble(self):
        self.assertEqual(self.o["prepend"][0], "A:옛 질문 아님")

    def test_a_ts_less_finished_bubble_is_not_mistaken_for_a_live_turn(self):
        self.assertEqual(self.o["notLive"], ["M:", "U:최근", "Q:질문"])

    def test_query_extraction_matches_what_the_server_sends(self):
        self.assertEqual(self.o["queryOf"], ["x", "x", "", "그냥 질문?"])


if __name__ == "__main__":
    unittest.main()
