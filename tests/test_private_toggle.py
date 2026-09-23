"""The heart button in the composer switches between the work and the private session (PRIVATE_TOGGLE_v1).
Runs the REAL updatePrivateBtn / togglePrivateMode / applyModeSwitch (sliced out of static/app.js) in node
against stubs. Skipped when node is not installed.
Run: python3 -m unittest tests.test_private_toggle  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
APP = CODE / "static" / "app.js"
HTML = CODE / "static" / "index.html"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('async function applyModeSwitch'), b = src.indexOf("if (privateBtn) privateBtn.addEventListener");
if (a < 0 || b < 0) throw new Error('markers missing');
const code = src.slice(a, b);
const cls = new Set(), attrs = {};
const privateBtn = { disabled: false, title: '', classList: { toggle: (c, on) => on ? cls.add(c) : cls.delete(c) },
                     setAttribute: (k, v) => { attrs[k] = v; } };
let sessionId = 'w1', sessionMode = 'work', liveSessionId = 'w1', archiveBrowse = true;
const sent = [], opened = [];
async function api(url, opts) {
  const text = JSON.parse(opts.body).text;
  sent.push([url, text]);
  const target = text === '/private' ? { id: 'p1', mode: 'private' } : { id: 'w1', mode: 'work' };
  return { ok: true, switched: true, session: target };
}
async function openSession(id) { opened.push(id); sessionId = id; updatePrivateBtn(); }
function addActivity() {}
eval(code);
(async () => {
  updatePrivateBtn();
  const before = { pressed: attrs['aria-pressed'], active: cls.has('active') };
  await togglePrivateMode();
  const inPrivate = { mode: sessionMode, live: liveSessionId, archive: archiveBrowse, pressed: attrs['aria-pressed'],
                      active: cls.has('active'), disabled: privateBtn.disabled };
  await togglePrivateMode();
  console.log(JSON.stringify({ before, inPrivate, back: { mode: sessionMode, pressed: attrs['aria-pressed'] }, sent, opened }));
})().catch(e => { console.error(e); process.exit(1); });
"""


class PrivateToggle(unittest.TestCase):
    def test_the_button_is_in_the_composer(self):
        html = HTML.read_text(encoding="utf-8")
        self.assertIn('id="privateBtn"', html)
        self.assertLess(html.find('id="geoBtn"'), html.find('id="privateBtn"'))
        self.assertLess(html.find('id="privateBtn"'), html.find('id="input"'))

    def test_toggling_goes_private_and_back(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        proc = subprocess.run([node, "-e", HARNESS, str(APP)], capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["before"], {"pressed": "false", "active": False})
        self.assertEqual(out["inPrivate"], {"mode": "private", "live": "p1", "archive": False, "pressed": "true",
                                            "active": True, "disabled": False})
        self.assertEqual(out["back"], {"mode": "work", "pressed": "false"})
        self.assertEqual([t for _, t in out["sent"]], ["/private", "/work"])
        self.assertEqual(out["sent"][0][0], "/api/sessions/w1/message")
        self.assertEqual(out["opened"], ["p1", "w1"])


if __name__ == "__main__":
    unittest.main()
