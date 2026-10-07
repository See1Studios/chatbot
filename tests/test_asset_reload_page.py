"""ASSET_RELOAD_v1: a host restart that brought new page code reloads an open page, keeping its unsent draft. The
first fingerprint the page sees is its own; the same one after a restart changes nothing. The REAL functions of
static/app-api.js run in node.
Run: engine/run-tests.sh test_asset_reload_page
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"

HARNESS = r"""
const all = require('fs').readFileSync(process.argv[1], 'utf8');
const src = all.slice(all.indexOf('let pageAssetsFp'), all.indexOf('async function defibrillateHost'));
const store = {};
const sessionStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; },
  removeItem: k => { delete store[k]; } };
let reloads = 0;
const window = { location: { reload: () => { reloads++; } } };
const inputEl = { value: 'half a sentence' };
const out = new Function('sessionStorage', 'window', 'inputEl', src + `;
  const r = {};
  r.first = reloadIfAssetsChanged('aaa');          // the page's own
  r.same = reloadIfAssetsChanged('aaa');
  r.none = reloadIfAssetsChanged('');
  r.changed = reloadIfAssetsChanged('bbb');
  return r;`)(sessionStorage, window, inputEl);
out.reloads = reloads;
out.kept = store['chatbot.reloadDraft'];
// the reloaded page puts the draft back once
const page2 = { value: '' };
new Function('sessionStorage', 'window', 'inputEl', src + '; restoreReloadDraft();')(sessionStorage, window, page2);
out.restored = page2.value;
out.left = Object.keys(store);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class AssetReload(unittest.TestCase):
    def test_new_page_code_after_a_restart_reloads_and_keeps_the_draft(self):
        out = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-api.js")], capture_output=True, text=True,
                             timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        o = json.loads(out.stdout)
        self.assertEqual((o["first"], o["same"], o["none"], o["changed"]), (False, False, False, True))
        self.assertEqual(o["reloads"], 1)
        self.assertEqual(o["kept"], "half a sentence")
        self.assertEqual(o["restored"], "half a sentence")
        self.assertEqual(o["left"], [], "restored once, then gone")

    def test_the_restart_paths_check_it(self):
        sse = (STATIC / "app-sse.js").read_text(encoding="utf-8")
        api = (STATIC / "app-api.js").read_text(encoding="utf-8")
        revived = sse[sse.index("async function checkRevived"):]
        self.assertIn("reloadIfAssetsChanged(fp)", revived)
        self.assertIn("restoreReloadDraft()", revived, "the reloaded page's first open puts the draft back")
        defib = api[api.index("async function defibrillateHost"):]
        self.assertIn("reloadIfAssetsChanged(", defib)
