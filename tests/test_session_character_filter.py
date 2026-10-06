"""The sessions pane can be browsed per character (SESSION_CHAR_TABS_v1, 2026-09-28).

/api/sessions already returned `character` and `character_name` on every row, and every row already
printed the name, so this groups what the list was showing instead of adding a backend. The group
labels and the row labels go through one resolver, so a tab and its rows cannot disagree.

Runs the REAL sessionCharacterLabel / sessionCharacterGroups / renderSessionCharTabs /
renderSessionsList (sliced out of the concatenated page bundle) in node against a stub DOM.
Skipped when node is not installed.

Run: python3 -m unittest tests.test_session_character_filter  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import app_bundle  # noqa: E402
from tests.page_source import i18n_prelude  # noqa: E402

CODE = Path(__file__).resolve().parent.parent
APP = app_bundle()   # static/app.js and its app-*.js parts (APP_SPLIT_v1), in index.html order

HARNESS = r"""
const fs = require('fs');
// argv: [node, bundle-path, case] -- `node -e` has no script path of its own
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('var SESSION_CHAR_TABS_KEY'), b = src.indexOf('async function deleteSession');
if (a < 0 || b < 0) throw new Error('markers missing');
const code = src.slice(a, b);

// A DOM stub with just what renderSessionCharTabs / renderSessionsList touch.
function el(tag) {
  const e = {
    tag, className: '', textContent: '', children: [], attrs: {}, handlers: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(t, f) { this.handlers[t] = f; },
    appendChild(c) { this.children.push(c); return c; },
    all(sel) {                       // only [data-*] selectors are used by the code under test
      const attr = sel.match(/^\[([\w-]+)\]$/);
      const out = [];
      (function walk(n) {
        for (const c of n.children) {
          if (attr ? Object.prototype.hasOwnProperty.call(c.attrs, attr[1]) : true) out.push(c);
          walk(c);
        }
      })(this);
      return out;
    },
    querySelectorAll(sel) { return this.all(sel); },
  };
  // A real element drops its children when innerHTML is set to the empty string; the code under
  // test relies on that to clear the list before re-rendering.
  let html = '';
  Object.defineProperty(e, 'innerHTML', {
    get() { return html; },
    set(v) { html = v; if (v === '') e.children = []; },
  });
  return e;
}

const tabsEl = el('div');
const listEl = el('div');
const document = { createElement: el, getElementById: (id) => (id === 'sessionCharTabs' ? tabsEl : null) };
const store = {};
const localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};
let characterCatalog = [];
const sessionsListEl = listEl;
let sessionId = 'live-1';
const escapeHtml = (s) => String(s == null ? '' : s);
const _scrollbackEpochMs = (t) => t;
const getActionSvg = () => '<svg/>';
const openSession = () => {};
const switchTab = () => {};

eval(code);

const CATALOG = [{ id: 'char_nono', name: '노노' }, { id: 'char_riri', name: '리리' }, { id: 'char_koko', name: '코코' }];
const S = (id, over) => Object.assign({ id, character: 'char_nono', character_name: 'ignored', mode: 'work',
  model: 'm', turns: 1, updated_at: '2026-09-28T00:00:00', preview: 'p' + id }, over || {});

