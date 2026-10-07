"""Bold/italic right before a letter with no space parses the same in every script (markdown.js, I18N_v1): the fix
once matched Korean letters only. ASCII letters are left to marked, so a*b*c and code keep their stars.
Run: engine/run-tests.sh test_markdown_letters
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

SRC = (REPO / "static" / "markdown.js").read_text(encoding="utf-8")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Letters(unittest.TestCase):
    def test_every_script_gets_the_same_fix_and_ascii_is_left_alone(self):
        rules = [l.strip() for l in SRC.splitlines() if l.strip().startswith("raw = raw.replace(/") and "\\p{L}" in l]
        self.assertEqual(len(rules), 2, rules)
        cases = ['**"A"**는', '**"A"**は', '**"A"**的', '**B**s', 'a*b*c']   # l10n-ok: one particle per script
        js = "let raw;\nconsole.log(JSON.stringify(%s.map(t => { raw = t; %s %s return raw; })));" % (json.dumps(cases), rules[0], rules[1])
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        out = json.loads(r.stdout)
        self.assertEqual([o.startswith('<strong>"A"</strong>') for o in out[:3]], [True, True, True])
        self.assertEqual(out[3:], ['**B**s', 'a*b*c'])


if __name__ == "__main__":
    unittest.main()
