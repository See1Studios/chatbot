"""THINKING_VIEW_v1 (plan ux/L, #388): a brain's streamed reasoning reaches the page as `thinking` events, keeps the
turn alive, is never stored, and shows as a strip that folds when the answer starts.
Run: engine/run-tests.sh test_thinking_view
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))

import host_config  # noqa: E402
from providers.adapters import ClaudeAdapter, GrokAdapter  # noqa: E402
from tests.test_conversation_sync import Base as SyncBase  # noqa: E402
from tests.page_source import i18n_prelude  # noqa: E402


class AdaptersSendThinking(SyncBase):
    def test_grok_thought_becomes_thinking(self):
        s = self.make()
        out = GrokAdapter().normalize_line(s, json.dumps({"type": "thought", "data": "hmm, the user"}))
        self.assertEqual(out, [{"event": "thinking", "text": "hmm, the user"}])
        self.assertEqual(GrokAdapter().normalize_line(s, json.dumps({"type": "thought", "data": ""})), [])

    def test_claude_thinking_delta_becomes_thinking(self):
        s = self.make()
        line = {"type": "stream_event", "event": {"type": "content_block_delta",
                                                  "delta": {"type": "thinking_delta", "thinking": "check the file"}}}
        self.assertEqual(ClaudeAdapter().normalize_line(s, json.dumps(line)),
                         [{"event": "thinking", "text": "check the file"}])
        self.assertEqual(s.current_text or "", "")          # reasoning never joins the answer


class ThinkingIsActivityNotRecord(unittest.TestCase):
    def test_thinking_is_never_stored(self):
        self.assertNotIn("thinking", host_config.PERSISTED_LOG_KINDS)

    def test_thinking_resets_the_quiet_clock(self):
        src = (ENGINE / "session_view.py").read_text(encoding="utf-8")
        self.assertIn('elif kind in ("delta", "thinking"):', src)


JS = r"""
function El(tag) {
  this.tagName = tag; this.children = []; this.dataset = {}; this.open = false; this.textContent = '';
  const cls = new Set(); this.classList = { add: c => cls.add(c), contains: c => cls.has(c) };
  Object.defineProperty(this, 'className', { set: v => { cls.clear(); v.split(' ').forEach(c => c && cls.add(c)); } });
  this.scrollTop = 0; this.scrollHeight = 0;
}
El.prototype.appendChild = function (c) { this.children.push(c); return c; };
El.prototype.insertBefore = function (c) { this.children.unshift(c); return c; };
El.prototype.querySelector = function (sel) {
  const want = sel.replace('.', '');
  return this.children.find(c => c.tagName === sel || c.classList.contains(want)) || null;
};
global.document = { createElement: t => new El(t) };
global.setInterval = () => 1; global.clearInterval = () => {};
global.sessionMode = MODE;
eval(require('fs').readFileSync(FILE, 'utf8'));
const node = new El('div');
thinkAppend(node, 'first ');
thinkAppend(node, 'second');
const el = node.children[0];
const live = { open: el.open, live: el.dataset.live, body: el.children[1].textContent, label: el.children[0].textContent };
thinkEnd(node);
console.log(JSON.stringify({ live, after: { open: el.open, live: el.dataset.live, label: el.children[0].textContent },
                             strips: node.children.length }));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class StripFolds(unittest.TestCase):
    def run_js(self, mode):
        code = JS.replace("MODE", json.dumps(mode)).replace("FILE", json.dumps(str(ROOT / "static" / "app-think.js")))
        out = subprocess.run(["node", "-e", i18n_prelude() + code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_open_while_thinking_folded_once_the_answer_starts(self):
        r = self.run_js("work")
        self.assertEqual((r["live"]["open"], r["live"]["live"], r["live"]["body"]), (True, "1", "first second"))
        self.assertTrue(r["live"]["label"].startswith("생각 중"))
        self.assertEqual((r["after"]["open"], r["after"]["live"]), (False, "0"))
        self.assertTrue(r["after"]["label"].startswith("생각 ·"))
        self.assertEqual(r["strips"], 1)

    def test_private_mode_starts_folded(self):
        self.assertFalse(self.run_js("private")["live"]["open"])


if __name__ == "__main__":
    unittest.main()
