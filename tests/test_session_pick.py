"""#863: a session the user opens while a talk goes on stays open. The real openSession() runs in node: a session
picked by hand (noRedirect) of another character or mode is not left to live-follow, which pulled the page to that
character's newest session; send() leaves a rotation or switch alone once the user moved to another session.
Run: engine/run-tests.sh test_session_pick
"""
import json
import re
import shutil
import subprocess
import unittest

from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"

JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('async function openSession(');
const body = src.slice(start, src.indexOf('\n}\n', start) + 3);
const make = new Function('info', body + `
  let sessionMode = 'work', sessionCharacter = 'kit', liveSessionId = '20260101-000000-kitliv', archiveBrowse = false;
  const window = {};
  const api = async () => info;
  const maybeRedirectHardSession = async () => false;
  const enterSession = () => {};
  const isLiveSid = (s) => /^\\d{8}-\\d{6}-/.test(s);
  const tr = (k) => k, applySessionProvider = () => {}, updateBrandAvatar = () => {}, providerEl = null;
  return { openSession, get archiveBrowse() { return archiveBrowse; }, get liveSessionId() { return liveSessionId; } };`);
(async () => {
  const out = {};
  let m = make({ mode: 'work', character: 'other', history: [] });
  await m.openSession('20260101-000000-oldoth', 0, null, true);        // picked: another character's older talk
  out.pickedOther = { pinned: m.archiveBrowse, live: m.liveSessionId };
  m = make({ mode: 'work', character: 'other', history: [] });
  await m.openSession('20260101-000000-newoth');                       // opened by the page (latest): follows
  out.pageOther = { pinned: m.archiveBrowse, live: m.liveSessionId };
  m = make({ mode: 'work', character: 'kit', history: [] });
  await m.openSession('20260101-000000-kitliv', 0, null, true);        // picked: its own live tip
  out.pickedTip = { pinned: m.archiveBrowse };
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SessionPick(unittest.TestCase):
    def run_js(self):
        p = subprocess.run(["node", "-e", JS, str(STATIC / "app-session.js")], capture_output=True, text=True,
                           timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        return json.loads(p.stdout.strip().splitlines()[-1])

    def test_a_picked_session_of_another_character_stays_open(self):
        out = self.run_js()
        self.assertEqual(out["pickedOther"], {"pinned": True, "live": ""}, "live-follow must not pull the page away")
        self.assertEqual(out["pageOther"], {"pinned": False, "live": "20260101-000000-newoth"})
        self.assertFalse(out["pickedTip"]["pinned"], "the live tip itself is followed as before")


class SendGuard(unittest.TestCase):
    def test_an_answer_for_a_session_the_user_left_does_not_pull_them_back(self):
        src = (STATIC / "app.js").read_text(encoding="utf-8")
        send = src[src.index("async function send(opts)"):]
        send = send[:send.index("\n}\n")]
        self.assertRegex(send, r"const sentSid = sessionId;[^\n]*\n  try \{", "declared before the try: the catch reads it")
        self.assertIn("encodeURIComponent(sentSid) + '/message'", send)
        guard = send.index("if (sessionId !== sentSid) return;")
        self.assertLess(guard, send.index("msgRes.rotated"), "checked before a rotation moves the page")
        self.assertRegex(send, re.compile(r"catch \(e\) \{\s+if \(sessionId === sentSid\)"))


if __name__ == "__main__":
    unittest.main()
