"""The page's side of one author per file (LEASE_SCOPE_v1): another agent's own ticket is not offered to the chat,
and a ticket whose files a live lease holds says what it waits for. Runs the REAL helpers extracted from
static/app.js in node. Skipped when node is not installed.
Run: python3 -m unittest tests.test_lease_ui  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import i18n_prelude  # noqa: E402
from tests.page_source import app_bundle  # noqa: E402

APP = app_bundle()   # static/app.js and its app-*.js parts (APP_SPLIT_v1)
HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('let ticketLeases = [];'), b = src.indexOf('function ticketDecisionText');
if (a < 0 || b < 0) throw new Error('markers missing');
const TICKET_DECISIONS = { approved: [['go', '진행'], ['delegate', '실행'], ['decline', '폐기']] };
eval(src.slice(a, b).replace('let ticketLeases', 'var ticketLeases'));
ticketLeases = [{ ticket: 113, paths: ['static/app.js'], until: '2026-09-24 10:53:57', actor: 'agy' }];
const out = {
  own: ticketDecisionsFor({ id: 114, status: 'approved', owner: 'claude-code' }).map(p => p[0]),
  chat: ticketDecisionsFor({ id: 115, status: 'approved', owner: 'chat-agent:agy' }).map(p => p[0]),
  plain: ticketDecisionsFor({ id: 116, status: 'approved' }).map(p => p[0]),
  sameFile: (ticketBlocker({ id: 1, paths: ['static/app.js'] }) || {}).ticket || 0,
  folder: (ticketBlocker({ id: 2, target: 'static/' }) || {}).ticket || 0,
  noFiles: (ticketBlocker({ id: 3, target: 'make it faster' }) || {}).ticket || 0,
  other: (ticketBlocker({ id: 4, paths: ['docs/DEVLOG.md'] }) || {}).ticket || 0,
  prefix: (ticketBlocker({ id: 5, paths: ['static/app.js.map'] }) || {}).ticket || 0,
  itself: (ticketBlocker({ id: 113, paths: ['static/app.js'] }) || {}).ticket || 0,
  text: leaseWaitText(ticketLeases[0]),
};
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class LeaseUi(unittest.TestCase):
    def setUp(self):
        r = subprocess.run(["node", "-e", i18n_prelude() + HARNESS, str(APP)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.out = json.loads(r.stdout)

    def test_another_agents_ticket_offers_only_hand_over_and_drop(self):
        self.assertEqual(self.out["own"], ["disown", "decline"])
        self.assertEqual(self.out["chat"], ["go", "delegate", "decline"])
        self.assertEqual(self.out["plain"], ["go", "delegate", "decline"])

    def test_waiting_follows_the_files(self):
        self.assertEqual((self.out["sameFile"], self.out["folder"], self.out["noFiles"]), (113, 113, 113))
        self.assertEqual((self.out["other"], self.out["prefix"], self.out["itself"]), (0, 0, 0))
        self.assertEqual(self.out["text"], "잠금 대기 · #113 static/app.js ~10:53")


if __name__ == "__main__":
    unittest.main()
