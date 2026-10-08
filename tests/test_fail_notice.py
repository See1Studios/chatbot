"""A failed action the user started is said in the talk, not only in the activity log (FAIL_NOTICE_v1).
The activity log is dev-only in shell2, so a failure logged only there looked like nothing happened. The guard reads
the page's scripts: an addActivity line naming a failure key goes through failNotice, or is listed below with the
place the user sees that failure. The node harnesses run the REAL failNotice / syncBlockedNotice against stubs.
Run: engine/run-tests.sh test_fail_notice
"""
import json
import re
import shutil
import subprocess
import unittest
from tests.page_source import app_bundle, app_files, i18n_prelude  # noqa: E402
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"
# file -> failure keys whose addActivity line may stay alone, because the user sees that failure elsewhere
SHOWN_ELSEWHERE = {
    "app-attach.js": {"ATTACH_TEXT.failed"},              # the attach chip turns to its error face with the error
    "app-api.js": {"api.continue_failed",                  # recovers by itself: a new talk opens
                   "api.defib_failed"},                    # the reboot HUD and the progress line say it
    "app-characters.js": {"team.st_failed"},               # showCharacterToast
    "app-sse.js": {"chat.conn_failed"},                    # setProgress(chat.conn_lost)
    "app-status.js": {"status.login.activity_failed"},     # the login panel shows the failed state
}
FAIL_KEY = re.compile(r"""tr\('([\w.]*fail\w*)'|\b([A-Z_]+_TEXT\.\w*[Ff]ail\w*)""")


def activity_failure_keys(text):
    keys = []
    for m in re.finditer(r"\baddActivity\(", text):
        call = text[m.end():text.find(";", m.end())]
        for k in FAIL_KEY.finditer(call):
            keys.append(k.group(1) or k.group(2))
    return keys


HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(a, b) { const i = src.indexOf(a), j = src.indexOf(b, i); if (i < 0 || j < 0) throw new Error('markers missing: ' + a); return src.slice(i, j); }
function el(tag) {
  return { tag, children: [], className: '', textContent: '', isConnected: true, listeners: {},
           append(...c) { this.children.push(...c); }, appendChild(c) { this.children.push(c); return c; },
           addEventListener(k, f) { this.listeners[k] = f; }, remove() { this.isConnected = false; } };
}
const document = { createElement: el };
const activity = [], notices = [], panes = [];
function addActivity(line, kind) { activity.push([line, kind]); }
function addNotice(kind, text) { const n = el('div'); n.kind = kind; n.text = text; notices.push(n); return n; }
function shellGoPane(tab, from) { panes.push([tab, from]); }
let gate = { pid: 'grok', reason: '' };
function syncProviderUseGates() { syncBlockedNotice(gate.reason ? gate.pid + '\n' + gate.reason : '', gate.reason); }
eval(slice('function failNotice', 'function prependActivity'));
eval(slice('let _blockedNotice', 'function themeForProvider'));
const out = {};
const n = failNotice(tr('session.mode_failed'), new Error('HTTP 502'));
out.fail = { kind: n.kind, text: n.text, detail: n.children.map(c => [c.className, c.children.map(x => x.textContent)]),
             activity: activity.slice() };
const quiet = failNotice(tr('chat.stop_failed'));
out.noError = { children: quiet.children.length, activity: activity[activity.length - 1] };
notices.length = 0;
gate.reason = '로그인 필요'; syncProviderUseGates(); syncProviderUseGates();
out.once = notices.length;
const first = notices[0];
first.children[0].listeners.click();
out.button = { text: first.children[0].textContent, panes: panes.slice() };
first.remove();                           // swiped away: not put back while the block is the same
syncProviderUseGates();
out.afterSwipe = notices.length;
reshowBlockedNotice();                    // a new talk cleared the log
out.afterNewTalk = notices.length;
gate.reason = ''; syncProviderUseGates();
out.unblocked = notices[notices.length - 1].isConnected;
console.log(JSON.stringify(out));
"""


class FailNotice(unittest.TestCase):
    def test_a_failure_logged_only_for_dev_goes_through_fail_notice(self):
        files = app_files() + [STATIC / "artifacts.js"]
        for p in files:
            allowed = SHOWN_ELSEWHERE.get(p.name, set())
            for key in activity_failure_keys(p.read_text(encoding="utf-8")):
                self.assertIn(key, allowed, "%s: addActivity(%s) only reaches the dev log -- use failNotice(text, error), "
                                            "or list it in SHOWN_ELSEWHERE with where the user sees it" % (p.name, key))

    def test_the_allowlist_has_no_stale_entries(self):
        for name, keys in SHOWN_ELSEWHERE.items():
            found = set(activity_failure_keys((STATIC / name).read_text(encoding="utf-8")))
            self.assertEqual(keys - found, set(), "%s: drop the entries that are no longer there" % name)

    def test_shell2_keeps_the_talk_when_the_provider_is_blocked(self):
        api = (STATIC / "app-api.js").read_text(encoding="utf-8")
        chars = (STATIC / "app-characters.js").read_text(encoding="utf-8")
        self.assertIn("if (!shell2 && (tab === 'chat'", api)
        self.assertIn("if (blocked && !shell2 &&", chars)

    def test_the_notice_line_carries_no_raw_error(self):
        for lang in ("ko", "en"):
            cat = json.loads((STATIC / "i18n" / ("%s.json" % lang)).read_text(encoding="utf-8"))
            for key in ("session.mode_failed", "shell.character_failed", "chat.stop_failed", "artifacts.load_failed",
                        "artifacts.more_failed", "item.failed", "shellbrain.brainResetFail"):
                self.assertNotIn("{error}", cat[key], "%s %s: the raw error goes under details" % (lang, key))

    def test_notices_behave(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        proc = subprocess.run([node, "-e", i18n_prelude() + HARNESS, str(app_bundle())], capture_output=True, text=True,
                              timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        cat = json.loads((STATIC / "i18n" / "ko.json").read_text(encoding="utf-8"))
        self.assertEqual(out["fail"]["kind"], "warn")
        self.assertEqual(out["fail"]["text"], cat["session.mode_failed"])
        self.assertEqual(out["fail"]["detail"], [["notice-detail", [cat["notice.detail"], "HTTP 502"]]])
        self.assertEqual(out["fail"]["activity"], [[cat["session.mode_failed"] + " — HTTP 502", "warn"]])
        self.assertEqual(out["noError"], {"children": 0, "activity": [cat["chat.stop_failed"], "warn"]})
        self.assertEqual(out["once"], 1, "one notice per block")
        self.assertEqual(out["button"], {"text": cat["notice.open_accounts"], "panes": [["status", ""]]})
        self.assertEqual(out["afterSwipe"], 1, "a swiped-away notice stays away")
        self.assertEqual(out["afterNewTalk"], 2, "a new talk shows it again")
        self.assertFalse(out["unblocked"], "unblocked: the notice goes")


if __name__ == "__main__":
    unittest.main()
