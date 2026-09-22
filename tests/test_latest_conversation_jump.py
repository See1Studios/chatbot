"""The '최신 대화로' button must open the latest session when browsing a past one.
(실장님: 이전 세션을 둘러보다가 최신 대화로 를 눌러도 최신 대화가 로딩안되있다면 실제로 최신대화로 가지 않네.)
Runs the REAL resolveLatestSessionId / goToLatestConversation / updateScrollBottomButton
(sliced out of static/app.js) in node against stubs. Skipped when node is not installed.
Run: python3 -m unittest tests.test_latest_conversation_jump  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
APP = CODE / "static" / "app.js"
HTML = CODE / "static" / "index.html"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a + from.length);
  if (a < 0 || b < 0) throw new Error('marker missing: ' + from + ' .. ' + to);
  return src.slice(a, b);
}
const jump = slice('// ---- latest-conversation jump ----', '// ---- end latest-conversation jump ----');
const btnFn = slice('function updateScrollBottomButton(nearBottomOverride)', 'function scrollChatToBottom');
const fwd = slice('async function resolveScrollforwardFallback', 'async function loadNewerHistory');

let sessionId = '20260920-090000-past1';
let sessionNavNextSid = '20260921-120000-mid2';
let currentTab = 'chat';
const scrolled = [];
const apiCalls = [];
const bodyCls = new Set();
const document = { body: { classList: { contains: c => bodyCls.has(c) } } };
const scrollToBottomBtn = { hidden: true };
const logEl = {
  scrollHeight: 2000, clientHeight: 400, scrollTop: 1600,
  scrollTo(opts) { scrolled.push(opts); this.scrollTop = opts.top; },
};
let sessions = { sessions: [
  { id: '20260921-180000-latest9' },
  { id: '20260921-120000-mid2' },
  { id: '20260920-090000-past1' },
] };
let active = { id: '20260921-180000-latest9' };
const chain = {
  '20260921-120000-mid2': { successor_session_id: '20260921-180000-latest9' },
  '20260921-180000-latest9': { successor_session_id: '' },
};
async function api(path) {
  apiCalls.push(path);
  if (path === '/api/sessions') return sessions;
  if (path === '/api/sessions/active') return active;
  const m = path.match(/^\/api\/sessions\/([^/?]+)$/);
  if (m) return chain[decodeURIComponent(m[1])] || {};
  return {};
}
function isUserNearBottom() {
  return (logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight) <= 140;
}
const body = btnFn + '\n' + jump + '\n' + fwd + `
  let liveSessionId = '';
  let archiveBrowse = false;
  const opened = [];
  async function openSession(id) {
    opened.push(id);
    sessionId = id;
    archiveBrowse = false;
    liveSessionId = id;
  }
  return { viewingPastSession, resolveLatestSessionId, goToLatestConversation, updateScrollBottomButton,
           resolveScrollforwardFallback, followLiveIfNeeded,
           get sessionId() { return sessionId; },
           set sessionId(v) { sessionId = v; },
           get sessionNavNextSid() { return sessionNavNextSid; },
           set sessionNavNextSid(v) { sessionNavNextSid = v; },
           get liveSessionId() { return liveSessionId; },
           set liveSessionId(v) { liveSessionId = v; },
           get archiveBrowse() { return archiveBrowse; },
           set archiveBrowse(v) { archiveBrowse = v; },
           get currentTab() { return currentTab; },
           set currentTab(v) { currentTab = v; },
           bodyCls, scrollToBottomBtn, logEl, opened, scrolled, apiCalls,
           setSessions(v) { sessions = v; }, setActive(v) { active = v; } };`;
const apiObj = new Function(
  'sessionId', 'sessionNavNextSid', 'currentTab', 'document', 'scrollToBottomBtn', 'logEl',
  'api', 'isUserNearBottom',
  body
)(sessionId, sessionNavNextSid, currentTab, document, scrollToBottomBtn, logEl, api, isUserNearBottom);

const out = {};
(async () => {
  // 1. browsing a past session → jump to latest, do not merely scroll
  apiObj.sessionId = '20260920-090000-past1';
  apiObj.liveSessionId = '20260921-180000-latest9';
  apiObj.archiveBrowse = true;
  apiObj.sessionNavNextSid = '20260921-120000-mid2';
  const r1 = await apiObj.goToLatestConversation();
  apiObj.logEl.scrollTop = 2000;
  apiObj.updateScrollBottomButton();
  out.pastJump = {
    result: r1, opened: apiObj.opened.slice(),
    hidden: apiObj.scrollToBottomBtn.hidden,
    past: apiObj.viewingPastSession(),
  };

  // 2. already on latest, scrolled up → scroll only (instant, not smooth)
  apiObj.opened.length = 0; apiObj.scrolled.length = 0;
  apiObj.sessionId = '20260921-180000-latest9';
  apiObj.liveSessionId = '20260921-180000-latest9';
  apiObj.archiveBrowse = false;
  apiObj.sessionNavNextSid = '';
  const r2 = await apiObj.goToLatestConversation();
  out.latestScroll = { result: r2, opened: apiObj.opened.slice(), scrolled: apiObj.scrolled.slice() };

  // 3. active/list still report the past session, but nav knows a successor → walk the chain
  apiObj.opened.length = 0; apiObj.scrolled.length = 0;
  apiObj.sessionId = '20260920-090000-past1';
  apiObj.liveSessionId = '20260920-090000-past1';
  apiObj.archiveBrowse = true;
  apiObj.sessionNavNextSid = '20260921-120000-mid2';
  apiObj.setActive({ id: '20260920-090000-past1' });
  apiObj.setSessions({ sessions: [{ id: '20260920-090000-past1' }] });
  const r3 = await apiObj.goToLatestConversation();
  out.chainWalk = { result: r3, opened: apiObj.opened.slice() };

  // 4. button stays visible at the bottom of a past session
  apiObj.sessionId = '20260920-090000-past1';
  apiObj.liveSessionId = '20260921-180000-latest9';
  apiObj.archiveBrowse = true;
  apiObj.sessionNavNextSid = '20260921-120000-mid2';
  apiObj.logEl.scrollTop = 2000;
  apiObj.updateScrollBottomButton();
  out.pastBtn = { hidden: apiObj.scrollToBottomBtn.hidden, past: apiObj.viewingPastSession() };

  // 5. latest session, near bottom → hide
  apiObj.sessionId = '20260921-180000-latest9';
  apiObj.liveSessionId = '20260921-180000-latest9';
  apiObj.archiveBrowse = false;
  apiObj.sessionNavNextSid = '';
  apiObj.logEl.scrollTop = 2000;
  apiObj.updateScrollBottomButton();
  out.latestNearBottom = { hidden: apiObj.scrollToBottomBtn.hidden };

  // 6. latest session, scrolled up with overflow → show
  apiObj.logEl.scrollTop = 200;
  apiObj.updateScrollBottomButton();
  out.latestScrolledUp = { hidden: apiObj.scrollToBottomBtn.hidden };

  // 7. keyboard open hides even in a past session
  apiObj.sessionNavNextSid = '20260921-120000-mid2';
  apiObj.bodyCls.add('keyboard-open');
  apiObj.updateScrollBottomButton();
  out.keyboardHides = { hidden: apiObj.scrollToBottomBtn.hidden };

  // 8. mtime-sorted list[0] is the past session we just opened; chronological
  //    latest is a newer id further down the list. Must still jump there.
  apiObj.bodyCls.delete('keyboard-open');
  apiObj.opened.length = 0; apiObj.scrolled.length = 0;
  apiObj.sessionId = '20260920-090000-past1';
  apiObj.liveSessionId = '20260920-090000-past1';
  apiObj.archiveBrowse = true;
  apiObj.sessionNavNextSid = '';
  apiObj.setActive({ id: '20260920-090000-past1' });
  apiObj.setSessions({ sessions: [
    { id: '20260920-090000-past1' },
    { id: '20260921-180000-latest9' },
  ] });
  const r8 = await apiObj.goToLatestConversation();
  out.mtimePast = { result: r8, opened: apiObj.opened.slice() };

  // 9. latest session whose "next" is a just-opened older id (mtime leftover)
  //    must NOT count as past-browse — button hides at the bottom.
  apiObj.sessionId = '20260921-180000-latest9';
  apiObj.liveSessionId = '20260921-180000-latest9';
  apiObj.archiveBrowse = false;
  apiObj.sessionNavNextSid = '20260920-090000-past1';
  apiObj.logEl.scrollTop = 2000;
  apiObj.updateScrollBottomButton();
  out.staleNext = { hidden: apiObj.scrollToBottomBtn.hidden, past: apiObj.viewingPastSession() };

  // 10. scroll-forward fallback ignores a past session with newer mtime
  apiObj.setSessions({ sessions: [
    { id: '20260920-090000-past1', updated_at: 9999999999, preview: 'old', turns: 4 },
    { id: '20260921-180000-latest9', updated_at: 1, preview: 'new', turns: 4 },
  ] });
  out.fallbackIgnoresMtime = await apiObj.resolveScrollforwardFallback(
    '20260921-180000-latest9', 1, new Set(['20260921-180000-latest9'])
  );
  out.fallbackFindsLater = await apiObj.resolveScrollforwardFallback(
    '20260920-090000-past1', 1, new Set(['20260920-090000-past1'])
  );

  // 11. archive browse must not auto-follow live; leaving archive does follow
  apiObj.opened.length = 0;
  apiObj.sessionId = '20260920-090000-past1';
  apiObj.liveSessionId = '20260921-180000-latest9';
  apiObj.archiveBrowse = true;
  apiObj.setActive({ id: '20260921-180000-latest9' });
  apiObj.setSessions({ sessions: [
    { id: '20260921-180000-latest9' },
    { id: '20260920-090000-past1' },
  ] });
  out.archiveNoFollow = {
    followed: await apiObj.followLiveIfNeeded(),
    opened: apiObj.opened.slice(),
  };
  apiObj.archiveBrowse = false;
  out.liveFollow = {
    followed: await apiObj.followLiveIfNeeded(),
    opened: apiObj.opened.slice(),
  };

  apiObj.setActive({ id: 'nonexistent-sid-test' });
  apiObj.setSessions({ sessions: [
    { id: 'nonexistent-sid-test', preview: 'leak', turns: 25 },
    { id: '20260921-180000-latest9', preview: 'real', turns: 4 },
  ] });
  out.skipGarbage = await apiObj.resolveLatestSessionId();

  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


class LatestConversationJump(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        cls.app = APP.read_text(encoding="utf-8")
        cls.html = HTML.read_text(encoding="utf-8")

    def test_click_handlers_call_goToLatestConversation(self):
        self.assertIn("goToLatestConversation();", self.app)
        self.assertGreaterEqual(self.app.count("goToLatestConversation();"), 2)
        self.assertIn("scrollToBottomBtn.addEventListener('click'", self.app)
        self.assertRegex(self.html, r"app\.js\?v=\d+")
        self.assertNotIn("app.js?v=100", self.html)
        self.assertIn("followLiveIfNeeded", self.app)
        self.assertIn("archiveBrowse", self.app)
        self.assertIn('class="stage-shell"', self.html)
        self.assertIn('id="scrollToBottomBtn"', self.html)
        # Overlay is a sibling of .stage (not inside #log) so iOS overflow
        # scrolling cannot steal taps.
        self.assertLess(self.html.find('class="stage-shell"'), self.html.find('id="scrollToBottomBtn"'))
        self.assertGreater(self.html.find('id="scrollToBottomBtn"'), self.html.find('id="sessionsPane"'))

    def test_jump_behavior(self):
        if not self.node:
            self.skipTest("node not installed")
        proc = subprocess.run(
            [self.node, "-e", HARNESS, str(APP)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["pastJump"]["result"], "jump")
        self.assertEqual(out["pastJump"]["opened"], ["20260921-180000-latest9"])
        self.assertTrue(out["pastJump"]["hidden"])
        self.assertFalse(out["pastJump"]["past"])
        self.assertEqual(out["latestScroll"]["result"], "scroll")
        self.assertEqual(out["latestScroll"]["opened"], [])
        self.assertTrue(out["latestScroll"]["scrolled"])
        self.assertEqual(out["latestScroll"]["scrolled"][0].get("behavior"), "auto")
        self.assertEqual(out["chainWalk"]["result"], "jump")
        self.assertEqual(out["chainWalk"]["opened"], ["20260921-180000-latest9"])
        self.assertFalse(out["pastBtn"]["hidden"])
        self.assertTrue(out["pastBtn"]["past"])
        self.assertTrue(out["latestNearBottom"]["hidden"])
        self.assertFalse(out["latestScrolledUp"]["hidden"])
        self.assertTrue(out["keyboardHides"]["hidden"])
        self.assertEqual(out["mtimePast"]["result"], "jump")
        self.assertEqual(out["mtimePast"]["opened"], ["20260921-180000-latest9"])
        self.assertTrue(out["staleNext"]["hidden"])
        self.assertFalse(out["staleNext"]["past"])
        self.assertEqual(out["fallbackIgnoresMtime"], "")
        self.assertEqual(out["fallbackFindsLater"], "20260921-180000-latest9")
        self.assertFalse(out["archiveNoFollow"]["followed"])
        self.assertEqual(out["archiveNoFollow"]["opened"], [])
        self.assertTrue(out["liveFollow"]["followed"])
        self.assertEqual(out["liveFollow"]["opened"], ["20260921-180000-latest9"])
        self.assertEqual(out["skipGarbage"], "20260921-180000-latest9")


if __name__ == "__main__":
    unittest.main()
