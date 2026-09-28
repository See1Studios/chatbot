"""The model in use sits small in the composer's right corner (MODEL_TAG_v1, static/model-picker.js placeModelTag):
named by the model, placed left of the inline button from the input's own box, and the placeholder keeps clear of it
while the box is empty; once there is text it hides. The REAL function runs in node; markup and CSS are read.
Run: python3 -m unittest tests.test_model_tag  (from services/chatbot)
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
const src = fs.readFileSync(process.argv[1], 'utf8');
eval(src.slice(src.indexOf('function modelLabel'), src.indexOf('function composerPlaceholder')));
eval(src.slice(src.indexOf('function placeModelTag'), src.indexOf('function refreshModelTag')));
const input = (inline) => ({ offsetParent: { clientWidth: 600 }, offsetLeft: 100, offsetWidth: 400, offsetTop: 10, offsetHeight: 42,
  classList: { contains: (c) => inline && c === 'has-inline-btn' }, vars: {}, style: { setProperty(k, v) { this.v = v; } } });
const tag = () => ({ textContent: '', style: {}, get offsetWidth() { return this.textContent ? 90 : 0; } });
const out = {};
let t = tag(), i = input(true); placeModelTag(t, i, 'gemini-3.8-flash-low');
out.inline = { text: t.textContent, right: t.style.right, top: t.style.top, w: i.style.v };
t = tag(); i = input(false); placeModelTag(t, i, '');
out.plain = { text: t.textContent, right: t.style.right };
t = tag(); i = input(false); i.offsetParent = null; placeModelTag(t, i, 'm');
out.detached = { text: t.textContent, right: t.style.right || '' };
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Placement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "model-picker.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_it_names_the_model_left_of_the_inline_button_and_centred(self):
        self.assertEqual(self.o["inline"], {"text": "gemini-3.8-flash-low", "right": "144px", "top": "31px", "w": "96px"})

    def test_without_an_inline_button_it_hugs_the_edge_and_names_the_default(self):
        self.assertEqual(self.o["plain"], {"text": "기본 모델", "right": "110px"})

    def test_a_hidden_composer_still_gets_the_name(self):
        self.assertEqual(self.o["detached"], {"text": "m", "right": ""})


class MarkupAndStyle(unittest.TestCase):
    def test_the_tag_follows_the_input_so_the_sibling_rule_can_hide_it(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(page.index('id="input"'), page.index('id="modelTag"'))
        self.assertLess(page.index('id="modelTag"'), page.index('id="send"'))
        self.assertIn('aria-hidden="true"', page[page.index('id="modelTag"') - 40:page.index('id="modelTag"') + 120],
                      "#modelBtn already names the model for screen readers")

    def test_the_placeholder_keeps_clear_and_text_hides_the_tag(self):
        css = (STATIC / "chat-composer.css").read_text(encoding="utf-8")
        self.assertIn("#input:not(:placeholder-shown) ~ .model-tag{visibility:hidden}", css)
        self.assertIn("#input:placeholder-shown{padding-right:calc(.75rem + var(--model-tag-w, 0px))}", css)
        self.assertIn("#input.has-inline-btn:placeholder-shown{padding-right:calc(2.9rem + var(--model-tag-w, 0px))}", css)

    def test_the_placeholder_no_longer_carries_the_model(self):
        turn = (STATIC / "app-turn.js").read_text(encoding="utf-8")
        self.assertIn("composerPlaceholder({", turn)
        self.assertIn("refreshModelTag()", turn)


if __name__ == "__main__":
    unittest.main()
