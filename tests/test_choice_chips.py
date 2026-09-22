"""Quick-reply chips: an agent's trailing <!--choices: A | B--> becomes buttons.
Runs the REAL splitChoices / renderChoiceChips / syncChoiceChips / pickChoice (extracted
from static/markdown.js) in node against a stub DOM. Skipped when node is not installed.
Run: python3 -m unittest tests.test_choice_chips  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

MD = Path(__file__).resolve().parent.parent / "static" / "markdown.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('const CHOICES_TAIL'), b = src.indexOf('function postProcessAssistant');
if (a < 0 || b < 0) throw new Error('markers missing');
const code = src.slice(a, b);

function el(tag) {
  const e = { tag, className: '', textContent: '', children: [], attrs: {}, handlers: {}, parent: null,
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(t, f) { this.handlers[t] = f; },
    appendChild(c) { c.parent = this; this.children.push(c); return c; },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this); this.parent = null; },
    contains(o) { for (let n = o; n; n = n.parent) if (n === this) return true; return false; },
    all(sel) {
      const cls = sel.replace('.', ''); const out = [];
      (function walk(n) { n.children.forEach(c => { if ((c.className || '').split(' ').includes(cls)) out.push(c); walk(c); }); })(this);
      return out;
    },
    querySelectorAll(sel) { return this.all(sel); },
    querySelector(sel) { return this.all(sel)[0] || null; },
  };
  return e;
}
const logEl = el('div');
// the one selector the stub cannot express: every message div in the log that is not a system notice
const plainQuery = logEl.querySelectorAll;
logEl.querySelectorAll = function (sel) {
  if (sel === '.msg:not(.system)') return this.children.filter(c => /\bmsg\b/.test(c.className) && !/\bsystem\b/.test(c.className));
  return plainQuery.call(this, sel);
};
const sent = [];
const inputEl = { value: '' };
const send = () => { sent.push(inputEl.value); };
const body = code + `
  return { splitChoices, renderChoiceChips, syncChoiceChips, pickChoice };`;
const api = new Function('logEl', 'inputEl', 'send', 'document', body)(logEl, inputEl, send, { createElement: el });

const out = {};
out.plain = api.splitChoices('그냥 답변');
out.full = api.splitChoices('어느 쪽이 좋을까냥?\n\n<!--choices: A. UI 개선 | B. 토큰 최적화-->');
out.trailingWs = api.splitChoices('질문\n<!--choices: 예|아니오-->  \n');
out.capped = api.splitChoices('q <!--choices: 1|2|3|4|5|6-->').choices;
out.emptyItems = api.splitChoices('q <!--choices: a||  | b-->').choices;
out.streamingHalf = api.splitChoices('질문\n<!--choices: A | B');
out.streamingOpenOnly = api.splitChoices('질문\n<!--choices');
out.midText = api.splitChoices('앞 <!--choices: x--> 뒤 내용');
out.otherComment = api.splitChoices('a <!-- note -->').text;

// chips: only the newest message keeps them
function msg(cls) { const m = el('div'); m.className = cls; const md = el('div'); md.className = 'md'; m.appendChild(md); logEl.appendChild(m); return m; }
const m1 = msg('msg assistant'), m2 = msg('msg assistant');
api.renderChoiceChips(m1, ['A', 'B']);
api.renderChoiceChips(m2, ['C', 'D', 'E']);
api.syncChoiceChips();
out.afterTwo = { m1: m1.all('.choice-chips').length, m2: m2.all('.choice-chips').length,
                 labels: m2.all('.choice-chip').map(x => x.textContent) };
const u = msg('msg user');
api.syncChoiceChips();
out.afterUser = { m2: m2.all('.choice-chips').length };
// a system notice after the message must not steal "newest"
const m3 = msg('msg assistant'); api.renderChoiceChips(m3, ['Z']);
msg('msg assistant system');
api.syncChoiceChips();
out.systemIgnored = m3.all('.choice-chips').length;
// click sends the label
m3.all('.choice-chip')[0].handlers.click();
out.sent = sent;
api.renderChoiceChips(m3, []);
out.cleared = m3.all('.choice-chips').length;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ChoiceChips(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(MD)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_plain_text_is_untouched(self):
        self.assertEqual(self.o["plain"], {"text": "그냥 답변", "choices": []})

    def test_trailing_marker_becomes_choices_and_leaves_the_body_clean(self):
        self.assertEqual(self.o["full"]["choices"], ["A. UI 개선", "B. 토큰 최적화"])
        self.assertEqual(self.o["full"]["text"], "어느 쪽이 좋을까냥?")
        self.assertEqual(self.o["trailingWs"], {"text": "질문", "choices": ["예", "아니오"]})

    def test_at_most_four_and_no_empty_labels(self):
        self.assertEqual(self.o["capped"], ["1", "2", "3", "4"])
        self.assertEqual(self.o["emptyItems"], ["a", "b"])

    def test_half_streamed_marker_never_shows(self):
        self.assertEqual(self.o["streamingHalf"], {"text": "질문", "choices": []})
        self.assertEqual(self.o["streamingOpenOnly"], {"text": "질문", "choices": []})

    def test_only_a_trailing_marker_counts(self):
        self.assertEqual(self.o["midText"]["choices"], [])
        self.assertIn("<!--choices: x-->", self.o["midText"]["text"])
        self.assertEqual(self.o["otherComment"], "a <!-- note -->")

    def test_only_the_newest_message_keeps_its_chips(self):
        self.assertEqual(self.o["afterTwo"], {"m1": 0, "m2": 1, "labels": ["C", "D", "E"]})
        self.assertEqual(self.o["afterUser"], {"m2": 0})
        self.assertEqual(self.o["systemIgnored"], 1)

    def test_click_sends_the_label_and_empty_choices_clear_the_row(self):
        self.assertEqual(self.o["sent"], ["Z"])
        self.assertEqual(self.o["cleared"], 0)


if __name__ == "__main__":
    unittest.main()
