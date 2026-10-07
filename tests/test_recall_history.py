"""Up and Down recall sent messages like a shell (RECALL_SENT_v1, static/app-recall.js): Up only from an empty box,
the walk goes on while the recalled text is unchanged, Down past the newest empties the box, an edit ends the walk,
and the open slash menu keeps its arrows. The REAL module runs in node against stubs.
Run: python3 -m unittest tests.test_recall_history  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

ROOT = REPO
STATIC = ROOT / "static"

HARNESS = r"""
const fs = require('fs');
const listeners = {};
const document = { addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); },
                   getElementById: (id) => (id === 'input' ? inputEl : null) };
const store = {};
const localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
const inputEl = { id: 'input', value: '', selectionStart: 0, selectionEnd: 0 };
let slashMenuEl = { hidden: true };
let cleared = 0;
const clearRetry = () => { cleared += 1; };
const actBare = (t) => t === '/act';
eval(fs.readFileSync(process.argv[1], 'utf8'));
const key = (k, extra) => { let stopped = false;
  (listeners.keydown || []).forEach(f => f(Object.assign({ target: inputEl, key: k, shiftKey: false, preventDefault() { stopped = true; } }, extra || {})));
  return stopped; };
const send = (t) => { inputEl.value = t; key('Enter'); inputEl.value = ''; };
const out = {};
out.emptyHistoryUp = [key('ArrowUp'), inputEl.value];
send('첫째'); send('/act '); send('둘째'); send('둘째'); send('셋째\n두 줄');
out.stored = JSON.parse(store['pe.sentHistory']);
const walk = [];
for (const k of ['ArrowUp', 'ArrowUp', 'ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowDown']) { key(k); walk.push(inputEl.value); }
out.walk = walk;
out.caret = (key('ArrowUp'), inputEl.selectionStart === inputEl.value.length);
inputEl.value = '셋째\n두 줄 고침'; out.editedUp = [key('ArrowUp'), inputEl.value];
out.editedDown = [key('ArrowDown'), inputEl.value];
inputEl.value = '쓰던 글'; out.draftUp = key('ArrowUp');
inputEl.value = ''; slashMenuEl.hidden = false; out.slashUp = key('ArrowUp'); slashMenuEl.hidden = true;
out.imeUp = key('ArrowUp', { isComposing: true });
out.shiftUp = key('ArrowUp', { shiftKey: true });
out.clearedRetry = cleared > 0;
for (let i = 0; i < 130; i++) send('m' + i);
out.capped = JSON.parse(store['pe.sentHistory']).length;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RecallHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-recall.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_sent_messages_are_kept_without_repeats(self):
        self.assertEqual(self.o["stored"], ["첫째", "둘째", "셋째\n두 줄"], "a bare /act is held, not remembered")
        self.assertEqual(self.o["emptyHistoryUp"], [False, ""])

    def test_up_walks_back_and_down_returns_to_the_empty_box(self):
        self.assertEqual(self.o["walk"], ["셋째\n두 줄", "둘째", "첫째", "첫째", "둘째", "셋째\n두 줄", ""])
        self.assertTrue(self.o["caret"], "the caret goes to the end, like a shell")

    def test_an_edit_or_a_draft_keeps_the_arrows_for_the_text(self):
        self.assertEqual(self.o["editedUp"], [False, "셋째\n두 줄 고침"])
        self.assertEqual(self.o["editedDown"], [False, "셋째\n두 줄 고침"])
        self.assertFalse(self.o["draftUp"])

    def test_slash_menu_ime_and_shift_keep_their_keys(self):
        self.assertFalse(self.o["slashUp"])
        self.assertFalse(self.o["imeUp"])
        self.assertFalse(self.o["shiftUp"])

    def test_a_recalled_message_drops_a_waiting_retry_and_history_is_capped(self):
        self.assertTrue(self.o["clearedRetry"])
        self.assertEqual(self.o["capped"], 100)


class Wiring(unittest.TestCase):
    def test_loaded_after_retry_and_before_the_send_handlers(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(page.index("app-retry.js"), page.index("app-recall.js"))
        self.assertLess(page.index("app-recall.js"), page.index("app.js?"))


if __name__ == "__main__":
    unittest.main()
