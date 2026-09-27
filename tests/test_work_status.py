"""While an expert works on a delegated run, the page says who and for how long, and a writing round shows its clock
against its limit and the files changed so far (DELEGATION_CLARITY_v1). Runs the REAL code from the page script in
node. Skipped when node is not installed.
Run: python3 -m unittest tests.test_work_status  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.page_source import app_bundle

APP = app_bundle()

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('marker missing: ' + from);
  return src.slice(a, b);
}
const els = {};
function el() {
  const n = { className: '', textContent: '', title: '', children: [], appendChild(c) { this.children.push(c); return c; },
           addEventListener() {}, classList: { add() {}, contains() { return false; } }, style: {} };   // style: card close button (#176)
  Object.defineProperty(n, 'childNodes', { get() { return n.children; } });
  return n;
}
var document = { getElementById: id => (els[id] = els[id] || el()), createElement: () => el() };
var turnStartedAt = 0, isBusy = false, inputEl = {}, workOpen = new Set();
function obsNode(tag, cls, text) { const n = el(); n.className = cls || ''; if (text != null) n.textContent = String(text); return n; }
eval(slice('const WORK_PHASE_LABEL', 'function workLine').replace(/\b(const|let) /g, 'var '));
eval(slice('function updateProcBadge', 'function startTurnTimer'));
eval(slice('function renderWorkCard', 'async function loadWork'));
const now = Date.now() / 1000;
workNames = { staff: '루루' };
const run = { ticket: 113, title: 'T', phase: 'writing', active: true, round: 1, task: 1, tasks_total: 1,
  tasks: [{ role: 'staff', title: 't', paths: [] }], started: now - 750, phase_since: now - 750, timeout_sec: 1200,
  files_changed: 2, brain: 'agy/flash', transcript: [] };
workOpen.add(113);   // the clock, file count and asked paths show in the opened card's details
const card = renderWorkCard(run);
const texts = n => [n.textContent].concat(n.children.flatMap(texts));
const badgeText = texts(card).join('|');
const paused = renderWorkCard(Object.assign({}, run, { phase: 'paused', active: false,
  need_paths: [{ path: 'b.txt', why: 'the helper lives there' }] }));
const pausedTexts = texts(paused);
activeWorkRun = run; updateProcBadge('idle');
const delegated = { text: els.procBadgeText.textContent, cls: els.procBadge.className };
activeWorkRun = null; updateProcBadge('idle');
process.stdout.write(JSON.stringify({ badgeText, delegated, idle: els.procBadgeText.textContent, pausedTexts }));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class WorkStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(APP)], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise AssertionError(r.stderr[-1500:])
        cls.out = json.loads(r.stdout)

    def test_the_card_shows_the_round_clock_and_files(self):
        self.assertIn("12:30 / 20:00", self.out["badgeText"])
        self.assertIn("파일 2개", self.out["badgeText"])

    def test_a_paused_card_lists_the_asked_files_and_offers_allow(self):
        t = self.out["pausedTexts"]
        self.assertIn("경로 필요: b.txt — the helper lives there", t)
        self.assertIn("경로 허용", t)
        self.assertTrue(any("경로 요청" in x for x in t))

    def test_the_chat_badge_says_who_works(self):
        self.assertEqual(self.out["delegated"]["text"], "루루 작업 중 · 12:30")
        self.assertIn("delegated", self.out["delegated"]["cls"])
        self.assertEqual(self.out["idle"], "대기 중")


if __name__ == "__main__":
    unittest.main()
