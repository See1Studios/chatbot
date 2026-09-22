"""The model is chosen with a short icon button + menu, and the composer placeholder always names
the model in use. (실장님: 모바일에서 모델 select가 폭을 차지해서 -- 짧은 버튼, 탭과 같은 아이콘, 현재
모델은 placeholder로.)
Runs the REAL code of static/model-picker.js in node against a stub DOM, plus static checks that the
markup/CSS keep the hidden <select id="model"> (the source of truth app.js reads) and the icon
button. Skipped when node is not installed.
Run: python3 -m unittest tests.test_model_picker  (from services/chatbot)
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
JS = STATIC / "model-picker.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function modelLabel'), b = src.lastIndexOf('\nsetupModelPicker();');
if (a < 0 || b < 0) throw new Error('markers missing');
const code = src.slice(a, b);
global.Event = global.Event || class { constructor(t) { this.type = t; } };

let focused = null;
function node(cls) {
  const n = { className: cls || '', children: [], parent: null, attrs: {}, handlers: {}, style: {}, hidden: false,
    textContent: '', title: '', tabIndex: -1,
    classList: {
      contains: c => n.className.split(/\s+/).includes(c),
      add: c => { if (!n.classList.contains(c)) n.className = (n.className + ' ' + c).trim(); },
      remove: c => { n.className = n.className.split(/\s+/).filter(x => x && x !== c).join(' '); },
    },
    setAttribute(k, v) { n.attrs[k] = v; },
    addEventListener(t, f) { (n.handlers[t] = n.handlers[t] || []).push(f); },
    appendChild(c) { c.parent = n; n.children.push(c); return c; },
    get nextSibling() { const s = n.parent ? n.parent.children : []; return s[s.indexOf(n) + 1] || null; },
    get previousSibling() { const s = n.parent ? n.parent.children : []; return s[s.indexOf(n) - 1] || null; },
    contains(o) { for (let x = o; x; x = x.parent) if (x === n) return true; return false; },
    querySelector(sel) { const c = sel.replace('.', ''); return n.children.find(x => x.classList.contains(c)) || null; },
    focus() { focused = n; },
  };
  Object.defineProperty(n, 'innerHTML', { get() { return ''; }, set(v) { n.children = []; } });
  return n;
}
const fire = (n, type, ev) => (n.handlers[type] || []).forEach(f => f(Object.assign({ preventDefault() {}, stopPropagation() {}, target: n }, ev || {})));

const modelBtnEl = node('model-trigger-btn'), modelMenuEl = node('slash-menu'); modelMenuEl.hidden = true;
const inputEl = node(); inputEl.placeholder = 'STATIC';
const saved = []; const calls = { hideSlash: 0, position: [], refresh: 0 };
const modelEl = { options: [{ value: 'flash-low', textContent: 'flash-low' }, { value: 'pro-high', textContent: 'pro-high' }, { value: 'opus', textContent: 'opus' }],
  value: 'flash-low', onchange: null,
  dispatchEvent(ev) { if (ev.type === 'change' && modelEl.onchange) modelEl.onchange(); } };
const docHandlers = {};
const document = { createElement: () => node(), addEventListener: (t, f) => { (docHandlers[t] = docHandlers[t] || []).push(f); } };
const win = { addEventListener() {} };
const fireDoc = (type, ev) => (docHandlers[type] || []).forEach(f => f(Object.assign({ preventDefault() {}, stopPropagation() {}, target: document }, ev || {})));

globalThis.__saved = saved; globalThis.__calls = calls;
const stubs = { modelBtnEl, modelMenuEl, inputEl, modelEl, document, window: win,
  hideSlashMenu: () => { calls.hideSlash++; }, positionSlashMenu: m => { calls.position.push(m === modelMenuEl); m.style.position = 'fixed'; m.style.bottom = '58px'; m.style.zIndex = '200'; } };   // like the real one: inline placement
const names = Object.keys(stubs);
// app.js's refreshComposerPlaceholder() and the select's onchange, stood in for right next to the real code
const api = new Function(...names, code + `
  function refreshComposerPlaceholder() { __calls.refresh++; inputEl.placeholder = composerPlaceholder(modelEl.value, { compact: false }); }
  modelEl.onchange = () => { __saved.push(modelEl.value); syncModelUi(); };
  setupModelPicker();
  return { composerPlaceholder, renderModelMenu, syncModelUi, modelLabel };`)(...names.map(k => stubs[k]));

const out = {};
// 1. the text (pure)
out.textIdleDesktop = api.composerPlaceholder('gemini-3.8-flash-low', {});
out.textIdlePhone = api.composerPlaceholder('gemini-3.8-flash-low', { compact: true });
out.textBusyDesktop = api.composerPlaceholder('m', { busySec: 7 });
out.textBusyPhone = api.composerPlaceholder('m', { busySec: 7, compact: true });
out.textNoModel = api.composerPlaceholder('', {});
out.modelFirst = ['gemini-3.8-flash-low'].every(m => [{}, { compact: true }, { busySec: 3 }, { busySec: 3, compact: true }].every(o => api.composerPlaceholder(m, o).startsWith(m)));

// 2. after setup the button already names the model
out.titleAtStart = modelBtnEl.title; out.ariaAtStart = modelBtnEl.attrs['aria-label']; out.menuHiddenAtStart = modelMenuEl.hidden;

// 3. open with a pointer
fire(modelBtnEl, 'pointerdown');
out.opened = { hidden: modelMenuEl.hidden, active: modelBtnEl.classList.contains('active'), expanded: modelBtnEl.attrs['aria-expanded'],
  hideSlash: calls.hideSlash, placed: calls.position.slice(), placedStyle: modelMenuEl.style.position,
  items: modelMenuEl.children.map(c => ({ name: c.children[0].textContent, mark: c.children[1].textContent, sel: c.classList.contains('selected'), aria: c.attrs['aria-selected'] })) };
// 4. pick another model
modelMenuEl.children[1].handlers.click[0]();
out.picked = { value: modelEl.value, saved: globalThis.__saved.slice(), hidden: modelMenuEl.hidden, active: modelBtnEl.classList.contains('active'),
  placeholder: inputEl.placeholder, title: modelBtnEl.title, inlineStyleCleared: Object.values(modelMenuEl.style).every(v => v === '') };
// 5. picking the model already in use changes nothing but closes
fire(modelBtnEl, 'pointerdown');
const savedBefore = globalThis.__saved.length;
modelMenuEl.children[1].handlers.click[0]();
out.sameModel = { saved: globalThis.__saved.length - savedBefore, hidden: modelMenuEl.hidden };
// 6. toggle closed by the button, outside click closes, inside click does not
fire(modelBtnEl, 'pointerdown'); fire(modelBtnEl, 'pointerdown');
out.toggledClosed = modelMenuEl.hidden;
fire(modelBtnEl, 'pointerdown');
fireDoc('pointerdown', { target: modelMenuEl.children[0] });
out.insideClickKeepsOpen = !modelMenuEl.hidden;
fireDoc('pointerdown', { target: node() });
out.outsideClickCloses = modelMenuEl.hidden;
// 7. Escape closes and returns focus to the button
fire(modelBtnEl, 'pointerdown'); fireDoc('keydown', { key: 'Escape' });
out.escape = { hidden: modelMenuEl.hidden, focusOnButton: focused === modelBtnEl };
// 8. keyboard: Enter/Space is a click with detail 0 (opens + focuses the current item); a pointer click (detail 1) must not toggle again
focused = null; fire(modelBtnEl, 'click', { detail: 0 });
out.keyboardOpen = { hidden: modelMenuEl.hidden, focusedCurrent: focused && focused.classList.contains('selected') };
fire(modelBtnEl, 'click', { detail: 1 });
out.pointerClickIgnored = !modelMenuEl.hidden;
// 9. arrow keys move focus, Enter picks
const first = modelMenuEl.children[0];
fire(first, 'keydown', { key: 'ArrowDown' });
out.arrowDown = focused === modelMenuEl.children[1];
fire(modelMenuEl.children[1], 'keydown', { key: 'ArrowUp' });
out.arrowUp = focused === modelMenuEl.children[0];
fire(modelMenuEl.children[2], 'keydown', { key: 'Enter' });
out.enterPicks = { value: modelEl.value, hidden: modelMenuEl.hidden };
// 10. typing in the input closes the menu
fire(modelBtnEl, 'pointerdown'); fire(inputEl, 'input');
out.typingCloses = modelMenuEl.hidden;
// 11. before boot filled the list the static placeholder is left alone
modelEl.options = []; modelEl.value = ''; inputEl.placeholder = 'STATIC'; const r0 = calls.refresh;
api.syncModelUi();
out.emptyListLeavesPlaceholder = { placeholder: inputEl.placeholder, refreshed: calls.refresh - r0 };
console.log(JSON.stringify(out));
"""

INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "chat.css").read_text(encoding="utf-8")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ModelPickerBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(JS)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_placeholder_always_leads_with_the_model_in_every_state(self):
        self.assertTrue(self.o["modelFirst"])
        self.assertEqual(self.o["textIdleDesktop"], "gemini-3.8-flash-low · 메시지를 입력… (/ 명령어·스킬, /btw <질문>)")
        self.assertEqual(self.o["textIdlePhone"], "gemini-3.8-flash-low · 메시지 입력… (/ 또는 /btw)")
        self.assertTrue(self.o["textBusyDesktop"].startswith("m · 작업 진행 중 (7초)"))
        self.assertTrue(self.o["textBusyPhone"].startswith("m · 작업 중 (7초)"))
        self.assertTrue(self.o["textNoModel"].startswith("기본 모델 · "))

    def test_the_button_names_the_model_from_the_start(self):
        self.assertEqual(self.o["titleAtStart"], "모델 선택 (현재: flash-low)")
        self.assertEqual(self.o["ariaAtStart"], "모델 선택 (현재: flash-low)")
        self.assertTrue(self.o["menuHiddenAtStart"])

    def test_the_menu_lists_every_model_and_marks_the_current_one(self):
        o = self.o["opened"]
        self.assertFalse(o["hidden"])
        self.assertTrue(o["active"])
        self.assertEqual(o["expanded"], "true")
        self.assertEqual(o["hideSlash"], 1)            # the slash menu is closed first
        self.assertEqual(o["placed"], [True])          # placed with the shared positioning
        self.assertEqual(o["placedStyle"], "fixed")    # ...which leaves inline styles behind
        self.assertEqual([i["name"] for i in o["items"]], ["flash-low", "pro-high", "opus"])
        self.assertEqual([i["sel"] for i in o["items"]], [True, False, False])
        self.assertEqual([i["mark"] for i in o["items"]], ["✓ 사용 중", "", ""])
        self.assertEqual([i["aria"] for i in o["items"]], ["true", "false", "false"])

    def test_picking_a_model_sets_the_hidden_select_persists_and_updates_the_ui(self):
        p = self.o["picked"]
        self.assertEqual(p["value"], "pro-high")
        self.assertEqual(p["saved"], ["pro-high"])     # the select's change handler ran (app.js persists there)
        self.assertTrue(p["hidden"])
        self.assertFalse(p["active"])
        self.assertTrue(p["placeholder"].startswith("pro-high · "))
        self.assertEqual(p["title"], "모델 선택 (현재: pro-high)")
        self.assertTrue(p["inlineStyleCleared"])

    def test_picking_the_model_already_in_use_only_closes_the_menu(self):
        self.assertEqual(self.o["sameModel"], {"saved": 0, "hidden": True})

    def test_open_and_close_gestures(self):
        self.assertTrue(self.o["toggledClosed"])
        self.assertTrue(self.o["insideClickKeepsOpen"])
        self.assertTrue(self.o["outsideClickCloses"])
        self.assertEqual(self.o["escape"], {"hidden": True, "focusOnButton": True})
        self.assertTrue(self.o["typingCloses"])

    def test_keyboard_users_can_open_move_and_pick(self):
        self.assertEqual(self.o["keyboardOpen"], {"hidden": False, "focusedCurrent": True})
        self.assertTrue(self.o["pointerClickIgnored"])   # the click that follows a pointerdown must not toggle it back
        self.assertTrue(self.o["arrowDown"])
        self.assertTrue(self.o["arrowUp"])
        self.assertEqual(self.o["enterPicks"], {"value": "opus", "hidden": True})

    def test_before_the_model_list_exists_the_static_placeholder_is_kept(self):
        self.assertEqual(self.o["emptyListLeavesPlaceholder"], {"placeholder": "STATIC", "refreshed": 0})


