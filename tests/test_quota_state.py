"""Which brain is out of quota until when (QUOTA_STATE_v1, docs/plans/quota-failure-resilience.md qfr/A): read from the
provider's usage report through the adapter's quota view, never from error wording; a failed turn reads it once; a send
to a brain recorded out of quota is not made until its reset time (2026-10-08: a Claude-route quota hit at 13:32 with
the five-hour window at 0 % until 18:25 KST).
Run: engine/run-tests.sh test_quota_state
"""
import time
import unittest
from unittest import mock

import quota_state as Q  # noqa: E402
import route_sessions  # noqa: E402
from tests._paths import ENGINE  # noqa: E402

NOW = 1_791_436_000.0
ISO = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def view(*windows):
    return {"scope": "Claude and GPT models", "windows": [{"label": l, "pct": p, "reset_at": r} for l, p, r in windows]}


class ReadAndBlock(unittest.TestCase):
    def setUp(self):
        Q._STATE.clear()

    def read(self, v, model="claude-opus-5-5-high"):
        with mock.patch.object(Q, "_report", return_value=v):
            return Q.read("agy", model, now=NOW)

    def test_an_empty_window_with_a_reset_to_come_is_recorded_until_the_latest_reset(self):
        hit = self.read(view(("5h", 0, ISO(NOW + 3600)), ("week", 0, ISO(NOW + 7200)), ("x", 40, ISO(NOW + 99))))
        self.assertEqual((hit["window"], hit["until"]), ("week", NOW + 7200))
        self.assertEqual(Q.blocked("agy", "claude-opus-5-5-high", now=NOW + 10)["until"], NOW + 7200)
        self.assertIsNone(Q.blocked("agy", "gemini-3.8-flash-high", now=NOW + 10), "another brain is not held")

    def test_the_hold_ends_at_its_time_and_a_good_report_clears_it(self):
        self.read(view(("5h", 0, ISO(NOW + 60))))
        self.assertIsNone(Q.blocked("agy", "claude-opus-5-5-high", now=NOW + 61))
        self.read(view(("5h", 0, ISO(NOW + 600))))
        self.read(view(("5h", 30, ISO(NOW + 600))))
        self.assertIsNone(Q.blocked("agy", "claude-opus-5-5-high", now=NOW))

    def test_no_reset_time_a_past_one_or_no_model_records_nothing(self):
        self.assertIsNone(self.read(view(("5h", 0, ""))))
        self.assertIsNone(self.read(view(("5h", 0, ISO(NOW - 5)))))
        self.assertIsNone(self.read(view(("5h", 0, ISO(NOW + 60))), model=""))
        with mock.patch.object(Q, "_report", side_effect=RuntimeError("no cli")):
            self.assertIsNone(Q.read("agy", "m", now=NOW))

    def test_the_time_reads_as_the_host_clock(self):
        self.assertEqual(Q.until_text(NOW + 60, now=NOW), time.strftime("%H:%M", time.localtime(NOW + 60)))
        self.assertEqual(Q.until_text(NOW + 3 * 86400, now=NOW), time.strftime("%m/%d %H:%M", time.localtime(NOW + 3 * 86400)))


class Alternatives(unittest.TestCase):
    """qfr/C: the brains offered when one is out of quota -- the provider's list order, without the held one, one
    recorded out of quota, or one with an empty window in the cached report."""
    def setUp(self):
        Q._STATE.clear()

    def test_other_usable_brains_in_the_provider_s_order(self):
        class A:
            def known_models(self):
                return ["claude-opus", "claude-sonnet", "gemini-high", "gemini-low", "gemini-mid"]

            def quota_view(self, m, rows):
                pct = 0 if m.startswith("claude") else 50
                return {"windows": [{"pct": pct, "reset_at": ISO(NOW + 600)}]}
        Q._STATE[("agy", "gemini-high")] = {"until": NOW + 600}
        with mock.patch("providers.adapters.get_adapter", return_value=A()), \
             mock.patch("route_accounts._get_usage", return_value={"ok": True, "rows": [{}]}):
            self.assertEqual(Q.alternatives("agy", "claude-opus", now=NOW), ["gemini-low", "gemini-mid"])
        with mock.patch("providers.adapters.get_adapter", side_effect=RuntimeError("x")):
            self.assertEqual(Q.alternatives("agy", "claude-opus", now=NOW), [])


PAGE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function quotaSwitchButtons');
function el(tag) { return { tag, children: [], listeners: {}, className: '', textContent: '', disabled: false, value: '',
  appendChild(c) { this.children.push(c); return c; }, addEventListener(k, f) { this.listeners[k] = f; },
  querySelectorAll() { return this.children; }, click() { clicks.push('send'); } }; }
