"""The model button sits in the composer's right corner (MODEL_TAG_v2, static/model-picker.js placeModelTag): named by
the model when the name takes at most a third of the empty box, else only its icon; placed left of the inline button
on the input's last line; the input keeps clear of it. Typing, a short screen and an open phone keyboard leave the
icon. The REAL function runs in node; markup and CSS are read.
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
const code = src.slice(src.indexOf('function modelLabel'), src.indexOf('function composerPlaceholder'))
  + src.slice(src.indexOf('const MODEL_TAG_ROOM'), src.indexOf('function refreshModelTag'));
const { placeModelTag } = new Function(code + '; return { placeModelTag };')();
const input = (inline, width, value) => ({ offsetParent: { clientWidth: 600 }, offsetLeft: 100, offsetWidth: width || 400, offsetTop: 10,
  offsetHeight: 42, value: value || '', classList: { contains: (c) => inline && c === 'has-inline-btn' },
  style: { v: null, setProperty(k, v) { this.v = v; } } });
// the button is as wide as its name, or 26px as an icon
const button = () => { const name = { textContent: '' }; const cls = new Set();
  return { name, style: {}, querySelector: () => name,
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c) },
    get offsetWidth() { return cls.has('icon-only') ? 26 : name.textContent.length * 6 + 12; } }; };
const out = {};
let b = button(), i = input(true); placeModelTag(b, i, 'gemini-3.8-flash-low');
out.wide = { name: b.name.textContent, icon: b.classList.contains('icon-only'), right: b.style.right, top: b.style.top, w: i.style.v };
b = button(); i = input(true, 240); placeModelTag(b, i, 'gemini-3.8-flash-low');
out.narrow = { icon: b.classList.contains('icon-only'), w: i.style.v };
b = button(); i = input(false, 400, '타이핑 중'); i.style.v = '138px'; placeModelTag(b, i, 'm');
out.typing = { name: b.name.textContent, w: i.style.v, right: b.style.right };
b = button(); i = input(false); i.offsetParent = null; placeModelTag(b, i, '');
out.detached = { name: b.name.textContent, right: b.style.right || '' };
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Placement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "model-picker.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_name_that_fits_is_shown_left_of_the_inline_button_on_the_last_line(self):
        self.assertEqual(self.o["wide"], {"name": "gemini-3.8-flash-low", "icon": False, "right": "144px", "top": "31px",
                                          "w": "138px"})

    def test_a_name_too_wide_for_the_box_becomes_the_icon(self):
        self.assertEqual(self.o["narrow"], {"icon": True, "w": "32px"})

    def test_typing_moves_it_but_keeps_the_empty_box_width(self):
        self.assertEqual(self.o["typing"], {"name": "m", "w": "138px", "right": "110px"})

    def test_a_hidden_composer_still_gets_the_name(self):
        self.assertEqual(self.o["detached"], {"name": "기본 모델", "right": ""})


class MarkupAndStyle(unittest.TestCase):
    def test_the_one_model_button_follows_the_input_and_carries_the_name(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertEqual(page.count('id="modelBtn"'), 1)
        self.assertNotIn('id="modelTag"', page)
        self.assertLess(page.index('id="input"'), page.index('id="modelBtn"'))
        self.assertLess(page.index('id="modelBtn"'), page.index('id="send"'))
        btn = page[page.index('id="modelBtn"'):page.index("</button>", page.index('id="modelBtn"'))]
        self.assertIn("model-tag", btn)
        self.assertIn('<span class="model-name"></span>', btn)

    def test_text_a_short_screen_and_the_phone_keyboard_leave_the_icon(self):
        css = (STATIC / "chat-composer.css").read_text(encoding="utf-8")
        for when in ("#modelBtn.model-tag.icon-only .model-name", "#input:not(:placeholder-shown) ~ #modelBtn.model-tag .model-name",
                     "body.keyboard-open .composer #modelBtn.model-tag .model-name"):
            self.assertIn(when, css)
        resp = (STATIC / "chat-responsive.css").read_text(encoding="utf-8")
        short = resp[resp.index("@media (max-height: 500px)"):]
        self.assertIn(".composer #modelBtn.model-tag .model-name{display:none}", short[:short.index("\n}")])
        self.assertNotRegex(resp, r"#modelBtn\s*(,[^{]*)?\{\s*display:none", "the model is always reachable")

    def test_the_input_keeps_clear_of_it(self):
        css = (STATIC / "chat-composer.css").read_text(encoding="utf-8")
        self.assertIn("#input:placeholder-shown{padding-right:calc(.75rem + var(--model-tag-w, 0px))}", css)
        self.assertIn("#input.has-inline-btn:not(:placeholder-shown){padding-right:calc(2.9rem + 30px)}", css)


if __name__ == "__main__":
    unittest.main()