class ModelPickerMarkupAndCss(unittest.TestCase):
    def test_the_hidden_select_stays_as_the_source_of_truth_next_to_the_new_button(self):
        self.assertIn('<select id="model"', INDEX)
        self.assertIn('id="modelBtn"', INDEX)
        self.assertIn('id="modelMenu"', INDEX)
        self.assertRegex(CSS, r"#model\{\s*display:none !important;")

    def test_the_button_uses_the_same_icon_style_as_the_tabs(self):
        btn = re.search(r'<button id="modelBtn".*?</button>', INDEX, re.S).group(0)
        self.assertIn('class="tab-icon-svg"', btn)
        self.assertIn('viewBox="0 0 24 24"', btn)
        self.assertIn('aria-haspopup="listbox"', btn)
        self.assertIn('aria-label="모델 선택"', btn)

    def test_the_phone_layout_gives_it_the_slash_buttons_44px_and_frees_the_old_58px_select(self):
        m = re.search(r"#modelBtn\{\s*order:2;\s*width:44px;\s*min-width:44px;\s*height:44px;", CSS)
        self.assertIsNotNone(m)
        self.assertNotIn("max-width:58px", CSS)

    def test_it_is_hidden_where_the_select_used_to_be_hidden_for_input_room(self):
        self.assertIn("body.keyboard-open #modelBtn", CSS)
        self.assertRegex(CSS, r"#modelBtn, #provider\{\s*display:none !important;")

    def test_the_script_is_loaded_after_slash_js_which_it_borrows_placement_from(self):
        self.assertLess(INDEX.index("./slash.js"), INDEX.index("./model-picker.js"))


if __name__ == "__main__":
    unittest.main()
