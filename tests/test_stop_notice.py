"""Stopping shows one notice (STOP_NOTICE_ONCE_v1): the server's 'stopped' event (static/app-sse.js) is the notice;
the stop button's own (static/app.js) stands in only when that event never comes. The REAL click handler runs in node.
Run: engine/run-tests.sh test_stop_notice
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.page_source import i18n_prelude  # noqa: E402
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"

HARNESS = r"""
const fs = require('fs');
const app = fs.readFileSync(process.argv[1], 'utf8'), sse = fs.readFileSync(process.argv[2], 'utf8');
const decl = sse.slice(sse.indexOf('let lastStopNoticeAt'), sse.indexOf('// A user line that is only'));
const block = app.slice(app.indexOf('if (stopBtn) {'), app.indexOf("const defibBtn"));
const run = async (serverSays) => {
  const notices = [], timers = [];
  let handler = null;
  const stopBtn = { disabled: false, addEventListener: (t, f) => { handler = f; } };
  const env = { stopBtn, sessionId: 's1', assistantNode: null, assistantBuf: '',
    addActivity() {}, setBusy() {}, api: async () => ({ ok: true }),
    addNotice: (kind, text) => { notices.push(text); return { dataset: {} }; },
    setTimeout: (f, ms) => timers.push([f, ms]) };
  const names = Object.keys(env);
  // the block registers the click handler; the returned hook stands in for the stream's 'stopped' event
  const api = new Function(...names, decl + block + `; return { setSeen: () => { lastStopNoticeAt = Date.now() + 1; } };`)
    (...names.map(k => env[k]));
  await handler();
  if (serverSays) api.setSeen();
  timers.forEach(([fn]) => fn());
  return { notices, waits: timers.map(t => t[1]) };
};
(async () => {
  const out = { withEvent: await run(true), withoutEvent: await run(false) };
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class StopNotice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", i18n_prelude() + HARNESS, str(STATIC / "app.js"), str(STATIC / "app-sse.js")],
                           capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_servers_notice_is_the_only_one(self):
        self.assertEqual(self.o["withEvent"]["notices"], [])
        self.assertEqual(self.o["withEvent"]["waits"], [1500])

    def test_without_the_event_the_button_says_it_itself(self):
        self.assertEqual(self.o["withoutEvent"]["notices"], ["작업을 중지했습니다."])

    def test_the_stream_marks_the_notice_it_showed(self):
        sse = (STATIC / "app-sse.js").read_text(encoding="utf-8")
        at = sse.index("if (type === 'stopped') {")
        self.assertIn("lastStopNoticeAt = Date.now();", sse[at:at + 300])


if __name__ == "__main__":
    unittest.main()
