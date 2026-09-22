"""Server-side behaviour behind account rotation (quota ran out -> log in elsewhere):
the usage cache must follow the ACCOUNT, and auto-recycle must never touch a busy
session, an external process, or a pid it was not told about.
Run: python3 -m unittest tests.test_auto_recycle  (from services/chatbot)
"""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import session  # noqa: E402

A, B = "a@example.com", "b@example.com"


class FakeAdapter:
    def __init__(self):
        self.calls = 0

    def rate_limit_report(self):
        self.calls += 1
        return {"rows": [{"group": "g", "limit_type": "t", "remaining_pct": "50%", "reset_at": "x"}]}


class UsageCacheTest(unittest.TestCase):
    def setUp(self):
        self.email = A
        self.adapter = FakeAdapter()
        self.orig = (server.get_adapter, server.accounts.current_email)
        server.get_adapter = lambda p: self.adapter
        server.accounts.current_email = lambda p: self.email
        server._USAGE_CACHE.clear()

    def tearDown(self):
        server.get_adapter, server.accounts.current_email = self.orig
        server._USAGE_CACHE.clear()

    def test_same_account_is_served_from_cache(self):
        server._get_usage("agy"); server._get_usage("agy")
        self.assertEqual(self.adapter.calls, 1)

    def test_switching_account_drops_the_cached_report(self):
        first = server._get_usage("agy")
        self.email = B
        second = server._get_usage("agy")
        self.assertEqual(self.adapter.calls, 2)
        self.assertEqual((first["account"], second["account"]), (A, B))

    def test_unknown_account_never_invalidates(self):
        server._get_usage("agy")
        self.email = None            # logged out / unreadable / omniroute
        server._get_usage("agy")
        self.assertEqual(self.adapter.calls, 1)

    def test_force_still_refetches(self):
        server._get_usage("agy"); server._get_usage("agy", force=True)
        self.assertEqual(self.adapter.calls, 2)


def _fake_session(sid, pid, busy):
    s = SimpleNamespace(sid=sid, busy=busy, stopped=False,
                        proc=SimpleNamespace(pid=pid, poll=lambda: None))
    s.stop = lambda notify=True, s=s: setattr(s, "stopped", True)
    return s


class RecycleSafetyTest(unittest.TestCase):
    def setUp(self):
        self.idle, self.busy = _fake_session("idle", 10, False), _fake_session("busy", 11, True)
        self.standby_discarded = False
        pool = SimpleNamespace(_lock=threading.Lock(),
                               _proc=SimpleNamespace(pid=12, poll=lambda: None),
                               discard=lambda: setattr(self, "standby_discarded", True) or True)
        self.orig = (session.REG, session.STANDBY_POOL)
        session.REG = SimpleNamespace(lock=threading.RLock(), sessions={"idle": self.idle, "busy": self.busy})
        session.STANDBY_POOL = pool

    def tearDown(self):
        session.REG, session.STANDBY_POOL = self.orig

    def test_idle_and_standby_are_recycled_busy_is_never_touched(self):
        r = session.recycle_agents({10, 11, 12})
        self.assertEqual(sorted(r["recycled"]), [10, 12])
        self.assertEqual(r["skipped_busy"], [11])
        self.assertTrue(self.idle.stopped)
        self.assertFalse(self.busy.stopped)
        self.assertTrue(self.standby_discarded)

    def test_pids_it_does_not_own_are_ignored(self):
        r = session.recycle_agents({9999})   # e.g. an external SSH agy
        self.assertEqual(r, {"recycled": [], "skipped_busy": []})
        self.assertFalse(self.idle.stopped or self.busy.stopped or self.standby_discarded)


class AutoRecycleOnceTest(unittest.TestCase):
    def setUp(self):
        self.orig = (server.accounts.snapshot, server.owned_agent_procs, server.recycle_agents,
                     dict(server._AUTO_RECYCLE))
        self.recycled_with = []
        server.owned_agent_procs = lambda: {}
        server.recycle_agents = lambda pids: self.recycled_with.append(set(pids)) or \
            {"recycled": sorted(pids), "skipped_busy": []}
        server._AUTO_RECYCLE.update(last_at=None, last_count=0, total=0)

    def tearDown(self):
        server.accounts.snapshot, server.owned_agent_procs, server.recycle_agents = self.orig[:3]
        server._AUTO_RECYCLE.clear(); server._AUTO_RECYCLE.update(self.orig[3])

    def _snap(self, *procs):
        server.accounts.snapshot = lambda owned, providers=None: {"providers": {"agy": {"processes": list(procs)}}}

    def test_nothing_stale_does_nothing(self):
        self._snap({"pid": 1, "stale": False, "owner": "session"})
        self.assertEqual(server._auto_recycle_once(), 0)
        self.assertEqual(self.recycled_with, [])
        self.assertIsNone(server._AUTO_RECYCLE["last_at"])

    def test_stale_owned_is_recycled_and_recorded_external_is_not(self):
        self._snap({"pid": 1, "stale": True, "owner": "session"},
                   {"pid": 2, "stale": True, "owner": "standby"},
                   {"pid": 3, "stale": True, "owner": "external"})
        self.assertEqual(server._auto_recycle_once(), 2)
        self.assertEqual(self.recycled_with, [{1, 2}])
        self.assertEqual((server._AUTO_RECYCLE["last_count"], server._AUTO_RECYCLE["total"]), (2, 2))
        self.assertIsNotNone(server._AUTO_RECYCLE["last_at"])


if __name__ == "__main__":
    unittest.main()
