"""TAB_CHROME_v1: the character's scene (stage background, standing sprite) and the input bar belong to the chat
tab; the tool tabs (sessions, log, artifacts, status, improve, team) are plain. The REAL switchTab (static/app-api.js)
runs in node against stubs and must mark the page with the tab; the stylesheet, read in cascade order, must hide
the scene and the input bar for every tab but chat. Skipped without node.
Run: python3 -m unittest tests.test_tab_chrome  (from services/chatbot)
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import page_source  # noqa: E402
from tests._paths import REPO  # noqa: E402

API = REPO / "static" / "app-api.js"
NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function switchTab('), b = src.indexOf('function escapeHtml(');
if (a < 0 || b < 0) throw new Error('markers missing');
const document = { documentElement: { dataset: {} }, getElementById: () => null };
let currentTab = '';
const noop = () => {};
const isProviderUseBlocked = () => false, chatProvider = () => 'agy';
const tabChat = null, tabArtifacts = null, tabActivity = null, tabStatus = null, tabSessions = null,
      tabEvolution = null, tabTeam = null, logEl = null, activityPaneEl = null, activityEl = null,
      statusPaneEl = null, sessionsPaneEl = null, evolutionPaneEl = null, teamPaneEl = null;
const fetchArtifacts = noop, scrollChatToBottom = noop, fetchSelfStatus = noop, renderStatusPicker = noop,
      fetchAccounts = noop, fetchUsage = noop, fetchEvolution = noop, loadTeam = noop, fetchSessionsList = noop,
      updateScrollBottomButton = noop, placeStopBtn = noop;
eval(src.slice(a, b));
const seen = {};
for (const t of ['status', 'team', 'chat', 'sessions']) { switchTab(t); seen[t] = document.documentElement.dataset.tab; }
console.log(JSON.stringify(seen));
"""

HIDDEN_OFF_CHAT = (".stage::before", ".character-sprite", ".composer", "#choiceBar")


class TabChrome(unittest.TestCase):
    @unittest.skipUnless(NODE, "node not installed")
    def test_switching_tabs_marks_the_page(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "h.js"
            h.write_text(HARNESS, encoding="utf-8")
            r = subprocess.run([NODE, str(h), str(API)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]),
                         {"status": "status", "team": "team", "chat": "chat", "sessions": "sessions"})

    def test_the_scene_and_the_input_bar_are_hidden_off_the_chat_tab(self):
        css = re.sub(r"/\*.*?\*/", "", page_source.css_source(), flags=re.S)
        off = ':root[data-tab]:not([data-tab="chat"])'
        rules = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        for target in HIDDEN_OFF_CHAT:
            hits = [body for sel, body in rules
                    if any(s.strip() == "%s %s" % (off, target) for s in sel.split(","))]
            self.assertTrue(hits, "no off-chat rule for %s" % target)
            self.assertTrue(any("display: none" in b or "opacity: 0" in b for b in hits), target)

    def test_the_session_import_opens_the_chat_before_it_fills_the_input(self):
        # a hidden box takes no focus: importSessionContext runs from the sessions tab
        src = page_source.app_source()
        body = src[src.index("async function importSessionContext("):]
        body = body[:body.index("\n}\n")]
        self.assertLess(body.index("switchTab('chat')"), body.index("inputEl.focus()"))


if __name__ == "__main__":
    unittest.main()
