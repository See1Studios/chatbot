"""The input's height follows the stylesheet in every state, and the documented sizes stay as decided.
(실장님: 하단 위젯들 높이가 상황에 따라 조금씩 다른 것 같은데.) autoResizeInput() used to keep its own
38/42 and 90/120: on a phone the input was 38px while the CSS said 36 (32 with the keyboard up) and the
buttons beside it were 44 (32), and a slash command sent it back to the CSS value until the next keystroke.
Runs the REAL autoResizeInput() / updateViewport() (sliced out of static/app.js) in node against a stub
DOM whose getComputedStyle mimics the stylesheet. Skipped when node is not installed.
Run: python3 -m unittest tests.test_composer_height  (from services/chatbot)
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
APP = STATIC / "app.js"
CSS = (STATIC / "chat.css").read_text(encoding="utf-8")

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function autoResizeInput'), b = src.indexOf('if (window.visualViewport) {');
if (a < 0 || b < 0) throw new Error('markers missing');
const code = src.slice(a, b);

const cls = new Set();
const pointer = { coarse: true };   // touch device (on-screen keyboard) vs mouse + physical keyboard
// what the stylesheet says for #input -- numbers are read from the real chat.css by the Python side
const CSSV = JSON.parse(process.argv[process.argv.length - 2]);
const cssFor = () => cls.has('keyboard-open') ? CSSV.keyboard
  : win.innerWidth <= 640 ? (pointer.coarse ? CSSV.phone : CSSV.narrowMouse)
  : CSSV.wide;
const win = { innerWidth: 1000, visualViewport: { height: 800 }, scrollY: 0, scrollTo() {},
  matchMedia: q => ({ matches: q === '(pointer: coarse)' && pointer.coarse }),
  getComputedStyle() { return cssFor(); } };
const inputEl = { value: '', style: {}, scrollHeight: 0 };
const doc = { activeElement: null, body: { classList: { toggle: (c, on) => { on ? cls.add(c) : cls.delete(c); }, contains: c => cls.has(c) } },
  documentElement: { style: { setProperty() {} } }, getElementById: () => null };
const stubs = { window: win, document: doc, inputEl, logEl: null, currentTab: 'chat', positionSlashMenu() {},
  updateScrollBottomButton() {}, scrollToBottomBtn: null, isUserNearBottom: () => true };
const names = Object.keys(stubs);
const api = new Function(...names, code + '; return { autoResizeInput, updateViewport, keyboardOpenState };')(...names.map(k => stubs[k]));

const out = {};
const size = (value, sh) => { inputEl.value = value; inputEl.scrollHeight = sh; api.autoResizeInput(); return [inputEl.style.height, inputEl.style.overflowY]; };
// 1. sizes derived from the stylesheet, per state
win.innerWidth = 1000; cls.clear();
out.wide = { empty: size('', 0), oneLine: size('hi', 40), grows: size('x\ny\nz', 90), capped: size('long', 300) };
win.innerWidth = 420; cls.clear();
out.phone = { empty: size('', 0), oneLine: size('hi', 38), grows: size('x\ny', 60), capped: size('long', 300) };
cls.add('keyboard-open');
out.keyboard = { empty: size('', 0), oneLine: size('hi', 34), capped: size('long', 300) };
// 2. a max-height of 'none' / an unreadable min fall back
win.getComputedStyle = () => ({ minHeight: 'auto', maxHeight: 'none' });
out.fallback = { empty: size('', 0), capped: size('long', 400) };

// 3. the input follows the state as it flips (the real FAB: an iframe 420px wide on a desktop)
let calls = 0;
win.getComputedStyle = () => { calls++; return cssFor(); };
cls.clear(); inputEl.value = ''; inputEl.style.height = '';
const _reset = () => { win.innerWidth = 1000; doc.activeElement = null; api.updateViewport(); };   // back to a known mode
const steps = [];
const step = (label) => steps.push([label, inputEl.style.height, cls.has('keyboard-open')]);
win.innerWidth = 1000; doc.activeElement = null; api.updateViewport(); step('wide, idle');
doc.activeElement = inputEl; api.updateViewport(); step('wide, focused');
win.innerWidth = 420; doc.activeElement = null; api.updateViewport(); step('420px (FAB), idle');
const callsIdle = calls; api.updateViewport(); out.noRemeasureWhenNothingChanged = calls === callsIdle;
doc.activeElement = inputEl; api.updateViewport(); step('420px (FAB), focused');
doc.activeElement = null; api.updateViewport(); step('420px (FAB), blurred');
win.visualViewport.height = 480; api.updateViewport(); step('420px, short viewport'); win.visualViewport.height = 800;
out.steps = steps;
// 3b. the same iframe with a mouse and a physical keyboard (the desktop FAB): focus is NOT a keyboard
pointer.coarse = false; cls.clear(); inputEl.value = ''; inputEl.style.height = ''; _reset();
const fine = [];
const stepF = (label) => fine.push([label, inputEl.style.height, cls.has('keyboard-open')]);
win.innerWidth = 420; win.visualViewport.height = 800; doc.activeElement = null; api.updateViewport(); stepF('idle');
doc.activeElement = inputEl; api.updateViewport(); stepF('focused');
doc.activeElement = null; api.updateViewport(); stepF('blurred');
win.visualViewport.height = 480; api.updateViewport(); stepF('short viewport'); win.visualViewport.height = 800;
out.fineSteps = fine; pointer.coarse = true;
out.truth = [[1,0,0,0],[1,0,1,0],[1,0,1,1],[1,1,0,0],[1,1,1,0],[0,0,1,1],[0,1,1,1]].map(a => [a.join(''), api.keyboardOpenState(...a.map(Boolean))]);
// 4. a slash command clears the inline height: the CSS value it falls back to is the same as the JS one
cls.clear(); win.innerWidth = 420; inputEl.style.height = ''; inputEl.value = '';
out.afterSlashReset = { cssFallback: win.getComputedStyle().minHeight, js: (api.autoResizeInput(), inputEl.style.height) };
console.log(JSON.stringify(out));
"""


