"""CHAT_FLOW_v1 (static/app-flow.js, ux-shell-roadmap 4.2.1b, #418): day dividers instead of session dividers, the
user's consecutive bubbles grouped. planFlow runs in node against the real file.
Run: python3 -m unittest tests.test_chat_flow  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"

JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const cut = src.slice(src.indexOf('const FLOW_GROUP_SEC'), src.indexOf('function flowMessages'));
const tail = src.slice(src.indexOf('function msToNextMidnight'));
const api = new Function(cut + tail + '; return { planFlow, flowDayLabel, msToNextMidnight };')();
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
                             lastYear: api.flowDayLabel(s(2025, 11, 31, 12, 0) * 1000, now, 'ko'),
                             toMidnight: api.msToNextMidnight(now) }));
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

    def test_an_idle_page_turns_the_day_over_at_midnight(self):
        self.assertEqual(self.r["toMidnight"], 9 * 3600 * 1000)          # 15:00 -> 24:00

    def test_another_year_names_the_year(self):
        self.assertIn("2025", self.r["lastYear"])

    def test_session_dividers_wait_for_the_advanced_density(self):
        css = (STATIC / "chat-log.css").read_text(encoding="utf-8")
        # #419: a plain .session-divider rule lost to .scrollback-marker{display:flex}, which chat-panes.css (read
        # after chat-log.css) sets with the same weight -- the hiding rule must outweigh one class
        self.assertIn("#log > .msg.session-divider{display:none}", css)
        self.assertIn("body.density-advanced #log > .msg.session-divider{display:flex}", css)
        panes = (STATIC / "chat-panes.css").read_text(encoding="utf-8")
        self.assertNotIn("#log > .msg.scrollback-marker", panes)   # nothing there as strong as the hiding rule
        js = (STATIC / "app-session.js").read_text(encoding="utf-8")
        self.assertEqual(js.count("'msg scrollback-marker session-divider'"), 2)


class Density(unittest.TestCase):
    """CHAT_DENSITY_v1 (#420): meters and session dividers wait for the "details" switch."""

    def test_the_switch_is_in_the_menu_and_remembered(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="densityBtn"', html)
        js = (STATIC / "app-flow.js").read_text(encoding="utf-8")
        self.assertIn("density-advanced", js)
        self.assertIn("localStorage.setItem(DENSITY_KEY", js)

    def test_the_simple_density_hides_the_meters_not_the_actions(self):
        css = (STATIC / "chat-log.css").read_text(encoding="utf-8")
        self.assertIn("body:not(.density-advanced) .msg-footer .token-badge", css)
        self.assertIn("body:not(.density-advanced) .msg-footer .served-model", css)
        self.assertNotIn(".tts-btn{display:none}", css)          # copy/read stay reachable


class OneDividerStyle(unittest.TestCase):
    """#421: the chat had four kinds of lines; the time and history markers now share the day divider's look."""

    def test_a_hidden_message_opens_no_day(self):
        # 2026-10-04: a coworker dm hidden until scrollback reaches it still left its "어제" divider in place
        src = (STATIC / "app-flow.js").read_text(encoding="utf-8")
        body = src[src.index("function flowMessages("):src.index("function applyFlow(")]
        js = ("const src = require('fs').readFileSync(process.argv[1], 'utf8');"
              "eval(src.slice(src.indexOf('function flowMessages('), src.indexOf('function applyFlow(')));"
              "const m = (h) => ({ hidden: h, classList: { contains: c => c === 'msg' } });"
              "console.log(flowMessages({ children: [m(false), m(true), m(false)] }).length);")
        out = subprocess.run(["node", "-e", js, str(STATIC / "app-flow.js")], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "2")
        self.assertIn("!n.hidden", body)

    def test_no_marker_draws_its_line_in_text(self):
        js = (STATIC / "app-session.js").read_text(encoding="utf-8")
        self.assertNotIn("'── 대화 시작", js)
        self.assertNotIn("'── 세션 ' + data.session.id", js)
        self.assertEqual(js.count("flow-line"), 4)          # two history starts, one new conversation, one retry note

    def test_the_simple_density_drops_the_footer_rule(self):
        css = (STATIC / "chat-log.css").read_text(encoding="utf-8")
        self.assertIn("body:not(.density-advanced) .msg.assistant .msg-footer{border-top-color:transparent", css)


if __name__ == "__main__":
    unittest.main()
