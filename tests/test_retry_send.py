"""A failed message waits in the composer placeholder (RETRY_LAST_v1, static/app-retry.js): an empty send takes it
again, typing anything else drops it, an answer settles it, and it belongs to one session. The REAL functions run in
node against stubs; the wiring into app-api.js, app-sse.js and the page is checked in the source.
Run: python3 -m unittest tests.test_retry_send  (from services/chatbot)
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
const [retrySrc, turn, picker] = process.argv.slice(1).map(p => fs.readFileSync(p, 'utf8'));
const listeners = {};
const document = { addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); },
                   getElementById: (id) => (id === 'input' ? inputEl : null) };
const fire = (t, ev) => (listeners[t] || []).forEach(f => f(ev));
class CustomEvent { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } }
const window = { innerWidth: 1200 };
const sendBtn = { disabled: null, dataset: {}, classList: { add() {}, remove() {} }, _html: '',
  set innerHTML(v) { this._html = v; }, set textContent(v) { this._html = ''; }, setAttribute() {}, title: '',
  closest() { return this; } };
const inputEl = { id: 'input', value: '', placeholder: '' };
const modelEl = { value: 'm' };
var sessionId = 's1';
let isBusy = false;
const isInquiry = () => false;
const modelLabel = (m) => 'M';
eval(retrySrc);
eval(turn.slice(turn.indexOf('const SEND_ICON'), turn.indexOf('let turnTimer')));
eval(turn.slice(turn.indexOf('function refreshComposerPlaceholder'), turn.indexOf('function setBusy')));
eval(picker.slice(picker.indexOf('function composerPlaceholder'), picker.indexOf('function modelChoices')));
let turnStartedAt = 0;
const type = (v) => { inputEl.value = v; fire('input', { target: inputEl }); updateSendButton(); };
const enter = () => fire('keydown', { target: inputEl, key: 'Enter', shiftKey: false });
const sent = () => { const v = inputEl.value; inputEl.value = ''; updateSendButton(); return v; };   // app.js send()
const look = () => { refreshComposerPlaceholder(); updateSendButton();
  return { ph: inputEl.placeholder, disabled: sendBtn.disabled, face: sendBtn.dataset.face }; };
const out = {};
out.fresh = look();
inputEl.value = '안녕 오늘 어땠어'; enter(); out.firstSend = sent();
offerRetry(); out.failed = look();
enter(); out.resent = sent(); out.afterResend = look();
offerRetry(); type('다른 말'); out.typed = look(); type('');
out.cleared = look();
offerRetry(); isBusy = true; out.busy = look(); isBusy = false;
sessionId = 's2'; out.otherSession = look(); sessionId = 's1';
fire('keydown', { target: inputEl, key: 'Escape', shiftKey: false, }); out.escaped = look();
retryAnswered(); offerRetry(); out.answered = look();
inputEl.value = '/new'; enter(); sent(); offerRetry(); out.command = look();
inputEl.value = '/act 머리를 쓰다듬는다'; enter(); sent();
fire('api-failed', { detail: { path: '/api/sessions/s1/items', method: 'GET' } }); out.otherApi = look();
fire('api-failed', { detail: { path: '/api/sessions/s1/message', method: 'POST' } }); out.postFailed = look();
out.short = [retryShort('가'.repeat(60)), retryShort('첫 줄\n둘째 줄'), retryShort('가'.repeat(30), 18)];
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RetrySend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-retry.js"), str(STATIC / "app-turn.js"),
                            str(STATIC / "model-picker.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_nothing_failed_means_a_plain_empty_box(self):
        self.assertEqual(self.o["fresh"], {"ph": "메시지 입력…", "disabled": True, "face": "icon"})

    def test_a_failed_message_waits_in_the_placeholder_and_an_empty_send_takes_it(self):
        self.assertEqual(self.o["firstSend"], "안녕 오늘 어땠어")
        self.assertEqual(self.o["failed"], {"ph": "↻ 다시 보내기: 안녕 오늘 어땠어", "disabled": False, "face": "retry"})
        self.assertEqual(self.o["resent"], "안녕 오늘 어땠어")
        self.assertEqual(self.o["afterResend"]["ph"], "메시지 입력…", "sent again, no longer waiting")

    def test_typing_something_else_drops_it_for_good(self):
        self.assertEqual(self.o["typed"]["face"], "icon")
        self.assertNotIn("다시 보내기", self.o["typed"]["ph"])
        self.assertEqual(self.o["cleared"]["disabled"], True, "erasing the new text does not bring it back")

    def test_busy_other_session_escape_and_an_answer_hide_it(self):
        self.assertTrue(self.o["busy"]["disabled"])
        self.assertNotIn("다시 보내기", self.o["busy"]["ph"])
        self.assertNotIn("다시 보내기", self.o["otherSession"]["ph"])
        self.assertNotIn("다시 보내기", self.o["escaped"]["ph"])
        self.assertNotIn("다시 보내기", self.o["answered"]["ph"], "an answered message is not offered")

    def test_only_messages_are_offered_and_only_a_failed_message_post(self):
        self.assertNotIn("다시 보내기", self.o["command"]["ph"], "/new is a command, not a message")
        self.assertNotIn("다시 보내기", self.o["otherApi"]["ph"])
        self.assertEqual(self.o["postFailed"]["ph"], "↻ 다시 보내기: /act 머리를 쓰다듬는다")

    def test_long_text_is_cut_to_its_first_line(self):
        self.assertEqual(self.o["short"], ["가" * 39 + "…", "첫 줄", "가" * 17 + "…"])


class Wiring(unittest.TestCase):
    def test_failures_offer_and_answers_settle(self):
        sse = (STATIC / "app-sse.js").read_text(encoding="utf-8")
        self.assertEqual(sse.count("offerRetry()"), 2, "both error paths: result without an answer, and 'error'")
        self.assertIn("retryAnswered()", sse)
        self.assertIn("new CustomEvent('api-failed'", (STATIC / "app-api.js").read_text(encoding="utf-8"))

    def test_the_page_loads_it_before_the_send_handlers(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(page.index("app-retry.js"), page.index("app.js?"))


if __name__ == "__main__":
    unittest.main()
