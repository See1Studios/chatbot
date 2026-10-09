"""#887: a handover's wait (a long talk moving to a new session) shows as a stage direction line before the answer's
bubble, not as words inside it -- the operator: "말풍선에 합쳐져버려서 기다리는 게 더 답답한 상황".
Run: engine/run-tests.sh test_stage_line
"""
import json
import shutil
import subprocess
import unittest

from tests._paths import ENGINE, REPO  # noqa: E402

STATIC = REPO / "static"

JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
eval(src.slice(src.indexOf('function stageLine(text)')));
const log = { kids: [], insertBefore(n, ref) { this.kids.splice(this.kids.indexOf(n), 1); this.kids.splice(this.kids.indexOf(ref), 0, n); } };
function addChat(role, text) { const n = { role, text, parentNode: log, isConnected: true }; log.kids.push(n); return n; }
let assistantNode = addChat('assistant', '');
let assistantBuf = '';
stageLine('(notes)');
console.log(JSON.stringify(log.kids.map(n => [n.role, n.text])));
"""


class StageLine(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_it_stands_before_the_empty_answer_bubble(self):
        p = subprocess.run(["node", "-e", JS, str(STATIC / "app-turn.js")], capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr[-500:])
        self.assertEqual(json.loads(p.stdout), [["action", "✦ (notes)"], ["assistant", ""]])

    def test_the_server_sends_it_as_a_stage_and_the_page_draws_it(self):
        src = (ENGINE / "session_turn.py").read_text(encoding="utf-8")
        self.assertIn('{"event": "stage", **i18n.msg("srv.handoff_stage")}', src)
        self.assertNotIn('"event": "progress", **i18n.msg("srv.handoff_writing")', src)
        self.assertIn("if (type === 'stage') { stageLine(text); return; }",
                      (STATIC / "app-sse.js").read_text(encoding="utf-8"))
        for lang in ("ko", "en"):
            cat = json.loads((STATIC / "i18n" / ("%s.json" % lang)).read_text(encoding="utf-8"))
            self.assertTrue(cat["srv.handoff_stage"].startswith("("), "a stage direction, in parentheses")


if __name__ == "__main__":
    unittest.main()
