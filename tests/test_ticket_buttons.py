"""Decision buttons act at once, with no bubble (TICKET_BUTTONS_v1, static/app-evolution.js): a work card's [실행],
[경로 허용], [폐기], [병합] ... decide on the spot and leave only the notice -- nothing in the box, nothing in the log.
[반려] and [계획 수정] put their text in the box and wake the send button (FILL_COMPOSER_v1, app-turn.js), which
setting inputEl.value alone never did. The REAL functions run in node against stubs.
Run: python3 -m unittest tests.test_ticket_buttons  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

HARNESS = r"""
const fs = require('fs');
const [evo, turn] = process.argv.slice(1).map(p => fs.readFileSync(p, 'utf8'));
const cut = (src, a, b) => src.slice(src.indexOf(a), src.indexOf(b, src.indexOf(a)));
const code = cut(evo, 'function ticketDecisionText', 'function parseTicketCommand')
  + cut(evo, '// TICKET_BUTTONS_v1', '// Who owns it')
  + cut(turn, 'function fillComposer', 'function composerSendable');
const log = { notices: [], chats: 0, decided: [], sent: [], sendable: null };
const inputEl = { value: '', focus() {} };
const env = { inputEl, switchTab() {}, loadTickets() {}, autoResizeInput() {},
  updateSendButton: () => { log.sendable = Boolean(inputEl.value.trim()); },
  addNotice: (k, t) => log.notices.push(t), addChat: () => { log.chats++; },
  decideTicket: async (c) => { log.decided.push(c.action + ' ' + c.id); return 'ok ' + c.action; },
  goTicket: async (c) => ({ message: '', prompt: 'do #' + c.id }),
  send: async () => { log.sent.push(inputEl.value); inputEl.value = ''; },
  obsErrorText: (e) => String(e), tapSendOpts: () => ({ keepFocus: false }) };
const names = Object.keys(env);
const api = new Function(...names, code + '; return { fillTicketCommand };')(...names.map(k => env[k]));
(async () => {
  api.fillTicketCommand({ id: 7 }, 'merge'); await new Promise(r => setTimeout(r, 5));
  const merge = { box: inputEl.value, chats: log.chats, decided: log.decided.slice(), notices: log.notices.slice() };
  api.fillTicketCommand({ id: 7 }, 'go'); await new Promise(r => setTimeout(r, 5));
  const go = { sent: log.sent.slice(), chats: log.chats };
  api.fillTicketCommand({ id: 7 }, 'rework');
  const rework = { box: inputEl.value, sendable: log.sendable, decidedCount: log.decided.length };
  console.log(JSON.stringify({ merge, go, rework }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TicketButtons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-evolution.js"), str(STATIC / "app-turn.js")],
                           capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_decision_acts_at_once_with_no_bubble(self):
        self.assertEqual(self.o["merge"], {"box": "", "chats": 0, "decided": ["merge 7"], "notices": ["ok merge"]})

    def test_go_hands_the_agent_its_instruction(self):
        self.assertEqual(self.o["go"], {"sent": ["do #7"], "chats": 0})

    def test_rework_waits_for_the_comment_with_the_send_button_awake(self):
        self.assertEqual(self.o["rework"], {"box": "/ticket rework 7 ", "sendable": True, "decidedCount": 1})

    def test_other_fills_wake_the_send_button_too(self):
        evo = (STATIC / "app-evolution.js").read_text(encoding="utf-8")
        self.assertIn("fillComposer('#' + r.ticket + ' 계획 수정: ')", evo)
        self.assertIn("fillComposer(text)", (STATIC / "artifacts.js").read_text(encoding="utf-8"))
        md = (STATIC / "markdown.js").read_text(encoding="utf-8")
        self.assertIn("runTicketDecision(ticketCmd", md, "chips share the one decision path")

    def test_work_card_has_no_redundant_talk_button(self):
        evo = (STATIC / "app-evolution.js").read_text(encoding="utf-8")
        self.assertNotIn("대화 보기", evo)

WORK_NOW = r"""
const fs = require('fs');
const evo = fs.readFileSync(process.argv[1], 'utf8');
const a = evo.indexOf('// WORK_NOW_v1'), b = evo.indexOf('function renderInProgressRow');
const inProgressRows = new Function(evo.slice(a, b) + '; return inProgressRows;')();
const all = [{ id: 5, status: 'in_progress', title: 'mine', worked_by: 'claude-code' },
             { id: 9, status: 'in_progress', title: 'lease ran out', worked_by: 'agy' },
             { id: 7, status: 'approved', title: 'a decision, not work in progress' }];
const leases = [{ ticket: 5, paths: ['a.py'], until: '2026-09-29 18:40:00', actor: 'claude-code' }];
console.log(JSON.stringify(inProgressRows(all, leases)));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class WorkInProgress(unittest.TestCase):
    """WORK_NOW_v1 (#417): held tickets show in the improvement tab with holder, locked files and deadline."""

    def test_held_tickets_are_listed_with_their_lease(self):
        out = subprocess.run(["node", "-e", WORK_NOW, str(STATIC / "app-evolution.js")], capture_output=True, text=True,
                             timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = json.loads(out.stdout)
        self.assertEqual([r["id"] for r in rows], [9, 5])                        # newest first, no decisions
        self.assertEqual((rows[1]["holder"], rows[1]["paths"], rows[1]["until"]), ("claude-code", ["a.py"], "18:40"))
        self.assertEqual((rows[0]["holder"], rows[0]["until"]), ("agy", ""))    # no live lease: shown as expired


if __name__ == "__main__":
    unittest.main()
