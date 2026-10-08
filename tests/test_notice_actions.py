"""A failure notice says one plain line, keeps the engine's raw error under 'details', and offers the way on
(NOTICE_ACTIONS_v1, critique 2026-10-08 P1: "failures speak in engine voice inside the companion's log; only the
blocked one has an action"). Which buttons is decided by the notice's key, never by its words.
Run: engine/run-tests.sh test_notice_actions
"""
import json
import shutil
import subprocess
import unittest

from tests.page_source import i18n_prelude  # noqa: E402
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"
PLAIN = ("srv.agent_exited", "srv.api_failed", "srv.claude_limit", "srv.http_timeout", "srv.quota_exhausted",
         "srv.quota_or_provider", "srv.quota_or_provider_closed", "srv.tool_hops_exceeded", "turn.backend_died",
         "chat.conn_lost", "chat.conn_failed")

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function el(tag) { return { tag, children: [], listeners: {}, className: '', textContent: '', disabled: false, value: '',
  appendChild(c) { this.children.push(c); return c; }, append(...c) { this.children.push(...c); },
  addEventListener(k, f) { this.listeners[k] = f; }, querySelectorAll() { return this.children.filter(x => x.tag === 'button'); },
  click() { calls.push('send'); } }; }
const calls = [], notices = [];
const input = el('textarea'), sendBtn = el('button');
const document = { createElement: el, getElementById: (id) => (id === 'input' ? input : id === 'send' ? sendBtn : null) };
const location = { reload() { calls.push('reload'); } };
let offer = 'held';
function retryHint() { return offer; }
function pickModel(m) { calls.push('pick:' + m); }
function shellProfileOpen() { calls.push('profile'); }
function addActivity() {}
function addNotice(kind, text) { const n = el('div'); n.kind = kind; n.text = text; notices.push(n); return n; }
function noticeDetail(node, raw) { const d = el('details'); d.raw = raw; node.appendChild(d); }
eval(src.slice(src.indexOf('function quotaSwitchButtons')));
const show = (n) => n.children.map(c => c.tag === 'details' ? 'details:' + c.raw : c.textContent);
const out = {};
let n = el('div'); noticeActions(n, { key: 'srv.quota_or_provider', vars: { error: 'Resets in 4h' } }); out.quota = show(n);
n.children[1].listeners.click(); out.afterPick = calls.slice(); out.disabled = n.querySelectorAll().map(b => b.disabled);
n = el('div'); noticeActions(n, { key: 'srv.quota_until', suggest: ['gemini-low'] }); out.suggest = show(n);
n = el('div'); noticeActions(n, { key: 'srv.agent_exited', error: 'exit 1' }); out.other = show(n);
calls.length = 0; n.children[1].listeners.click(); out.resend = calls.slice();
offer = ''; n = el('div'); noticeActions(n, { key: 'srv.agent_exited' }); out.noOffer = show(n);
calls.length = 0; connLost(); out.lost = { kind: notices[0].kind, buttons: show(notices[0]) };
notices[0].children[0].listeners.click(); out.reload = calls.slice();
console.log(JSON.stringify(out));
"""


class NoticeActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ko = json.loads((STATIC / "i18n" / "ko.json").read_text(encoding="utf-8"))
        node = shutil.which("node")
        cls.out = None
        if node:
            p = subprocess.run([node, "-e", i18n_prelude() + HARNESS, str(STATIC / "app-retry.js")], capture_output=True,
                               text=True, timeout=15)
            assert p.returncode == 0, p.stderr
            cls.out = json.loads(p.stdout)

    def need(self):
        if self.out is None:
            self.skipTest("node not installed")
        return self.out

    def test_a_quota_or_provider_failure_offers_another_brain_and_a_resend(self):
        o, t = self.need(), self.ko
        self.assertEqual(o["quota"], ["details:Resets in 4h", t["notice.pick_brain"], t["notice.resend"]])
        self.assertEqual(o["afterPick"], ["profile"])
        self.assertEqual(o["disabled"], [True, True], "one choice: the others turn off")

    def test_held_for_quota_with_suggestions_shows_only_the_switches(self):
        self.assertEqual(self.need()["suggest"], [self.ko["quota.switch_to"].replace("{model}", "gemini-low")])

    def test_another_failure_offers_the_resend_when_there_is_one(self):
        o, t = self.need(), self.ko
        self.assertEqual(o["other"], ["details:exit 1", t["notice.resend"]])
        self.assertEqual(o["resend"], ["send"])
        self.assertEqual(o["noOffer"], [], "nothing to resend: no button")

    def test_a_lost_connection_is_a_notice_with_a_reload(self):
        o = self.need()
        self.assertEqual(o["lost"], {"kind": "error", "buttons": [self.ko["notice.reload"]]})
        self.assertEqual(o["reload"], ["reload"])

    def test_the_failure_lines_carry_no_raw_error_and_no_engine_words(self):
        for lang in ("ko", "en"):
            cat = json.loads((STATIC / "i18n" / ("%s.json" % lang)).read_text(encoding="utf-8"))
            for k in PLAIN:
                self.assertNotIn("{error}", cat[k], "%s %s: the raw error goes under details" % (lang, k))
        for k in PLAIN:
            for word in ("에이전트", "백엔드", "프로바이더", "20회"):
                self.assertNotIn(word, self.ko[k], k)

    def test_help_describes_the_screen_that_ships(self):
        # critique run 4: /help still taught the tabs, Alt+1..6 and the header ... button, none of which shell2 shows
        for lang in ("ko", "en"):
            body = json.loads((STATIC / "i18n" / ("%s.json" % lang)).read_text(encoding="utf-8"))["help.body"]
            for gone in ("Alt+1", "Alt+3", "/private", "\u22ef"):
                self.assertNotIn(gone, body, "%s help: %s" % (lang, gone))
            for there in ("Alt+O", "/move", "/act"):
                self.assertIn(there, body, "%s help: %s" % (lang, there))
        for k in ("srv.turn_ended_early", "srv.hang_closed", "turn.backend_stopped", "srv.session_heavy",
                  "session.banner_long", "session.new", "menu.defib", "srv.turn_closed"):
            for word in ("에이전트", "백엔드", "세션", "턴", "리부트"):
                self.assertNotIn(word, self.ko[k], k)

    def test_both_failure_paths_of_the_stream_use_it(self):
        sse = (STATIC / "app-sse.js").read_text(encoding="utf-8")
        self.assertIn("if (nn && typeof noticeActions === 'function') noticeActions(nn, data);", sse)
        self.assertIn("if (rn && typeof noticeActions === 'function') noticeActions(rn, data);", sse)
        self.assertIn("if (typeof connLost === 'function') connLost();", sse)


if __name__ == "__main__":
    unittest.main()
