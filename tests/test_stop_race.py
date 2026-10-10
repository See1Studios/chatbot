"""#843: a stop() that lands while a turn is being prepared (a slow standby agent, the repair probe giving up after
8 s) clears proc first; the turn then ends quietly instead of writing to no process (AttributeError on proc.stdin).
Run: engine/run-tests.sh test_stop_race
"""
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import session as S  # noqa: E402


class FakeProc:
    def __init__(self):
        self.stdin = io.StringIO()


class StopRace(unittest.TestCase):
    def setUp(self):
        self._sessions = S.SESSIONS   # a fixture sessions dir, never the live one
        S.SESSIONS = Path(tempfile.mkdtemp()) / "sessions"
        S.SESSIONS.mkdir()
        self.s = s = S.AgentSession("20260101-000000-stoprc")
        s.provider, s.model, s.mode = "agy", "m", "work"
        s.handoff_summary = ""
        s.adapter = mock.MagicMock(keeps_stdin_open=True, transport_kind="process")
        s.adapter.format_stdin.side_effect = lambda c: c
        s.adapter.turn_context.return_value = ""
        self.proc = FakeProc()

        def ensure(t_enter):
            s.proc = self.proc
            return 0
        s._ensure_timed = ensure
        s._context_lore = lambda text: ""
        self.events = []
        patcher = mock.patch("session_turn.obslog.event", lambda evt, **kw: self.events.append((evt, kw.get("reason"))))
        patcher.start()
        self.addCleanup(patcher.stop)
        helper = mock.patch("session_turn._s")
        m = helper.start().return_value
        self.addCleanup(helper.stop)
        m.boot_notice.return_value = ""
        m.format_client_context.return_value = ""

    def tearDown(self):
        shutil.rmtree(str(S.SESSIONS.parent), ignore_errors=True)
        S.SESSIONS = self._sessions

    def test_a_stop_during_preparation_wins_and_nothing_is_written(self):
        def stopped_meanwhile():   # stop() clears proc before it takes the lock
            self.s.proc = None
            return ""
        self.s._context_prefix = stopped_meanwhile
        self.s._start_turn("hello", "", None, False, "chat")   # no AttributeError
        self.assertFalse(self.s.busy)
        self.assertEqual(self.proc.stdin.getvalue(), "")
        self.assertIn(("turn.dropped", "stopped_before_send"), self.events)

    def test_without_a_stop_the_turn_is_written(self):
        self.s._context_prefix = lambda: ""
        self.s._start_turn("hello", "", None, False, "chat")
        self.assertTrue(self.s.busy)
        self.assertIn("hello", self.proc.stdin.getvalue())
        self.s.busy = False
        self.s._cancel_silent_hang()

    def test_a_pipe_closed_by_a_stop_is_the_same_race(self):
        self.s.proc = proc = FakeProc()
        proc.stdin.close()            # write -> ValueError, as on a terminated process

        def stop_after_check(payload):
            self.s._stop_requested = True
            return payload
        self.s.adapter.format_stdin.side_effect = stop_after_check
        self.assertFalse(self.s._write_turn(self.s.adapter.format_stdin("x")))
        self.assertFalse(self.s.busy)
        self.s._stop_requested = False
        with self.assertRaises(ValueError):   # a closed pipe with no stop is a real failure: not hidden
            self.s._write_turn("x")

    def _one_shot(self):
        self.s.adapter.keeps_stdin_open = False
        self.s.adapter.close_stdin_after_prompt = False
        self.s._context_prefix = lambda: ""
        self.s._spawn = lambda prompt: setattr(self.s, "proc", self.proc)

    def test_a_one_shot_stop_before_stdin_drops_the_turn(self):
        self._one_shot()

        def clear_proc(content):
            self.s.proc = None
            return content

        self.s.adapter.format_stdin.side_effect = clear_proc
        self.s._start_turn("hello", "", None, False, "chat")
        self.assertFalse(self.s.busy)
        self.assertEqual(self.proc.stdin.getvalue(), "")
        self.assertIn(("turn.dropped", "stopped_before_send"), self.events)

    def test_a_one_shot_with_nothing_on_stdin_stays_busy(self):
        self._one_shot()
        self.s.adapter.format_stdin.side_effect = lambda content: ""
        self.s._start_turn("hello", "", None, False, "chat")
        self.assertTrue(self.s.busy)
        self.assertEqual(self.proc.stdin.getvalue(), "")
        self.assertNotIn("turn.dropped", [evt for evt, _reason in self.events])
        self.s.busy = False
        self.s._cancel_silent_hang()

    def test_a_one_shot_prompt_is_written_and_stdin_closed(self):
        class Remembering(io.StringIO):
            def close(self):
                self.written = self.getvalue()
                super().close()

        self.proc.stdin = Remembering()
        self._one_shot()
        self.s.adapter.close_stdin_after_prompt = True
        self.s._start_turn("hello", "", None, False, "chat")
        self.assertTrue(self.s.busy)
        self.assertIn("hello", self.proc.stdin.written)
        self.assertTrue(self.proc.stdin.closed)
        self.s.busy = False
        self.s._cancel_silent_hang()


if __name__ == "__main__":
    unittest.main()
