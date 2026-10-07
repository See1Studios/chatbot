"""The session sync poll is a safety net while the stream is open (SYNC_THROTTLE_v1, static/app-session.js syncDue):
with the stream closed it runs every tick; with it open, every 30s, or after 10s of stream silence while a turn runs.
It used to fetch the whole session and the session list every 2.5s. The REAL function runs in node.
Run: python3 -m unittest tests.test_sync_throttle  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const code = src.slice(src.indexOf('const SYNC_SAFETY_MS'), src.indexOf('async function resyncFromServer'));
const { syncDue } = new Function(code + '; return { syncDue };')();
const T = 1000000;
console.log(JSON.stringify({
  closed: syncDue(T, false, false, T - 100, T - 100),
  openQuiet: syncDue(T, true, false, T - 29000, T - 50000),
  openSafety: syncDue(T, true, false, T - 30000, T - 1000),
  busyStreaming: syncDue(T, true, true, T - 20000, T - 2000),
  busyStalled: syncDue(T, true, true, T - 20000, T - 11000),
  busyJustSynced: syncDue(T, true, true, T - 3000, T - 60000),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SyncThrottle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-session.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_closed_stream_syncs_every_tick(self):
        self.assertTrue(self.o["closed"])

    def test_an_open_stream_syncs_only_as_a_safety_net(self):
        self.assertFalse(self.o["openQuiet"])
        self.assertTrue(self.o["openSafety"])

    def test_a_running_turn_syncs_when_the_stream_goes_silent(self):
        self.assertFalse(self.o["busyStreaming"])
        self.assertTrue(self.o["busyStalled"])
        self.assertFalse(self.o["busyJustSynced"])

    def test_the_poll_asks_before_fetching(self):
        src = (STATIC / "app-session.js").read_text(encoding="utf-8")
        loop = src[src.index("function startSessionSyncLoop"):]
        self.assertLess(loop.index("syncDue("), loop.index("followLiveIfNeeded()"))
        self.assertIn("lastStreamAt = Date.now();", (STATIC / "app-sse.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
