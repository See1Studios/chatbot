"""Provider chrome follows the session, not per-device localStorage.

Chat history already resyncs across devices. The picker used to keep
chatbot.provider in localStorage and POST it on every send, so a stale
phone could overwrite the live session (and keep showing the old portrait).
Run: python3 -m unittest tests.test_provider_sync  (from services/chatbot)
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "static" / "app.js"
HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a + from.length);
  if (a < 0 || b < 0) throw new Error('marker missing: ' + from + ' .. ' + to);
  return src.slice(a, b);
}
const fields = slice('function providerFieldsForSend', 'function applySessionProvider');
const apply = slice('function applySessionProvider', 'async function persistSessionProvider');
const resync = slice('async function resyncFromServer', 'function startSessionSyncLoop');

const store = {};
const localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};
const providerEl = { value: 'agy' };
const modelEl = { value: 'gemini-3-flash' };
let lastServerProvider = 'agy';
let lastServerModel = 'gemini-3-flash';
let localProviderEdit = 0;
const providerCatalog = [
  { id: 'agy', name: 'Antigravity', theme: 'spark' },
  { id: 'openrouter', name: 'OpenRouter', theme: 'lime' },
];
const calls = { avatar: 0, theme: 0, models: 0, tray: 0, follow: 0 };
function updateBrandAvatar() { calls.avatar++; }
function followChatProvider() { calls.follow++; }
function populateModelsForProvider(pid, mid) {
  calls.models++;
  if (mid) modelEl.value = mid;
}
function renderProviderTray() { calls.tray++; }
function applyTheme() { calls.theme++; }
function themeForProvider(p) { return p && p.theme; }
function syncModelUi() {}

eval(fields + apply);
const out = {
  match: providerFieldsForSend('agy', 'gemini-3-flash', 'agy', 'gemini-3-flash'),
  localSwitch: providerFieldsForSend('openrouter', 'openrouter/free', 'agy', 'gemini-3-flash'),
  staleUiSameCache: providerFieldsForSend('agy', 'gemini-3-flash', 'agy', 'gemini-3-flash'),
};
out.applied = applySessionProvider({ provider: 'openrouter', model: 'openrouter/free' });
out.afterApply = {
  pid: providerEl.value, mid: modelEl.value,
  lastP: lastServerProvider, lastM: lastServerModel,
  ls: store['chatbot.provider'], avatar: calls.avatar,
};
out.noopSame = applySessionProvider({ provider: 'openrouter', model: 'openrouter/free' });
localProviderEdit = 1;
providerEl.value = 'claude';
out.locked = applySessionProvider({ provider: 'openrouter', model: 'openrouter/free' });
out.lockedPid = providerEl.value;
localProviderEdit = 0;

out.resyncCallsApply = /applySessionProvider\(info\)/.test(resync);
out.sendOmitsWhenSynced = Object.keys(out.match).length === 0;
out.sendIncludesWhenLocal = out.localSwitch.provider === 'openrouter'
  && out.localSwitch.model === 'openrouter/free';
console.log(JSON.stringify(out));
"""


class ProviderSync(unittest.TestCase):
    def test_source_wires_resync_and_send(self):
        app = APP.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        self.assertIn("function providerFieldsForSend", app)
        self.assertIn("function applySessionProvider", app)
        self.assertIn("applySessionProvider(info)", app)
        self.assertIn("providerFieldsForSend(", app)
        self.assertNotIn(
            "provider: providerEl ? providerEl.value : 'agy'",
            app.split("async function send()")[1].split("async function")[0]
            if "async function send()" in app else app,
        )
        self.assertRegex(html, r"app\.js\?v=\d+")
        self.assertNotIn("app.js?v=100", html)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_fields_and_apply(self):
        r = subprocess.run(
            ["node", "-e", HARNESS, str(APP)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        o = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(o["match"], {})
        self.assertTrue(o["sendOmitsWhenSynced"])
        self.assertTrue(o["sendIncludesWhenLocal"])
        self.assertTrue(o["applied"])
        self.assertEqual(o["afterApply"]["pid"], "openrouter")
        self.assertEqual(o["afterApply"]["mid"], "openrouter/free")
        self.assertEqual(o["afterApply"]["lastP"], "openrouter")
        self.assertEqual(o["afterApply"]["ls"], "openrouter")
        self.assertGreater(o["afterApply"]["avatar"], 0)
        self.assertFalse(o["noopSame"])
        self.assertFalse(o["locked"])
        self.assertEqual(o["lockedPid"], "claude")
        self.assertTrue(o["resyncCallsApply"])


if __name__ == "__main__":
    unittest.main()
