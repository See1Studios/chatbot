"""Space on an empty composer starts an action in private mode (ACT_KEY_v1, static/app-act-key.js): only when empty,
not while composing Hangul or with modifiers; Backspace on the bare "/act " takes it back; a bare "/act" is neither
sent nor sendable; the placeholder tells private mode about it. The REAL functions run in node against stubs.
Run: python3 -m unittest tests.test_act_key  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

HARNESS = r"""
const fs = require('fs');
const [actSrc, turn, picker] = process.argv.slice(1).map(p => fs.readFileSync(p, 'utf8'));
const listeners = {};
let privateOn = true;
const document = { addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); },
                   body: { classList: { contains: (c) => c === 'private-session' && privateOn } } };
const window = { innerWidth: 1200 };
const sendBtn = { disabled: null, dataset: {}, classList: { add() {}, remove() {} }, set innerHTML(v) {}, set textContent(v) {},
                  setAttribute() {}, title: '' };
const inputEl = { id: 'input', value: '', placeholder: '', selectionStart: 0, selectionEnd: 0 };
const modelEl = { value: 'm' };
let isBusy = false, turnStartedAt = 0;
const isInquiry = () => false;
const modelLabel = () => 'M';
eval(actSrc);
eval(turn.slice(turn.indexOf('const SEND_ICON'), turn.indexOf('let turnTimer')));
eval(turn.slice(turn.indexOf('function refreshComposerPlaceholder'), turn.indexOf('function setBusy')));
eval(picker.slice(picker.indexOf('function composerPlaceholder'), picker.indexOf('function modelChoices')));
const key = (k, extra) => { const r = { prevented: false, stopped: false };
  (listeners.keydown || []).forEach(f => f(Object.assign({ target: inputEl, key: k, shiftKey: false,
    preventDefault() { r.prevented = true; }, stopPropagation() { r.stopped = true; } }, extra || {})));
  return r; };
const out = {};
out.start = [key(' ').prevented, inputEl.value, inputEl.selectionStart];
out.bareSendable = (updateSendButton(), !sendBtn.disabled);
out.bareEnter = key('Enter');
out.undo = [key('Backspace').prevented, inputEl.value];
inputEl.value = '/act 차를 건넨다'; out.withText = [(updateSendButton(), !sendBtn.disabled), key('Enter').prevented, key('Backspace').prevented];
inputEl.value = '안녕'; out.midText = key(' ').prevented;
inputEl.value = ''; out.ime = key(' ', { isComposing: true }).prevented;
out.shift = key(' ', { shiftKey: true }).prevented;
out.ctrl = key(' ', { ctrlKey: true }).prevented;
refreshComposerPlaceholder(); out.phPrivate = inputEl.placeholder;
privateOn = false; out.work = [key(' ').prevented, inputEl.value];
refreshComposerPlaceholder(); out.phWork = inputEl.placeholder;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ActKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-act-key.js"), str(STATIC / "app-turn.js"),
                            str(STATIC / "model-picker.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_space_on_an_empty_box_starts_an_action(self):
        self.assertEqual(self.o["start"], [True, "/act ", 5])

    def test_a_bare_action_is_not_sent_and_backspace_takes_it_back(self):
        self.assertFalse(self.o["bareSendable"])
        self.assertEqual(self.o["bareEnter"], {"prevented": True, "stopped": True})
        self.assertEqual(self.o["undo"], [True, ""])

    def test_an_action_with_words_is_left_to_the_usual_send(self):
        self.assertEqual(self.o["withText"], [True, False, False])

    def test_space_is_plain_space_elsewhere(self):
        self.assertFalse(self.o["midText"])
        self.assertFalse(self.o["ime"])
        self.assertFalse(self.o["shift"])
        self.assertFalse(self.o["ctrl"])
        self.assertEqual(self.o["work"], [False, ""], "work mode keeps Space")

    def test_the_placeholder_tells_private_mode(self):
        self.assertEqual(self.o["phPrivate"], "메시지 입력… (Space: 행동)")
        self.assertEqual(self.o["phWork"], "메시지 입력…")


class Wiring(unittest.TestCase):
    def test_loaded_before_the_send_handlers(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(page.index("app-act-key.js"), page.index("app.js?"))


if __name__ == "__main__":
    unittest.main()
