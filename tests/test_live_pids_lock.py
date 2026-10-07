"""LOCK_ORDER_v1: recording live agent pids never takes another session's lock. Two sessions spawning at once each held
their own lock and waited for the other's in _record_live_pids; the handoff pass and the reaper then stopped behind
them (drill restart under load, 2026-10-06).
Run: ./run-tests.sh test_live_pids_lock
"""
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import session  # noqa: E402


class Proc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


def fake(pid):
    return types.SimpleNamespace(lock=threading.RLock(), proc=Proc(pid))


class LivePids(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a, self.b = fake(101), fake(202)
        self.patches = [mock.patch.object(session, "DATA", Path(self.tmp.name)),
                        mock.patch.object(session.REG, "sessions", {"a": self.a, "b": self.b}),
                        mock.patch.object(session.STANDBY_POOL, "_proc", None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def spawn_in(self, sess, both, done):
        with sess.lock:   # what ensure() -> _spawn() holds when it records the pids
            both.wait(2)
            session._record_live_pids()
            done.append(sess)

    def test_two_sessions_spawning_at_once_both_finish(self):
        both, done = threading.Barrier(2), []
        threads = [threading.Thread(target=self.spawn_in, args=(s, both, done), daemon=True) for s in (self.a, self.b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual(len(done), 2, "a session waited on the other's lock: the spawns deadlocked")

    def test_a_session_whose_lock_is_held_still_counts(self):
        held, release = threading.Event(), threading.Event()

        def hold():
            with self.b.lock:
                held.set()
                release.wait(5)

        threading.Thread(target=hold, daemon=True).start()
        held.wait(2)
        try:
            session._record_live_pids()
        finally:
            release.set()
        self.assertEqual(sorted(json.loads((Path(self.tmp.name) / "live_pids.json").read_text())), [101, 202])


if __name__ == "__main__":
    unittest.main()
