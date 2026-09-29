"""CHAT_FLOW_v1 (static/app-flow.js, ux-shell-roadmap 4.2.1b, #418): day dividers instead of session dividers, the
user's consecutive bubbles grouped. planFlow runs in node against the real file.
Run: python3 -m unittest tests.test_chat_flow  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const cut = src.slice(src.indexOf('const FLOW_GROUP_SEC'), src.indexOf('function flowMessages'));
const api = new Function(cut + '; return { planFlow, flowDayLabel };')();
const now = new Date(2026, 8, 29, 15, 0, 0).getTime();          // Tue 2026-09-29 15:00 local
const s = (y, mo, d, h, mi) => new Date(y, mo, d, h, mi, 0).getTime() / 1000;
const items = [
  { role: 'user', ts: s(2026, 8, 27, 22, 0) },                   // Sat
  { role: 'other', ts: s(2026, 8, 27, 22, 1) },
  { role: 'user', ts: s(2026, 8, 28, 23, 58) },                  // yesterday, a run of two
  { role: 'user', ts: s(2026, 8, 28, 23, 59) },
  { role: 'user', ts: s(2026, 8, 29, 0, 1) },                    // today: a new day ends the run
  { role: 'user', ts: s(2026, 8, 29, 0, 30) },                   // 29 minutes later: not a run
  { role: 'other', ts: 0 },                                       // still arriving: counts as now
];
console.log(JSON.stringify({ plan: api.planFlow(items, now, 'ko'),
                             lastYear: api.flowDayLabel(s(2025, 11, 31, 12, 0) * 1000, now, 'ko') }));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ChatFlow(unittest.TestCase):
    def setUp(self):
        out = subprocess.run(["node", "-e", JS, str(STATIC / "app-flow.js")], capture_output=True, text=True,
                             encoding="utf-8", timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.r = json.loads(out.stdout)

    def test_a_divider_opens_each_day(self):
        ds = self.r["plan"]["dividers"]
        self.assertEqual([d["before"] for d in ds], [0, 2, 4])
        self.assertIn("27", ds[0]["label"])
        self.assertEqual(ds[1]["label"], "어제")
        self.assertEqual(ds[2]["label"], "오늘")

    def test_only_the_users_close_bubbles_on_one_day_group(self):
        self.assertEqual(self.r["plan"]["cont"], [3])

    def test_another_year_names_the_year(self):
        self.assertIn("2025", self.r["lastYear"])

    def test_session_dividers_wait_for_the_advanced_density(self):
        css = (STATIC / "chat-log.css").read_text(encoding="utf-8")
        self.assertIn(".session-divider{display:none}", css)
        self.assertIn("body.density-advanced .session-divider{display:flex}", css)
        js = (STATIC / "app-session.js").read_text(encoding="utf-8")
        self.assertEqual(js.count("'msg scrollback-marker session-divider'"), 2)


if __name__ == "__main__":
    unittest.main()