const clicks = [], picked = [];
const input = el('textarea'), sendBtn = el('button');
const document = { createElement: el, getElementById: (id) => (id === 'input' ? input : id === 'send' ? sendBtn : null) };
function pickModel(m) { picked.push(m); }
function retryHint() { return 'held message'; }
const setTimeout = (f) => f();
eval(src.slice(a));
const node = el('div');
quotaSwitchButtons(node, ['gemini-low', 'gemini-mid', 'third']);
const labels = node.children.map(b => b.textContent);
node.children[0].listeners.click();
console.log(JSON.stringify({ labels, picked, clicks, disabled: node.children.map(b => b.disabled) }));
"""


class Page(unittest.TestCase):
    def test_a_button_switches_the_brain_and_sends_the_held_message(self):
        import json, shutil, subprocess
        from tests.page_source import i18n_prelude
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        static = ENGINE.parent / "static"
        p = subprocess.run([node, "-e", i18n_prelude() + PAGE, str(static / "app-retry.js")], capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        cat = json.loads((static / "i18n" / "ko.json").read_text(encoding="utf-8"))
        self.assertEqual(out["labels"], [cat["quota.switch_to"].replace("{model}", m) for m in ("gemini-low", "gemini-mid")])
        self.assertEqual((out["picked"], out["clicks"], out["disabled"]), (["gemini-low"], ["send"], [True, True]))
        sse = (static / "app-sse.js").read_text(encoding="utf-8")
        self.assertIn("if (nn && data.suggest && typeof quotaSwitchButtons === 'function') quotaSwitchButtons(nn, data.suggest);", sse)


class LowWarning(unittest.TestCase):
    """qfr/D: a brain at 10 % or less is said once in the talk (an event the page shows as a notice, no turn state)."""
    def setUp(self):
        Q._WARNED.clear()

    def low(self, *windows):
        with mock.patch.object(Q, "_report", return_value=view(*windows)):
            return Q.low("agy", "claude-opus-5-5-high", now=NOW)

    def test_the_lowest_window_at_ten_percent_or_less(self):
        hit = self.low(("5h", 8, ISO(NOW + 600)), ("week", 4, ISO(NOW + 9000)), ("x", 50, ISO(NOW + 60)))
        self.assertEqual((hit["window"], hit["pct"], hit["until"]), ("week", 4, NOW + 9000))
        self.assertIsNone(self.low(("5h", 0, ISO(NOW + 600)), ("week", 11, ISO(NOW + 600))), "0 % is out, not low")
        self.assertIsNone(self.low(("5h", 5, ISO(NOW - 1))), "a reset in the past says nothing")
        self.assertIsNone(self.low(("5h", None, ISO(NOW + 600))), "not a percentage")

    def test_it_is_said_once_per_window_and_reset(self):
        sess = type("S", (), {"provider": "agy", "model": "claude-opus-5-5-high", "events": []})()
        sess._emit = sess.events.append
        hit = {"provider": "agy", "model": "claude-opus-5-5-high", "scope": "Claude", "window": "5h", "pct": 8,
               "until": time.time() + 600, "reset_at": "R1"}
        with mock.patch.object(Q, "low", return_value=hit):
            Q._warn_low(sess)
            Q._warn_low(sess)
        with mock.patch.object(Q, "low", return_value=dict(hit, reset_at="R2")):
            Q._warn_low(sess)
        self.assertEqual([e["event"] for e in sess.events], ["notice", "notice"])
        self.assertEqual(sess.events[0]["key"], "srv.quota_low")
        self.assertEqual(sess.events[0]["vars"]["pct"], "8")   # i18n vars travel as text

    def test_a_finished_turn_asks_and_the_page_shows_it(self):
        src = (ENGINE / "session.py").read_text(encoding="utf-8")
        self.assertIn('if outcome == "result":\n            quota_state.warn_low(self)', src)
        self.assertFalse(Q.AUTO)   # the suite never reads a real account on its own
        sse = (ENGINE.parent / "static" / "app-sse.js").read_text(encoding="utf-8")
        self.assertIn("if (type === 'notice') { addNotice(data.notice || 'info', text, data.ts, true); return; }", sse)


class FakeReq:
    def __init__(self, text):
        self.arg, self.body, self.out = "w1", {"text": text}, None

    def json(self, obj, code=200):
        self.out = (code, obj)
        return self.out


class FakeSess:
    provider, model, character, is_private = "agy", "claude-opus-5-5-high", "", False

    def __init__(self):
        self.history, self.events, self.sent = [], [], []

    def maybe_swap_provider(self, _p):
        pass

    def maybe_swap_model(self, _m):
        pass

    def save_meta(self):
        pass

    def _emit(self, ev):
        self.events.append(ev)

    def send(self, *a, **k):
        self.sent.append(a)
        return False

    def to_public(self):
        return {"id": "w1"}


class SendRoute(unittest.TestCase):
    def setUp(self):
        Q._STATE.clear()

    def test_a_send_to_a_brain_out_of_quota_is_not_made(self):
        Q._STATE[("agy", "claude-opus-5-5-high")] = {"provider": "agy", "model": "claude-opus-5-5-high", "scope": "",
                                                     "window": "5h", "until": time.time() + 600}
        sess = FakeSess()
        with mock.patch.object(route_sessions.REG, "get", return_value=sess), \
             mock.patch.object(Q, "alternatives", return_value=["gemini-low"]):   # no real CLI from the suite
            req = FakeReq("hello")
            route_sessions.message(req)
        self.assertEqual(sess.sent, [], "nothing reaches the brain")
        self.assertTrue(req.out[1]["blocked"])
        self.assertEqual(sess.events[-1]["key"], "srv.quota_until")
        self.assertEqual(sess.history[-1]["key"], "srv.quota_until")
        self.assertEqual(sess.events[-1]["suggest"], ["gemini-low"])

    def test_a_failed_turn_reads_the_quota_once_and_a_test_run_never_does(self):
        self.assertFalse(Q.AUTO, "run-tests.sh sets CHATBOT_TEST_RUNNER: no real usage read from the suite")
        seen = []
        with mock.patch.object(Q, "AUTO", True), mock.patch.object(Q, "read", side_effect=lambda *a: seen.append(a)):
            Q.after_error("agy", "m")
            for th in __import__("threading").enumerate():
                if th.name == "quota-after-error":
                    th.join(5)
        self.assertEqual(seen, [("agy", "m", True)])
        src = (ENGINE / "providers" / "adapter_base.py").read_text(encoding="utf-8")
        self.assertIn('quota_state.after_error(getattr(session, "provider", "") or self.id', src)


if __name__ == "__main__":
    unittest.main()