function render(catalog, list, live) {
  characterCatalog = catalog;
  sessionId = live;
  tabsEl.children = []; listEl.children = []; tabsEl.className = 'session-char-tabs';
  renderSessionsList(list);
}
const tabs = () => tabsEl.children.map((b) => b.textContent);
const rows = () => listEl.children.map((r) => {
  const m = String(r.innerHTML).match(/session-row-id">([^<]*)/);
  return m ? m[1] : '';
});

const CASES = {
  catalog_order: () => {
    render(CATALOG, [S('a', { character: 'char_koko' }), S('b'), S('c'), S('d', { character: 'char_riri' })], 'live-1');
    return { tabs: tabs(), strip: tabsEl.className, rows: rows().length };
  },
  label_agrees: () => {
    render(CATALOG, [S('a', { character: 'char_riri' }), S('b', { character: 'char_koko' })], 'live-1');
    return { tab: tabs()[1], row: rows()[0] };
  },
  filters_and_remember: () => {
    const list = [S('a'), S('b'), S('c', { character: 'char_koko' })];
    render(CATALOG, list, 'live-1');
    const before = rows().length;
    tabsEl.children[1].handlers.click();
    return { before, after: rows().length, stored: store['pe_session_char_tabs'] };
  },
  one_character_no_strip: () => {
    render(CATALOG, [S('a'), S('b')], 'live-1');
    return { tabs: tabs(), strip: tabsEl.className };
  },
  counts_skip_hidden: () => {
    render(CATALOG, [S('a'), S('b', { preview: '' }), S('c', { character: 'char_koko' })], 'live-1');
    return { tabs: tabs() };
  },
  falls_back_when_gone: () => {
    // 노노 · 리리 · 코코, so the strip stays up throughout and only 코코 loses its sessions.
    render(CATALOG, [S('a'), S('c', { character: 'char_koko' }), S('d', { character: 'char_riri' })], 'live-1');
    tabsEl.children[3].handlers.click();      // filter to 코코, the one we are about to delete
    const filtered = rows().length;
    render(CATALOG, [S('a'), S('d', { character: 'char_riri' })], 'live-1');
    return { filtered, after: rows().length, stored: store['pe_session_char_tabs'], tabs: tabs() };
  },
  no_character_is_default: () => {
    render(CATALOG, [S('a', { character: '', character_name: '' }), S('b', { character: 'char_koko' })], 'live-1');
    return { tabs: tabs() };
  },
  server_name_fallback: () => {
    render([], [S('a', { character: 'char_x', character_name: '엑스' })], 'live-1');
    return { strip: tabsEl.className, label: sessionCharacterLabel({ character: 'char_x', character_name: '엑스' }) };
  },
};

console.log(JSON.stringify(CASES[process.argv[2]]()));
"""


def run(case):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not installed")
    proc = subprocess.run([node, "-e", i18n_prelude() + HARNESS, str(APP), case], capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        raise AssertionError("node failed for %s: %s" % (case, proc.stderr.strip()[:600]))
    return json.loads(proc.stdout.strip().splitlines()[-1])


class SessionCharacterFilter(unittest.TestCase):
    def test_the_strip_sits_above_the_list(self):
        html = (CODE / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="sessionCharTabs"', html)
        self.assertLess(html.find('id="sessionCharTabs"'), html.find('id="sessionsList"'))

    def test_one_tab_per_character_plus_all_in_catalog_order(self):
        out = run("catalog_order")
        self.assertEqual(out["tabs"], ["전체 (4)", "노노 (2)", "리리 (1)", "코코 (1)"])
        self.assertEqual(out["strip"], "session-char-tabs on")
        self.assertEqual(out["rows"], 4)

    def test_a_tab_label_and_its_row_label_agree(self):
        out = run("label_agrees")
        # The row reads "<name> · <id>" and the tab "<name> (<count>)": the name must come from the
        # same resolver, so strip the decorations and compare the part that identifies the character.
        self.assertEqual(out["row"], "리리 · a")
        self.assertEqual(out["tab"].split(" (")[0], out["row"].split(" · ")[0])

    def test_picking_a_character_filters_the_list_and_is_remembered(self):
        out = run("filters_and_remember")
        self.assertEqual((out["before"], out["after"]), (3, 2))
        self.assertEqual(out["stored"], "char_nono")

    def test_a_single_character_gets_no_strip(self):
        out = run("one_character_no_strip")
        self.assertEqual(out["tabs"], [])
        self.assertEqual(out["strip"], "session-char-tabs")

    def test_hidden_empty_sessions_do_not_inflate_the_counts(self):
        out = run("counts_skip_hidden")
        self.assertEqual(out["tabs"], ["전체 (2)", "노노 (1)", "코코 (1)"])

    def test_deleting_the_last_session_of_a_character_falls_back_to_all(self):
        out = run("falls_back_when_gone")
        self.assertEqual(out["filtered"], 1)
        self.assertEqual(out["after"], 2, "the list went blank instead of falling back to 전체")
        self.assertEqual(out["stored"], "")
        self.assertEqual(out["tabs"][0], "전체 (2)")

    def test_a_session_with_no_character_is_labelled_default(self):
        out = run("no_character_is_default")
        # Catalog order first, then a character the catalog does not know (here: no character at
        # all, i.e. the team default) sorted by name -- so the strip never reshuffles on counts.
        self.assertEqual(out["tabs"], ["전체 (2)", "코코 (1)", "기본 (1)"])

    def test_a_character_missing_from_the_catalog_uses_the_servers_name(self):
        out = run("server_name_fallback")
        self.assertEqual(out["label"], "엑스")
        self.assertEqual(out["strip"], "session-char-tabs", "one character should not raise the strip")


if __name__ == "__main__":
    unittest.main()
