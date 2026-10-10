"""Solid accent labels stay readable, and dialogs keep the keyboard (impeccable harden).

The active card tab used white on every dial, which disappears on Paper White.
Private mode used #c2185b, about 3.3:1 on the pit. The artifact dialog opened
behind the page focus; confirm did not return focus when it closed.

Run: engine/run-tests.sh test_a11y_harden
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests._paths import REPO  # noqa: E402
from tests.page_source import i18n_prelude  # noqa: E402

STATIC = REPO / "static"
PANELS = ("#14171d", "#0a0c0f", "#181c24", "#0c0c0e", "#10141c", "#050505")


def _lin(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg, bg):
    hi, lo = max(_lum(fg), _lum(bg)), min(_lum(fg), _lum(bg))
    return (hi + 0.05) / (lo + 0.05)


def _token(css, name):
    for line in css.splitlines():
        if line.strip().startswith(name + ":"):
            found = re.search(r"#[0-9a-fA-F]{3,8}", line)
            if found:
                return found.group(0).lower()
    raise AssertionError("%s missing" % name)


class AccentContrast(unittest.TestCase):
    def test_private_rose_clears_aa_on_every_panel(self):
        css = (STATIC / "chat-base.css").read_text(encoding="utf-8")
        rose = _token(css, "--accent-private")
        self.assertEqual(rose, "#ff7aa2")
        for bg in PANELS:
            self.assertGreaterEqual(contrast(rose, bg), 4.5, "%s on %s" % (rose, bg))
        for name in ("chat-composer.css", "chat-features.css", "shell.css"):
            text = (STATIC / name).read_text(encoding="utf-8")
            self.assertNotIn("#c2185b", text, name)

    def test_card_tab_uses_ink_on_the_accent_fill(self):
        css = (STATIC / "chat-panes.css").read_text(encoding="utf-8")
        rule = next(l for l in css.splitlines() if l.startswith(".card-tab-btn.active{"))
        self.assertIn("color:var(--accent-contrast)", rule)
        self.assertNotIn("color:#fff", rule)
        ink = _token((STATIC / "chat-base.css").read_text(encoding="utf-8"), "--accent-contrast")
        accents = {
            "lime": "#d1fe17", "amber": "#ff8a50", "cyan": "#38bdf8", "emerald": "#34d399",
            "violet": "#a78bfa", "spark": "#6ea8fe", "mono": "#ffffff",
        }
        for name, bg in accents.items():
            self.assertGreaterEqual(contrast(ink, bg), 4.5, "%s on %s" % (name, bg))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class DialogFocus(unittest.TestCase):
    def test_artifact_dialog_takes_and_traps_focus(self):
        js = r"""
const fs = require('fs'), vm = require('vm');
const keys = [];
let active = null;
const cache = {};
function make(id) {
  const el = {
    id: id, style: {}, disabled: false, hidden: false, children: [],
    classList: { add() {}, remove() {} },
    setAttribute() {}, getAttribute() { return null; },
    addEventListener() {}, removeEventListener() {},
    appendChild(c) { this.children.push(c); return c; },
    focus() { active = el; },
    contains(n) { return n === el || el.children.indexOf(n) >= 0; },
  };
  cache[id] = el;
  return el;
}
function el(id) { return cache[id] || make(id); }
const opener = make('opener');
active = opener;
const artModal = el('artModal');
const modalClose = el('modalClose');
const modalDownload = el('modalDownload');
const modalCite = el('modalCite');
artModal.querySelectorAll = () => [modalClose, modalDownload, modalCite];
artModal.contains = (n) => n === modalClose || n === modalDownload || n === modalCite;
const ctx = {
  console, setTimeout: (fn) => { if (typeof fn === 'function') fn(); return 0; },
  clearTimeout() {},
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Map, Set,
  encodeURIComponent, decodeURIComponent, parseInt,
  document: {
    getElementById: el,
    createElement: () => make('node'),
    querySelectorAll: () => [],
    addEventListener() {}, removeEventListener() {},
    contains: (n) => n === opener,
    get activeElement() { return active; },
  },
};
ctx.window = ctx;
ctx.window.addEventListener = (type, fn) => { if (type === 'keydown') keys.push(fn); };
vm.createContext(ctx);
vm.runInContext(__I18N, ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx, { filename: 'artifacts.js' });
(async () => {
  await ctx.openArtifactModal({ name: 'a.png', kind: 'image', url: '/a.png' });
  const opened = active === modalClose;
  const ev = { key: 'Tab', shiftKey: false, prevented: false, preventDefault() { this.prevented = true; } };
  active = modalCite;
  keys[0](ev);
  const wrapped = ev.prevented && active === modalClose;
  ctx.closeArtifactModal();
  console.log(JSON.stringify({ opened, wrapped, restored: active === opener, keys: keys.length }));
})();
"""
        r = subprocess.run(
            ["node", "-e", "const __I18N = %s;\n" % json.dumps(i18n_prelude()) + js,
             str(STATIC / "artifacts.js")],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(out["opened"], out)
        self.assertTrue(out["wrapped"], out)
        self.assertTrue(out["restored"], out)
        self.assertEqual(out["keys"], 1)

    def test_confirm_returns_focus(self):
        src = (STATIC / "app.js").read_text(encoding="utf-8")
        start, end = src.index("function confirmModal"), src.index("\nfunction alertModal")
        js = r"""
const fs = require('fs'), vm = require('vm');
let active = null;
const clicks = {};
function btn(id) {
  return {
    id, style: {}, className: '', textContent: '',
    focus() { active = this; },
    addEventListener(type, fn) { clicks[id + ':' + type] = fn; },
    removeEventListener() {},
  };
}
const opener = { id: 'opener', focus() { active = opener; } };
active = opener;
const ok = btn('ok'), cancel = btn('cancel');
const box = { id: 'box', style: {}, addEventListener() {}, removeEventListener() {} };
const ctx = {
  console, tr: (k) => k,
  document: {
    get activeElement() { return active; },
    contains: (n) => n === opener,
    addEventListener() {}, removeEventListener() {},
  },
  confirmModalEl: box, confirmModalMsgEl: { textContent: '' },
  confirmModalOkBtn: ok, confirmModalCancelBtn: cancel,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const pending = ctx.confirmModal('leave?');
const focusedOk = active === ok;
clicks['ok:click']();
pending.then((okd) => {
  console.log(JSON.stringify({ focusedOk, restored: active === opener, okd }));
});
"""
        fn = Path("/tmp/confirm-modal.js")
        fn.write_text(src[start:end], encoding="utf-8")
        try:
            r = subprocess.run(["node", "-e", js, str(fn)], capture_output=True, text=True, timeout=20)
        finally:
            fn.unlink(missing_ok=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(out["focusedOk"], out)
        self.assertTrue(out["restored"], out)
        self.assertTrue(out["okd"], out)
