"""The send button says whether there is something to send (SEND_VALIDATE_v1, static/app-turn.js): disabled for an
empty box or while an attached file is still uploading (app-attach.js), an Enter glyph for the plain send, words only
for the busy-time actions (steer, side question). The attach button's icon names the kind of file. The REAL functions
run in node against stubs.
Run: python3 -m unittest tests.test_composer_send  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HARNESS = r"""
const fs = require('fs');
const turn = fs.readFileSync(process.argv[1], 'utf8');
const attach = fs.readFileSync(process.argv[2], 'utf8');
const a = turn.indexOf('const SEND_ICON'), b = turn.indexOf('let turnTimer');
const c = attach.indexOf('function attachIcon'), d = attach.indexOf('function renderAttachmentCards');
const sendBtn = { disabled: null, dataset: {}, classList: { s: new Set(), add(x) { this.s.add(x); }, remove(...x) { x.forEach(y => this.s.delete(y)); } },
  _html: '', set innerHTML(v) { this._html = v; this._text = ''; }, set textContent(v) { this._text = v; this._html = ''; },
  get textContent() { return this._text; }, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, title: '' };
const inputEl = { value: '' };
let isBusy = false, uploading = false;
const isInquiry = (v) => v.endsWith('?');
const attachBusy = () => uploading;
eval(turn.slice(a, b));
eval(attach.slice(c, d));
const look = () => ({ disabled: sendBtn.disabled, icon: sendBtn.dataset.face === 'icon' && sendBtn._html.includes('send-icon'),
                      text: sendBtn.dataset.face === 'text' ? sendBtn._text : '', label: sendBtn.attrs['aria-label'] });
const out = {};
inputEl.value = '   '; updateSendButton(); out.empty = look();
inputEl.value = '안녕'; updateSendButton(); out.text = look();
uploading = true; updateSendButton(); out.uploading = look(); uploading = false;
isBusy = true; inputEl.value = ''; updateSendButton(); out.busyEmpty = look();
inputEl.value = '이건 뭐야?'; updateSendButton(); out.busyBtw = look();
inputEl.value = '이렇게 바꿔'; updateSendButton(); out.busySteer = look();
isBusy = false; updateSendButton(); out.backToIdle = look();
out.icons = [['a.png', 'image/png'], ['r.pdf', ''], ['t.csv', ''], ['x.py', ''], ['notes.md', 'text/markdown'], ['s.mp4', '']]
  .map(([n, m]) => attachIcon(n, m));
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ComposerSend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(ROOT / "static" / "app-turn.js"), str(ROOT / "static" / "app-attach.js")],
                           capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_nothing_to_send_is_a_dimmed_button(self):
        self.assertTrue(self.o["empty"]["disabled"])
        self.assertTrue(self.o["busyEmpty"]["disabled"])

    def test_text_makes_it_live_and_an_upload_holds_it(self):
        self.assertFalse(self.o["text"]["disabled"])
        self.assertTrue(self.o["uploading"]["disabled"], "sending now would leave the file for the next message")

    def test_the_plain_send_is_an_enter_glyph_with_a_name(self):
        for k in ("empty", "text", "backToIdle"):
            self.assertTrue(self.o[k]["icon"], k)
            self.assertEqual(self.o[k]["label"], "보내기")

    def test_busy_time_actions_keep_their_words(self):
        self.assertEqual(self.o["busyBtw"]["text"], "샛길 질문")
        self.assertEqual(self.o["busySteer"]["text"], "끼워 넣기")
        self.assertFalse(self.o["busySteer"]["disabled"])

    def test_the_attach_button_names_the_kind_of_file(self):
        self.assertEqual(self.o["icons"], ["image", "text", "table", "code", "text", "film"])

    def test_the_markup_starts_as_a_dimmed_glyph(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<button id="send" class="primary" data-i18n-aria-label="composer.send" data-i18n-title="composer.send_key" disabled data-face="icon">', html)


if __name__ == "__main__":
    unittest.main()
