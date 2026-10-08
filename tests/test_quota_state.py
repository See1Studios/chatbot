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
        with mock.patch.object(route_sessions.REG, "get", return_value=sess):
            req = FakeReq("hello")
            route_sessions.message(req)
        self.assertEqual(sess.sent, [], "nothing reaches the brain")
        self.assertTrue(req.out[1]["blocked"])
        self.assertEqual(sess.events[-1]["key"], "srv.quota_until")
        self.assertEqual(sess.history[-1]["key"], "srv.quota_until")

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
