"""character-settings cs/C: the profile drawer draws a tab's settings from the server's list and sends back only the
keys that changed (PATCH); a sensitive one stays folded; brains and the face crop keep their own editors.
Run: engine/run-tests.sh test_settings_page
"""
import json
import shutil
import subprocess
import unittest

from tests._paths import REPO  # noqa: E402
from tests.page_source import i18n_prelude  # noqa: E402

STATIC = REPO / "static"

JS = r"""
const fs = require('fs');
eval(fs.readFileSync(process.argv[1], 'utf8'));
function el(tag) { const n = { tag, kids: [], hidden: false, isConnected: true, dataset: {}, listeners: {}, value: '', checked: false,
  append(...k) { k.forEach(x => { x.parentNode = n; this.kids.push(x); }); }, appendChild(k) { this.append(k); return k; },
  addEventListener(t, f) { this.listeners[t] = f; }, remove() {}, setAttribute(k, v) { this[k] = v; }, set textContent(v) { if (v === '') this.kids = []; this.text = v; },
  get textContent() { return this.text || ''; } }; return n; }
global.document = { createElement: el, createTextNode: t => ({ text: t }) };
function shellEl(tag, cls, text) { const n = el(tag); n.cls = cls; if (text != null) n.text = text; return n; }
function shellSection(title) { const b = shellEl('div', 'shell-section'); b.appendChild(shellEl('div', 't', title)); return b; }
const fields = [
  { key: 'card.name', tab: 'character', type: 'text', label: { key: 'charset.card.name' }, editable: true, value: 'Kit' },
  { key: 'card.tags', tab: 'character', type: 'list', label: { key: 'charset.card.tags' }, editable: true, value: ['a'] },
  { key: 'display.focal', tab: 'character', type: 'focal', label: { key: 'charset.display.focal' }, editable: true, value: null },
  { key: 'file.private_memory', tab: 'relationship', type: 'longtext', label: { key: 'charset.file.private_memory' }, editable: true, sensitive: true, value: 'secret' },
  { key: 'brain.work', tab: 'settings', type: 'brain', label: { key: 'charset.brain.work' }, editable: true, value: null } ];
const calls = [];
async function api(url, opts) {
  calls.push([url, opts && opts.method, opts && opts.body]);
  if (url.includes('/versions/')) return { versions: [{ version: '20261009220512', bytes: 9 }] };
  if (url.endsWith('/restore')) return { ok: true };
  return opts ? { changed: Object.keys(JSON.parse(opts.body)), errors: {} } : { fields };
}
const flat = n => [n].concat(...(n.kids || []).map(flat));
(async () => {
  const out = {};
  const sec = shellSettingsSection({ id: 'c1' }, 'character', 'Card');
  await new Promise(r => setTimeout(r, 5));
  out.charRows = flat(sec).filter(n => n.cls === 'shell-info-label').map(n => n.text);
  const rel = shellSettingsSection({ id: 'c1' }, 'relationship', 'Mem');
  await new Promise(r => setTimeout(r, 5));
  out.folded = flat(rel).filter(n => n.cls === 'shell-info-val').map(n => n.hidden);
  // cs/D: a row's versions; the first tap arms, the second restores
  const hist = flat(sec).find(n => n.cls === 'shell-icon-btn shell-settings-history');
  out.sameTools = flat(rel).filter(n => /^shell-icon-btn/.test(n.cls || '')).map(n => n.cls.split(' ')[0]);
  await hist.listeners.click();
  await new Promise(r => setTimeout(r, 5));
  const ver = flat(sec).filter(n => n.tag === 'button' && /10-09 22:05:12/.test(n.text || ''))[0];
  out.versionLabel = ver.text;
  await ver.listeners.click();
  out.armed = ver.text;
  await ver.listeners.click();
  out.restore = calls.filter(c => c[1] === 'POST').map(c => [c[0], JSON.parse(c[2])]);
  await new Promise(r => setTimeout(r, 5));
  // edit: change the name only, keep the tags
  const toggle = flat(sec).find(n => n.tag === 'button');
  toggle.listeners.click();
  await new Promise(r => setTimeout(r, 5));
  const inputs = flat(sec).filter(n => n.tag === 'input' || n.tag === 'textarea');
  inputs[0].value = 'Kat';
  const save = flat(sec).filter(n => n.tag === 'button').pop();
  await save.listeners.click();
  out.patch = calls.filter(c => c[1] === 'PATCH').map(c => [c[0], JSON.parse(c[2])]);
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SettingsPage(unittest.TestCase):
    def test_a_tab_draws_its_settings_and_saves_only_what_changed(self):
        p = subprocess.run(["node", "-e", i18n_prelude() + JS, str(STATIC / "app-shell-settings.js")],
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(out["charRows"], ["이름", "태그"], "the face crop keeps its own editor")
        self.assertEqual(out["folded"], [True], "a sensitive value is folded")
        self.assertEqual(out["patch"], [["/api/characters/c1/settings", {"card.name": "Kat"}]])

    def test_a_version_is_restored_on_the_second_tap(self):
        p = subprocess.run(["node", "-e", i18n_prelude() + JS, str(STATIC / "app-shell-settings.js")],
                           capture_output=True, text=True, timeout=20)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(out["versionLabel"], "10-09 22:05:12")
        self.assertEqual(out["armed"], "10-09 22:05:12 되돌리기?")
        self.assertEqual(out["sameTools"], ["shell-icon-btn", "shell-icon-btn"], "show and versions: one size, no art-btn")
        self.assertEqual(out["restore"], [["/api/characters/c1/settings/restore",
                                           {"key": "card.name", "version": "20261009220512"}]])


if __name__ == "__main__":
    unittest.main()