def rule(selector, css=CSS, after=None):
    """Body of the first rule `selector{...}` at/after an anchor string (whitespace-insensitive)."""
    start = css.index(after) if after else 0
    # anchored at a line start so `textarea{` is not found inside `select,button,textarea{font:inherit}`
    m = re.compile(r"(?m)^[ \t]*" + re.escape(selector) + r"\s*\{([^}]*)\}").search(css, start)
    assert m, selector
    return m.group(1)


def prop(body, name):
    m = re.search(r"(?:^|[;\s])" + re.escape(name) + r"\s*:\s*([^;!]+)", body)
    return m.group(1).strip() if m else None


def css_values():
    """(min-height, max-height) of #input per state, straight from chat.css (cascade applied by hand)."""
    phone_at = "@media (max-width: 640px) {"
    fine_at = "@media (max-width: 640px) and (pointer: fine) {"
    wide = rule("textarea")
    phone = rule("#input", after=phone_at)
    fine = rule("#input", after=fine_at)
    kb = rule("body.keyboard-open #input")
    mm = lambda body, name, fallback: prop(body, name) or fallback
    return {
        "wide": {"minHeight": prop(wide, "min-height"), "maxHeight": prop(wide, "max-height")},
        "phone": {"minHeight": prop(phone, "min-height"), "maxHeight": prop(phone, "max-height")},
        # the mouse block only sets min-height/height; max-height still comes from the phone block
        "narrowMouse": {"minHeight": prop(fine, "min-height"), "maxHeight": mm(fine, "max-height", prop(phone, "max-height"))},
        "keyboard": {"minHeight": prop(kb, "min-height"), "maxHeight": prop(kb, "max-height")},
    }


