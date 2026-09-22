"""Swapping a session's provider/model is not a user-requested stop.
Run: python3 -m unittest tests.test_session_swap  (from services/chatbot)
"""
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session  # noqa: E402

OLD_NOTICE = "요청으로 작업이 중지되었습니다"


def drain(sess):
    out = []
    while True:
        try:
            out.append(sess.events.get_nowait())
        except queue.Empty:
            return out


class SwapTest(unittest.TestCase):
    def setUp(self):
        self._sessions = session.SESSIONS
        session.SESSIONS = Path(tempfile.mkdtemp())
        self._summary = session.AgySession.get_handover_summary
        session.AgySession.get_handover_summary = lambda self, *a, **k: ""   # would spawn agy /compact
        self.s = session.AgySession("swap-test", provider="agy")
        drain(self.s)

    def tearDown(self):
        session.SESSIONS = self._sessions
        session.AgySession.get_handover_summary = self._summary

    def stopped(self):
        return [e for e in drain(self.s) if e.get("event") == "stopped"]

    def test_idle_provider_and_model_swap_say_nothing(self):
        self.s.maybe_swap_provider("claude")
        self.s.maybe_swap_model("some-model")
        self.assertEqual(self.stopped(), [])
        self.assertEqual((self.s.provider, self.s.model), ("claude", "some-model"))

    def test_the_real_tray_click_no_longer_prints_two_stop_notices(self):
        # POST /provider carries both keys; it used to emit one "stopped" per swap = a pair
        self.s.maybe_swap_provider("codex")
        self.s.maybe_swap_model("gpt-x")
        self.assertEqual(len(self.stopped()), 0)

    def test_a_turn_in_flight_is_reported_once_and_accurately(self):
        self.s.busy = True
        self.s.maybe_swap_provider("claude")
        self.s.maybe_swap_model("some-model")            # busy is already cleared -> no second notice
        notices = self.stopped()
        self.assertEqual(len(notices), 1)
        self.assertIn("제공자를 바꿔서 진행 중이던 작업을 중단했습니다", notices[0]["text"])
        self.assertNotIn(OLD_NOTICE, notices[0]["text"])
        self.assertFalse(self.s.busy)

    def test_model_swap_while_busy_names_the_model(self):
        self.s.busy = True
        self.s.maybe_swap_model("other-model")
        self.assertIn("모델을 바꿔서", self.stopped()[0]["text"])

    def test_same_provider_and_model_do_nothing_at_all(self):
        self.s.proc = SimpleNamespace(poll=lambda: None, stdin=None, terminate=lambda: self.fail("must not stop"),
                                      wait=lambda **k: None, kill=lambda: None)
        self.s.maybe_swap_provider("agy")
        self.s.maybe_swap_model(self.s.model)
        self.assertEqual(self.stopped(), [])
        self.assertIsNotNone(self.s.proc)

    def test_an_explicit_user_stop_still_says_so(self):
        self.s.stop()
        notices = self.stopped()
        self.assertEqual(len(notices), 1)
        self.assertIn(OLD_NOTICE, notices[0]["text"])


if __name__ == "__main__":
    unittest.main()
