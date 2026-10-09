"""The theme the user picks is theirs (THEME_OWN_v1): a brain switch used to repaint the lamp in the provider's catalog
theme, so a picked swatch did not survive the next model change (PRODUCT: personalization survives a provider
switch). Until a swatch is picked the lamp follows the brain. Runs the REAL theme.js helpers in node against stubs.
Run: engine/run-tests.sh test_theme_own
"""
import json
import re
import shutil
import subprocess
import unittest
from tests.page_source import app_source  # noqa: E402
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"
THEME = STATIC / "theme.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('const THEME_CHOSEN_KEY'), b = src.indexOf('let initialTheme', a);
if (a < 0 || b < 0) throw new Error('markers missing');
const store = {};
const localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
const painted = [];
function applyTheme(name) { painted.push(name); store['chatbot.themeColor'] = name; }
eval(src.slice(a, b));
applyBrainTheme('spark');                 // nothing picked: the lamp follows the brain
const follows = painted[painted.length - 1];
chooseTheme('amber');                     // the user picks a swatch
applyBrainTheme('mono');                  // then switches to a brain whose catalog theme is mono
console.log(JSON.stringify({ follows, kept: painted[painted.length - 1], chosen: store['chatbot.themeChosen'] }));
"""


class ThemeOwn(unittest.TestCase):
    def test_a_picked_theme_outlives_a_brain_switch(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        proc = subprocess.run([node, "-e", HARNESS, str(THEME)], capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"follows": "spark", "kept": "amber", "chosen": "amber"})

    def test_brain_switches_and_swatches_go_through_the_owner_rule(self):
        src = app_source()
        self.assertNotRegex(src, r"\bapplyTheme\(themeForProvider", "a brain switch paints via applyBrainTheme")
        self.assertEqual(len(re.findall(r"applyBrainTheme\(themeForProvider", src)), 3)
        self.assertIn("chooseTheme(name)", (STATIC / "app-shell-panes.js").read_text(encoding="utf-8"))
        self.assertIn("chooseTheme(chosen)", THEME.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
