"""A brand-new session opens with a quiet centered divider, not the assistant greeting bubble (#160).
continueSession shows its handoff note as a system notice, not an assistant turn (#196).
A continue waits for its handoff summary, and a slow scrollback hop is retried, not routed around (#609).
Run: python3 -m unittest tests.test_session_marker  (from services/chatbot)
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'static'
SRC = (STATIC / 'app-session.js').read_text(encoding='utf-8')
API = (STATIC / 'app-api.js').read_text(encoding='utf-8')


def func_body(name):
    start = SRC.index('function ' + name + '(')
    nxt = re.search(r'\n(?:async )?function \w+\(', SRC[start + 1:])
    return SRC[start:start + 1 + nxt.start()] if nxt else SRC[start:]


def enter_call(body):
    start = body.index('enterSession(')
    return body[start:body.index('});', start)]


class SessionMarkerTest(unittest.TestCase):
    def test_create_session_passes_marker_not_greeting(self):
        call = enter_call(func_body('createSession'))
        self.assertIn("sessionMarker: data.session.id", call)   # #421: the divider names it; the id is advanced-only
        self.assertNotIn('greeting:', call)

    def test_enter_session_renders_marker_as_divider(self):
        body = func_body('enterSession')
        block = body[body.index('if (opts.sessionMarker)'):]
        block = block[:block.index('}') + 1]
        self.assertIn("className = 'msg scrollback-marker flow-line", block)   # the day divider's look (#421)
        self.assertIn('textContent = opts.sessionMarker', block)
        self.assertNotIn('innerHTML', block)
        self.assertIn('logEl.appendChild(marker)', block)

    def test_continue_session_shows_handoff_as_notice(self):
        call = enter_call(func_body('continueSession'))
        self.assertIn('notice:', call)
        self.assertNotIn('greeting:', call)


    def test_both_continue_calls_wait_for_the_summary(self):
        # 2026-10-03: the default 12 s timeout gave up on a 42 s handoff and opened an unlinked new session
        self.assertIn('timeoutMs: CONTINUE_TIMEOUT_MS', func_body('continueSession'))
        hard = API[API.index('async function maybeRedirectHardSession('):]
        self.assertIn('timeoutMs: CONTINUE_TIMEOUT_MS', hard[:hard.index('await createSession()')])
        self.assertGreaterEqual(int(re.search(r'const CONTINUE_TIMEOUT_MS = (\d+);', API).group(1)), 120000)


HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const pick = n => { const a = src.indexOf('function ' + n + '('); const s = src.lastIndexOf('\n', a) + 1;
  const m = /\n(?:async )?function \w+\(/g; m.lastIndex = a + 1; const r = m.exec(src); return src.slice(s, r ? r.index : undefined); };
const nodes = [];
const el = () => ({ className: '', textContent: '', classList: { add() {} }, remove() { nodes.splice(nodes.indexOf(this), 1); },
  querySelectorAll: () => [] });
global.document = { createElement: () => el() };
global.logEl = { firstChild: null, scrollHeight: 0, scrollTop: 0, insertBefore: n => nodes.push(n),
  querySelectorAll: () => [] };
let fallbackCalls = 0;
global.api = async () => { const e = new Error('aborted'); e.name = 'AbortError'; throw e; };
eval(pick('loadOlderHistory'));
global.resolveScrollbackFallback = async () => { fallbackCalls++; return 'unrelated-old'; };
global.scrollbackLoading = false; global.scrollbackExhausted = false;
global.scrollbackSid = 'linked-prev'; global.scrollbackVisited = new Set();
loadOlderHistory().then(() => console.log(JSON.stringify({ sid: scrollbackSid, fallbackCalls,
  exhausted: scrollbackExhausted, loading: scrollbackLoading, visited: [...scrollbackVisited] })));
"""


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class SlowScrollbackHopTest(unittest.TestCase):
    def test_a_timeout_keeps_the_link_and_does_not_jump(self):
        p = subprocess.run(['node', '-e', HARNESS, str(STATIC / 'app-session.js')], capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        import json
        got = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(got, {'sid': 'linked-prev', 'fallbackCalls': 0, 'exhausted': False, 'loading': False,
                               'visited': []})


if __name__ == '__main__':
    unittest.main()
