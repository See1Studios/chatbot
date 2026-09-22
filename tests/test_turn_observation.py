"""AgySession funnels every way a turn can end into one hook (docs/plans/recursive-self-evolution.md §4.6).
Run: python3 -m unittest tests.test_turn_observation  (from services/chatbot)

Real AgySession objects, temp data directory; no child process is ever started.
"""
import json
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import session  # noqa: E402


class FakeProc:
    def __init__(self):
        self.stdout = iter([])     # the child's output ended immediately
        self.stdin = None
        self.returncode = 1

    def poll(self):
        return self.returncode


class Base(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        (self.data / "sessions").mkdir()
        self.obs = self.data / "workspace" / "skill-observations"
        self.obs.mkdir(parents=True)
        self._orig = {k: getattr(session, k) for k in ("SESSIONS", "ROOT", "_record_live_pids", "DATA", "evolution")}
        session.SESSIONS = self.data / "sessions"
        session.ROOT = CODE
        session.DATA = self.data
        session._record_live_pids = lambda: None
        self._summary = session.AgySession.get_handover_summary
        session.AgySession.get_handover_summary = lambda self, *a, **k: ""
        self.s = self.session("obs-test", "claude")

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(session, k, v)
        session.AgySession.get_handover_summary = self._summary

    def session(self, sid, provider="agy"):
        s = session.AgySession(sid, provider=provider)
        self.drain(s)
        return s

    @staticmethod
    def drain(sess):
        out = []
        while True:
            try:
                out.append(sess.events.get_nowait())
            except queue.Empty:
                return out

    def say(self, text, sess=None, ts=None):
        sess = sess or self.s
        sess.history.append({"role": "user", "text": text, "ts": ts or (len(sess.history) + 1000.0)})
        sess.busy = True

    def rows(self):
        p = self.obs / "candidates.jsonl"
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def signals(self):
        return [r["signal"] for r in self.rows()]


class NormalEndTest(Base):
    def test_a_clean_turn_records_nothing_and_still_finishes(self):
        self.say("오늘 날씨 알려줘")
        self.s._handle_events([{"event": "result", "text": "맑음"}])
        self.assertFalse(self.s.busy)
        self.assertEqual(self.rows(), [])

    def test_a_correction_is_recorded_with_who_when_and_the_users_words(self):
        self.say("아니 그게 아니라 왜 안 돼?")
        self.s._handle_events([{"event": "result", "text": "미안"}])
        (row,) = self.rows()
        self.assertEqual((row["signal"], row["sid"], row["provider"]), ("correction", "obs-test", "claude"))
        self.assertIn("왜 안 돼", row["detail"]["user"])
        self.assertEqual(row["detail"]["outcome"], "result")

    def test_an_error_event_ends_the_turn_as_an_error(self):
        self.say("이거 해줘")
        self.s._handle_events([{"event": "error", "text": "boom"}])
        self.assertEqual(self.signals(), ["error"])

    def test_the_host_self_test_is_never_a_candidate(self):
        self.say("[doctor-probe] ping")
        self.s._handle_events([{"event": "error", "text": "boom"}])
        self.assertEqual(self.rows(), [])


class OtherEndsTest(Base):
    def test_the_child_dying_mid_turn(self):
        self.say("이거 해줘")
        proc = FakeProc()
        self.s.proc = proc
        self.s._read_stdout(proc)
        self.assertFalse(self.s.busy)
        self.assertEqual(self.signals(), ["process_died"])  # the error event it emits is not a second signal

    def test_a_child_that_was_already_replaced_is_not_a_death(self):
        self.say("이거 해줘")
        proc = FakeProc()
        self.s.proc = FakeProc()
        self.s._read_stdout(proc)
        self.assertEqual(self.rows(), [])

    def test_the_users_stop_button(self):
        self.say("이거 해줘")
        self.s.stop()
        self.assertEqual(self.signals(), ["stopped"])

    def test_stop_on_an_idle_session_or_without_notice_is_not_a_signal(self):
        self.s.stop()
        self.say("이거 해줘")
        self.s.stop(notify=False)  # provider swap, recycle: the host's own doing
        self.assertEqual(self.rows(), [])

    def test_interrupt_is_a_signal_but_steering_is_normal_use(self):
        self.say("이거 해줘")
        self.s.interrupt_current_turn(reason="steer")
        self.assertEqual(self.rows(), [])
        self.say("저거 해줘")
        self.s.interrupt_current_turn()
        self.assertEqual(self.signals(), ["interrupted"])

    def test_the_loop_guard_stopping_a_turn(self):
        self.say("이거 해줘")
        self.s._emit({"event": "stopped", "text": "같은 도구 호출이 반복돼 자동으로 중단했습니다냥"})
        self.s._loop_stopping = True
        self.s._auto_stop_worker()
        self.assertEqual(self.signals(), ["auto_stop"])

    def test_the_reaper_finding_a_dead_child(self):
        self.say("이거 해줘")
        self.s.proc = FakeProc()
        reg = SimpleNamespace(lock=threading.RLock(), sessions={self.s.sid: self.s})
        pool = SimpleNamespace(_lock=threading.Lock(), _proc=None)
        orig = (session.REG, session.STANDBY_POOL)
        session.REG, session.STANDBY_POOL = reg, pool
        try:
            session._reap_sessions()
        finally:
            session.REG, session.STANDBY_POOL = orig
        self.assertEqual(self.signals(), ["process_died"])

    def test_creating_a_successor_session_is_recorded_once(self):
        made = []
        fake = SimpleNamespace(create=lambda **kw: made.append(kw) or SimpleNamespace(sid="succ-1", _send_direct=lambda *a: None,
                                                                                       handoff_summary=""),
                               get=lambda sid: None)
        orig = session.REG
        session.REG = fake
        self.s._successor_usable = lambda sid: False
        try:
            self.s._rotate_to_fresh_session("안녕", reason="heavy")
        finally:
            session.REG = orig
        (row,) = self.rows()
        self.assertEqual((row["signal"], row["detail"]["outcome"]), ("rotation", "heavy"))


class OneRecordPerTurnTest(Base):
    def test_two_paths_ending_the_same_turn_record_it_once(self):
        self.say("왜 안 돼")
        self.s._handle_events([{"event": "result", "text": "x"}])
        self.s._finish_turn("process_died")
        self.assertEqual(self.signals(), ["correction"])

    def test_the_next_turn_is_judged_on_its_own(self):
        self.say("왜 안 돼")
        self.s._handle_events([{"event": "result", "text": "x"}])
        self.say("고마워")
        self.s._handle_events([{"event": "result", "text": "y"}])
        self.say("망가졌어")
        self.s._handle_events([{"event": "result", "text": "z"}])
        self.assertEqual(self.signals(), ["correction", "correction"])

    def test_marks_from_a_turn_that_never_reported_do_not_leak_into_the_next(self):
        self.say("이거 해줘")
        self.s._emit({"event": "error", "text": "boom"})   # e.g. a provider swap cleared the turn silently
        self.say("고마워")
        self.s._handle_events([{"event": "result", "text": "ok"}])
        self.assertEqual(self.rows(), [])


class NeverDisturbsATurnTest(Base):
    def test_no_observation_directory_means_nothing_is_written(self):
        import shutil
        shutil.rmtree(str(self.obs))
        self.say("왜 안 돼")
        self.s._handle_events([{"event": "result", "text": "x"}])
        self.assertFalse(self.obs.exists())
        self.assertFalse(self.s.busy)

    def test_a_missing_core_module_only_switches_observation_off(self):
        session.evolution = None
        self.say("왜 안 돼")
        self.s._handle_events([{"event": "error", "text": "x"}])
        self.s.stop()
        self.assertFalse(self.s.busy)
        self.assertEqual(self.rows(), [])

    def test_a_failing_recorder_does_not_break_the_turn(self):
        class Boom:
            @staticmethod
            def on_turn_end(*a, **k):
                raise RuntimeError("disk on fire")

            record_candidate = on_turn_end
        session.evolution = Boom
        self.say("왜 안 돼")
        self.s._handle_events([{"event": "result", "text": "x"}])
        self.assertFalse(self.s.busy)

    def test_a_session_built_without_init_still_emits(self):
        bare = session.AgySession.__new__(session.AgySession)  # some tests fake sessions this way
        bare.events = queue.Queue()
        bare.subscribers = []
        bare.lock = threading.RLock()
        bare.history = []
        bare.last_activity = 0
        bare.last_progress = ""
        bare.meta_path = self.data / "sessions" / "bare" / "meta.json"
        bare.sid = "bare"
        bare._emit({"event": "error", "text": "x"})
        self.assertEqual(bare.events.get_nowait()["event"], "error")


if __name__ == "__main__":
    unittest.main()
