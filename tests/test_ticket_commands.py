"""[반려] waits for its reason (static/app-evolution.js): the button types `/ticket rework N ` and waits; Enter with no
reason sent the bare command to the agent as a plain message (#715, 2026-10-06). Now the page keeps it -- a notice
asks for the reason, the command stays in the box, nothing is decided and nothing reaches the agent.
The REAL functions run in node against stubs.
Run: python3 -m unittest tests.test_ticket_commands  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

HARNESS = r"""
const fs = require('fs');
const evo = fs.readFileSync(process.argv[1], 'utf8');
const cut = (a, b) => evo.slice(evo.indexOf(a), evo.indexOf(b, evo.indexOf(a)));
const code = cut('function parseTicketCommand', '\n}\n') + '\n}\n' + cut('async function runTicketDecision', '// Who owns it');
const log = { notices: [], decided: [], sent: 0, focused: 0 };
const inputEl = { value: '', focus() { log.focused++; } };
const env = { inputEl, addNotice: (k, t) => log.notices.push(k + ':' + t), loadTickets() {}, updateSendButton() {},
  decideTicket: async (c) => { log.decided.push(c.action + ' ' + c.id + ' ' + c.comment); return 'ok'; },
  goTicket: async () => ({}), send: async () => { log.sent++; }, obsErrorText: String };
const names = Object.keys(env);
const api = new Function(...names, code + '; return { parseTicketCommand, runTicketDecision };')(...names.map(k => env[k]));
(async () => {
  const bare = api.parseTicketCommand('/ticket rework 715');
  const bareRan = await api.runTicketDecision(bare, {});
  const kept = { box: inputEl.value, decided: log.decided.slice(), notices: log.notices.slice(), sent: log.sent, focused: log.focused };
  const full = api.parseTicketCommand('/ticket rework 715 fix the claims');
  await api.runTicketDecision(full, {});
  console.log(JSON.stringify({ bare, bareRan, kept, full, decided: log.decided }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ReworkNeedsAReason(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-evolution.js")], capture_output=True, text=True,
                           timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_bare_rework_is_the_pages_not_the_agents(self):
        self.assertEqual(self.o["bare"], {"action": "rework", "id": 715, "comment": ""})

    def test_it_asks_for_the_reason_and_keeps_the_command(self):
        kept = self.o["kept"]
        self.assertEqual((kept["box"], kept["decided"], kept["sent"]), ("/ticket rework 715 ", [], 0))
        self.assertTrue(kept["notices"] and kept["notices"][0].startswith("warn:"))
        self.assertFalse(self.o["bareRan"])

    def test_with_a_reason_it_is_decided(self):
        self.assertEqual(self.o["full"]["comment"], "fix the claims")
        self.assertEqual(self.o["decided"], ["rework 715 fix the claims"])


if __name__ == "__main__":
    unittest.main()
