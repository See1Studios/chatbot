"""SESSION_OPEN_v1 / CLIENT_ERRORS_v1 (#424): a refresh never hides the conversation behind a new empty session, and
the page's errors reach the host log. ensureSession runs in node against the real file with stubbed calls.
Run: python3 -m unittest tests.test_session_open  (from services/chatbot)
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import client_errors  # noqa: E402
from tests.page_source import i18n_prelude  # noqa: E402

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('// SESSION_OPEN_v1'), b = src.indexOf('\n}\n', src.indexOf('function showSessionOpenFailure')) + 3;
const scenario = process.argv[2];
async function run() {
  const log = { opened: [], created: 0, reported: 0, notices: [] };
  let calls = 0;
  const stubs = `
    let liveSessionId = '', archiveBrowse = false, sessionId = 'saved';
    const SESSION_KEY = 'k';
    const location = { search: '' };
    const localStorage = { removeItem() {} };
    const document = { createElement: () => ({ addEventListener() {} }) };
  `;
  const env = {
    resolveLatestSessionId: async () => 'latest',
    openSession: async (id) => {
      calls++;
      log.opened.push(id);
      if (scenario === 'broken') throw new Error('TypeError in render');
      if (scenario === 'gone') throw new Error('session not found');
      if (scenario === 'flaky' && calls === 1) throw new Error('once');
    },
    createSession: async () => { log.created++; },
    reportClientError: () => { log.reported++; },
    addNotice: (k, t) => { log.notices.push(k); return { appendChild() {}, remove() {} }; },
  };
  const names = Object.keys(env);
  const fn = new Function(...names, stubs + src.slice(a, b) + '; return ensureSession;');
  await fn(...names.map(k => env[k]))();
  console.log(JSON.stringify(log));
}
run();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class EnsureSession(unittest.TestCase):
    def run_js(self, scenario):
        out = subprocess.run(["node", "-e", i18n_prelude() + HARNESS, str(ROOT / "static" / "app-session.js"), scenario],
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_a_failure_is_retried_reported_and_shown_never_replaced_by_an_empty_session(self):
        r = self.run_js("broken")
        self.assertEqual(r["created"], 0)
        self.assertEqual(r["reported"], 2)
        self.assertEqual(r["notices"], ["error"])

    def test_a_session_that_is_really_gone_makes_a_new_one(self):
        r = self.run_js("gone")
        self.assertEqual((r["created"], r["opened"]), (1, ["latest", "saved"]))

    def test_a_passing_failure_opens_on_the_second_try(self):
        r = self.run_js("flaky")
        self.assertEqual((r["created"], r["reported"], r["opened"]), (0, 1, ["latest", "latest"]))


class ClientErrors(unittest.TestCase):
    def test_a_page_error_is_logged_short_and_other_paths_pass_by(self):
        with mock.patch.object(client_errors.obslog, "event") as ev:
            self.assertEqual(client_errors.api("POST", "/api/client-error",
                                               {"name": "TypeError", "message": "x" * 500, "context": "boot"}),
                             (200, {"ok": True}))
        kw = ev.call_args[1]
        self.assertEqual(ev.call_args[0][0], "page.error")
        self.assertEqual((kw["name"], len(kw["msg"]), kw["context"]), ("TypeError", 200, "boot"))
        self.assertIsNone(client_errors.api("POST", "/api/tickets/1/approve", {}))
        self.assertIsNone(client_errors.api("GET", "/api/client-error", None))

    def test_the_route_is_same_origin_like_the_operators_other_calls(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('"/api/delegations*", "/api/rooms*", client_errors.PATH + "*"),', src)
        self.assertIn('_api(room_chat.api, "POST"), _api(client_errors.api, "POST"))),', src)


if __name__ == "__main__":
    unittest.main()
