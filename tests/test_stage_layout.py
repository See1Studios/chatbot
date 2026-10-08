"""The staged reply's face (STAGE_v1, app-stage.js) is a button only when it does something: it opens the thought, or
in a group room it calls that member. Otherwise it leaves the tab order and the screen reader's view (critique run 4:
every reply added an unnamed, inert button to the tab order). Runs the REAL stageSync in node against stubs.
Run: engine/run-tests.sh test_stage_layout
"""
import json
import shutil
import subprocess
import unittest

from tests._paths import REPO  # noqa: E402

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function stageSync'), b = src.indexOf('\n}\n', a) + 3;
function el(cls) { const attrs = {}; return { cls, tabIndex: 0, title: '', attrs, classList: { add() {}, remove() {} },
  setAttribute(k, v) { attrs[k] = v; }, removeAttribute(k) { delete attrs[k]; }, getAttribute(k) { return attrs[k] || null; } }; }
let kids = [];
const stageOn = () => true, stageLayout = () => {}, stageKids = () => kids;
const stageHas = (x, c) => x && (x.cls === c || (x.classes || []).includes(c));
eval(src.slice(a, b));
function run(withThought, roomWho) {
  const face = el('md-face');
  kids = withThought ? [face, el('thought-box')] : [face];
  const msg = { classes: ['staged'], dataset: roomWho ? { roomWho } : {}, getAttribute: () => null };
  const md = { children: kids, parentNode: msg, insertBefore() {}, appendChild() {} };
  stageSync(md);
  return { tab: face.tabIndex, hidden: face.attrs['aria-hidden'] || '' };
}
console.log(JSON.stringify({ thought: run(true), none: run(false), room: run(false, 'b') }));
"""


class StageFace(unittest.TestCase):
    def test_only_a_face_that_acts_is_a_button(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        p = subprocess.run([node, "-e", HARNESS, str(REPO / "static" / "app-stage.js")], capture_output=True, text=True,
                           timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["thought"], {"tab": 0, "hidden": "false"})
        self.assertEqual(out["none"], {"tab": -1, "hidden": "true"})
        self.assertEqual(out["room"], {"tab": 0, "hidden": "false"}, "in a group room the face calls the member")


if __name__ == "__main__":
    unittest.main()
