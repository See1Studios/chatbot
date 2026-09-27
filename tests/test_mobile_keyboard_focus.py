"""Taps on skill buttons, choice chips and actions must not pop the virtual keyboard on touch devices
(MOBILE_KEYBOARD_FOCUS_v1): no '/' typed in, no inputEl.focus(). Desktop keeps the old focus behaviour.
Runs the REAL isTouchDevice / tapSendOpts / toggleSlashMenu / applySlashItem / pickChoice in node against stubs.
Skipped when node is not installed.
Run: python3 -m unittest tests.test_mobile_keyboard_focus  (from services/chatbot)
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def fn_src(path, name):
    """Source of one top-level `function name(...) {...}` (ends at the first line that is just '}')."""
    src = (STATIC / path).read_text(encoding="utf-8")
    m = re.search(r"^(?:async )?function %s\(.*?^}\n" % re.escape(name), src, re.S | re.M)
    if not m:
        raise AssertionError("%s missing from %s" % (name, path))
    return m.group(0)


HARNESS = r"""
const touch = process.argv[process.argv.length - 1] === 'touch';
const code = require('fs').readFileSync(0, 'utf8');
const calls = [];
global.window = { matchMedia: q => ({ matches: touch && q === '(pointer: coarse)' }) };
global.requestAnimationFrame = f => f();
global.inputEl = { value: '', focus() { calls.push('focus'); }, blur() { calls.push('blur'); }, setSelectionRange() {} };
global.slashMenuEl = { hidden: true };
global.autoResizeInput = () => {}; global.updateSendButton = () => {};
global.renderSlashMenu = () => { slashMenuEl.hidden = false; };
global.hideSlashMenu = () => { slashMenuEl.hidden = true; };
global.slashIgnoreDismissUntil = 0;
const sent = [];
global.send = opts => { sent.push({ text: inputEl.value, opts: opts || null }); };
eval(code.replace(/^function (\w+)/gm, 'global.$1 = function $1'));
const out = {};
toggleSlashMenu();
out.toggle = { value: inputEl.value, calls: calls.splice(0), open: !slashMenuEl.hidden };
applySlashItem({ name: '/help' });
out.apply = { value: inputEl.value, calls: calls.splice(0) };
pickChoice('네');
pickChoice({ label: '달리기', kind: 'action', payload: '달리기' });
out.sent = sent;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class MobileKeyboardFocusTest(unittest.TestCase):
    def run_case(self, mode):
        code = "\n".join([
            fn_src("app.js", "isTouchDevice"), fn_src("app.js", "tapSendOpts"), fn_src("app.js", "sendAction"),
            fn_src("slash.js", "toggleSlashMenu"), fn_src("slash.js", "applySlashItem"),
            fn_src("markdown.js", "stripOuterParens"), fn_src("markdown.js", "classifyChoicePayload"),   # #243
            fn_src("markdown.js", "parseChoiceItem"), fn_src("markdown.js", "pickChoice"),
            fn_src("markdown.js", "sendPickedChoice"),
        ])
        r = subprocess.run(["node", "-e", HARNESS, "--", mode], input=code, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_touch_taps_never_focus_or_type_slash(self):
        out = self.run_case("touch")
        self.assertEqual(out["toggle"], {"value": "", "calls": [], "open": True})
        self.assertEqual(out["apply"]["value"], "/help ")
        self.assertNotIn("focus", out["apply"]["calls"])
        self.assertIn("blur", out["apply"]["calls"])
        self.assertEqual([s["opts"] for s in out["sent"]], [{"keepFocus": False}] * 2)
        self.assertEqual(out["sent"][1]["text"], "/act 달리기")

    def test_desktop_keeps_focus_and_slash(self):
        out = self.run_case("desktop")
        self.assertEqual(out["toggle"]["value"], "/")
        self.assertIn("focus", out["toggle"]["calls"])
        self.assertIn("focus", out["apply"]["calls"])
        self.assertEqual([s["opts"] for s in out["sent"]], [{"keepFocus": True}] * 2)

    def test_send_only_skips_refocus_on_explicit_keep_focus_false(self):
        src = fn_src("app.js", "send")
        self.assertIn("!(opts && opts.keepFocus === false)", src)   # a click Event still refocuses
        self.assertIn("if (keepFocus) inputEl.focus();", src)
        self.assertIn("return send(opts);", src)


if __name__ == "__main__":
    unittest.main()
