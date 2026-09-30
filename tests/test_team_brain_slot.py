"""The team tab shows an empty second brain slot when a character has one brain, so the operator sees a fallback can
be added (static/app-team.js teamSpareSlot). The REAL function runs in node against a tiny DOM stub.
Run: python3 -m unittest tests.test_team_brain_slot  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const document = { getElementById: () => null };
function obsNode(tag, cls, text) { return { tag, cls, text: text || '', kids: [], appendChild(k) { this.kids.push(k); } }; }
const { teamSpareSlot } = new Function('document', 'obsNode', src + '; return { teamSpareSlot };')(document, obsNode);
const one = teamSpareSlot(1);
console.log(JSON.stringify({ zero: teamSpareSlot(0), two: teamSpareSlot(2), one: one && { cls: one.cls, n: one.kids[0].text, text: one.kids[1].text } }));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SpareSlot(unittest.TestCase):
    def test_only_a_lone_brain_shows_the_empty_fallback_slot(self):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-team.js")], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        o = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIsNone(o["zero"], "no brains: the existing 'default settings' hint")
        self.assertIsNone(o["two"], "a fallback already exists")
        self.assertEqual((o["one"]["cls"], o["one"]["n"]), ("team-brain team-brain-spare", "2"))
        self.assertIn("예비 두뇌 없음", o["one"]["text"])


if __name__ == "__main__":
    unittest.main()
