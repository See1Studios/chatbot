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


def _subscribe(sess):
    """Attach a fresh subscriber queue and return it."""
    q = queue.Queue()
    with sess.lock:
        sess.subscribers.append(q)
    return q


def drain(q):
    """Drain all currently available events from a queue."""
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


class SwapTest(unittest.TestCase):
    def setUp(self):
        self._sessions = session.SESSIONS
        session.SESSIONS = Path(tempfile.mkdtemp())
        self._summary = session.AgentSession.get_handover_summary
        session.AgentSession.get_handover_summary = lambda self, *a, **k: ""   # would spawn agy /compact
        self._dialogue = session.AgentSession._dialogue_summary_fallback
        session.AgentSession._dialogue_summary_fallback = lambda self, *a, **k: ""  # refine thread: no agy
        self.s = session.AgentSession("swap-test", provider="agy")
        self._q = _subscribe(self.s)
        drain(self._q)  # discard startup events

    def tearDown(self):
        session.SESSIONS = self._sessions
        session.AgentSession.get_handover_summary = self._summary
        session.AgentSession._dialogue_summary_fallback = self._dialogue

    def stopped(self):
        return [e for e in drain(self._q) if e.get("event") == "stopped"]

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


class AsyncHandoffTest(unittest.TestCase):
    """SWAP_ASYNC_HANDOFF_v1: a swap away from agy answers at once; /compact refines the handoff later."""

    def setUp(self):
        import threading
        import time
        self.time = time
        self._sessions, self._compact = session.SESSIONS, session.AgentSession._native_compact
        session.SESSIONS = Path(tempfile.mkdtemp())
        self.release = threading.Event()

        def slow_compact(provider, cid):
            self.release.wait(5)
            return "COMPACT-OF-" + cid if provider == "agy" else ""   # only a provider with a native compact
        session.AgentSession._native_compact = staticmethod(slow_compact)
        self._dialogue = session.AgentSession._dialogue_summary_fallback
        session.AgentSession._dialogue_summary_fallback = lambda self, *a, **k: "DIALOGUE-SUMMARY"  # never spawn agy
        self.s = session.AgentSession("async-swap", provider="agy")
        self.s.conversation_id = "old-cid"
        self.s.history = [{"role": "user", "text": "앞선 질문", "ts": 1}, {"role": "assistant", "text": "앞선 답", "ts": 2}]

    def tearDown(self):
        self.release.set()
        session.SESSIONS = self._sessions
        session.AgentSession._native_compact = self._compact
        session.AgentSession._dialogue_summary_fallback = self._dialogue

    def wait_refined(self, want):
        for _ in range(100):
            if want(self.s.handoff_summary):
                return True
            self.time.sleep(0.02)
        return False

    def test_the_swap_does_not_wait_for_compact_and_is_refined_after(self):
        t0 = self.time.monotonic()
        self.s.maybe_swap_provider("claude")
        self.assertLess(self.time.monotonic() - t0, 1.0)
        self.assertNotIn("COMPACT", self.s.handoff_summary)      # instant dialogue summary for now
        self.assertIn("앞선", self.s.handoff_summary)
        self.release.set()
        self.assertTrue(self.wait_refined(lambda h: "COMPACT-OF-old-cid" in h))
        self.assertIn("앞선 답", self.s.handoff_summary)          # last exchange still appended

    def test_a_second_swap_discards_the_first_refinement(self):
        self.s.maybe_swap_provider("claude")
        self.s.maybe_swap_provider("codex")                       # claude had no agy conversation
        self.assertTrue(self.wait_refined(lambda h: "DIALOGUE-SUMMARY" in h))  # the codex swap's own refine
        self.release.set()
        self.time.sleep(0.3)
        self.assertNotIn("COMPACT", self.s.handoff_summary)       # the stale agy one was dropped

    def test_a_handoff_already_sent_is_not_rewritten(self):
        self.s.maybe_swap_provider("claude")
        sent = self.s.handoff_summary
        self.s.handoff_injected = True                            # the next message already carried it
        self.release.set()
        self.time.sleep(0.3)
        self.assertEqual(self.s.handoff_summary, sent)



class EffortGoesWithTheBrain(SwapTest):
    """2026-09-30: grok's private default effort=low stayed after a swap to agy, and agy refused
    "--model gemini-3.8-flash-high --effort low"."""

    def test_a_provider_swap_clears_the_old_effort(self):
        self.s.provider, self.s.effort = "grok", "low"
        self.s.maybe_swap_provider("agy")
        self.assertEqual((self.s.provider, self.s.effort, self.s.model), ("agy", "", ""))

    def test_agy_sends_no_effort_when_the_model_name_carries_one(self):
        from providers.adapter_agy import AgyAdapter
        a = AgyAdapter()
        a.find_executable = lambda: "agy"
        self.assertNotIn("--effort", a.build_args("gemini-3.8-flash-high", "low", None, []))
        self.assertIn("--effort", a.build_args("gemini-plain", "low", None, []))


if __name__ == "__main__":
    unittest.main()