def run_harness(path=APP):
    r = subprocess.run(["node", "-e", HARNESS, json.dumps(css_values()), str(path)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class InputFollowsTheStylesheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, json.dumps(css_values()), str(APP)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_desktop_sizes_come_from_the_stylesheet(self):
        w = self.o["wide"]
        self.assertEqual(w["empty"], ["42px", "hidden"])
        self.assertEqual(w["oneLine"], ["42px", "hidden"])       # within the 4px slack: no growth
        self.assertEqual(w["grows"], ["90px", "hidden"])
        self.assertEqual(w["capped"], ["120px", "auto"])

    def test_phone_sizes_are_36_and_80_not_the_old_38_and_90(self):
        p = self.o["phone"]
        self.assertEqual(p["empty"], ["36px", "hidden"])
        self.assertEqual(p["oneLine"], ["36px", "hidden"])
        self.assertEqual(p["grows"], ["60px", "hidden"])
        self.assertEqual(p["capped"], ["80px", "auto"])

    def test_with_the_keyboard_up_the_input_is_32_like_its_buttons_not_38(self):
        k = self.o["keyboard"]
        self.assertEqual(k["empty"], ["32px", "hidden"])
        self.assertEqual(k["oneLine"], ["32px", "hidden"])
        self.assertEqual(k["capped"], ["64px", "auto"])

    def test_unreadable_css_values_fall_back_instead_of_breaking(self):
        self.assertEqual(self.o["fallback"], {"empty": ["42px", "hidden"], "capped": ["120px", "auto"]})

    def test_the_height_is_re_measured_whenever_the_state_flips(self):
        steps = {label: (h, kb) for label, h, kb in self.o["steps"]}
        self.assertEqual(steps["wide, idle"], ("42px", False))
        self.assertEqual(steps["wide, focused"], ("42px", False))          # a wide window never counts focus as a keyboard
        self.assertEqual(steps["420px (FAB), idle"], ("36px", False))
        self.assertEqual(steps["420px (FAB), focused"], ("32px", True))    # ...but a narrow one (the FAB iframe) does
        self.assertEqual(steps["420px (FAB), blurred"], ("36px", False))
        self.assertEqual(steps["420px, short viewport"], ("32px", True))
        self.assertTrue(self.o["noRemeasureWhenNothingChanged"])

    def test_a_desktop_fab_does_not_treat_focus_as_a_keyboard(self):
        steps = {label: (h, kb) for label, h, kb in self.o["fineSteps"]}
        self.assertEqual(steps["idle"], ("42px", False))       # same as the full-page desktop, not the phone's 36
        self.assertEqual(steps["focused"], ("42px", False))    # no shrink, no hidden header/tabs/model button on click
        self.assertEqual(steps["blurred"], ("42px", False))
        self.assertEqual(steps["short viewport"], ("32px", True))   # a genuinely short window still is

    def test_keyboard_open_truth_table(self):
        # narrow, short, focused, touch
        table = {k: v for k, v in self.o["truth"]}
        self.assertFalse(table["1000"])   # narrow, nothing else
        self.assertFalse(table["1010"])   # narrow + focused, mouse   -> the desktop FAB
        self.assertTrue(table["1011"])    # narrow + focused, touch   -> a phone
        self.assertTrue(table["1100"])    # narrow + short, any pointer
        self.assertTrue(table["1110"])
        self.assertFalse(table["0011"])   # a wide window is never "keyboard up" just for focus
        self.assertFalse(table["0111"])   # ...nor for being short: the phone rules are for narrow screens

    def test_a_slash_command_no_longer_changes_the_input_height(self):
        self.assertEqual(self.o["afterSlashReset"], {"cssFallback": "36px", "js": "36px"})


class DecidedSizesStayAsDocumented(unittest.TestCase):
    """The intentional differences (42 desktop; 44 touch buttons beside a shorter input on phones; 32 when
    the keyboard is up) are stated in CSS comments; pin them so they only change on purpose."""

    def test_desktop_buttons_and_input_are_all_42(self):
        self.assertEqual(prop(rule(".composer button"), "height"), "42px")
        self.assertEqual(prop(rule("textarea"), "height"), "42px")
        self.assertEqual(prop(rule("textarea"), "min-height"), "42px")

    def test_phone_buttons_are_44_and_the_input_36(self):
        phone = CSS.index("@media (max-width: 640px)")
        for sel in ("#slashBtn", "#modelBtn", "#send"):
            self.assertEqual(prop(rule(sel, after="@media (max-width: 640px)"), "height"), "44px", sel)
        inp = rule("#input", after="@media (max-width: 640px)")
        self.assertEqual((prop(inp, "min-height"), prop(inp, "height"), prop(inp, "max-height")), ("36px", "36px", "80px"))
        self.assertGreater(phone, 0)

    def test_a_narrow_window_with_a_mouse_gets_the_desktop_42_everywhere(self):
        # the desktop hub FAB: an iframe 420px wide, no touch -> buttons and input all 42, like the full page
        at = "@media (max-width: 640px) and (pointer: fine) {"
        for sel in ("#slashBtn, #modelBtn", "#send"):
            self.assertEqual(prop(rule(sel, after=at), "height"), "42px", sel)
        icon = rule("#slashBtn, #modelBtn", after=at)
        self.assertEqual((prop(icon, "width"), prop(icon, "min-width")), ("42px", "42px"))
        inp = rule("#input", after=at)
        self.assertEqual((prop(inp, "min-height"), prop(inp, "height")), ("42px", "42px"))

    def test_the_mouse_block_sits_before_the_keyboard_and_short_screen_blocks_so_they_still_win(self):
        fine = CSS.index("@media (max-width: 640px) and (pointer: fine) {")
        self.assertLess(fine, CSS.index("@media (max-height: 500px)"))
        self.assertLess(fine, CSS.index("body.keyboard-open #input"))
        self.assertLess(CSS.index("@media (max-width: 640px) {"), fine)   # ...and after the phone block it overrides

    def test_with_the_keyboard_up_every_widget_in_the_row_is_32(self):
        for sel in ("body.keyboard-open #slashBtn", "body.keyboard-open #send", "body.keyboard-open #input"):
            self.assertEqual(prop(rule(sel), "height"), "32px", sel)
        self.assertEqual(prop(rule("body.keyboard-open #input"), "min-height"), "32px")

    def test_the_short_screen_block_uses_the_same_32(self):
        block = CSS[CSS.index("@media (max-height: 500px)"):]
        for sel in ("#slashBtn", "#send", "#input"):
            self.assertEqual(prop(rule(sel, css=block), "height"), "32px", sel)


if __name__ == "__main__":
    unittest.main()
