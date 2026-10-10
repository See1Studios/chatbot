"""GET /api/delegations must answer without waiting on git, and must not rebuild unchanged cards.
Run: engine/run-tests.sh test_delegation_list
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
os.environ.setdefault("CHATBOT_EDITION", "dev")
import delegation  # noqa: E402
import tickets  # noqa: E402
from tests.test_delegation import Base, TIER0  # noqa: E402

_DEV = mock.patch.object(__import__("mcp_server"), "EDITION", "dev")
setUpModule, tearDownModule = _DEV.start, _DEV.stop


class ListSpeedTest(Base):
    def setUp(self):
        super().setUp()
        self._clear_caches()

    def tearDown(self):
        self._wait_idle()
        self._clear_caches()
        super().tearDown()

    def _clear_caches(self):
        delegation._changed_cache.clear()
        delegation._changed_inflight.clear()
        delegation._runs_cache.update(stamp=None, rows=None)
        delegation._names_cache.update(key=None, at=0.0, names=None)

    def _wait_idle(self):
        deadline = time.monotonic() + 3
        while delegation._changed_inflight and time.monotonic() < deadline:
            time.sleep(0.01)

    def _blocking_git(self):
        gate = threading.Event()
        started = threading.Event()

        def git(wt, *args, timeout=10):
            started.set()
            self.assertTrue(gate.wait(5), "the test released git")
            if args and args[0] == "diff":
                return 0, "a.py\n", ""
            return 0, "b.py\n", ""

        return gate, started, git

    def test_a_poll_does_not_wait_for_git(self):
        tid = 926
        wt = delegation.runner().WORKTREE_BASE / ("ticket-%d" % tid)
        wt.mkdir(parents=True)
        gate, started, git = self._blocking_git()
        mod = delegation.runner()
        saved = mod.git
        mod.git = git
        try:
            t0 = time.monotonic()
            self.assertIsNone(delegation._files_changed(tid, "abc"))
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertTrue(started.wait(2))
            gate.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                hit = delegation._changed_cache.get(tid)
                if hit and hit[1] == 2:
                    break
                time.sleep(0.02)
            else:
                self.fail("the count never arrived: %r" % delegation._changed_cache.get(tid))
            self.assertEqual(delegation._files_changed(tid, "abc"), 2)
        finally:
            gate.set()
            mod.git = saved

    def test_a_stale_count_is_returned_while_git_runs(self):
        tid = 927
        wt = delegation.runner().WORKTREE_BASE / ("ticket-%d" % tid)
        wt.mkdir(parents=True)
        delegation._changed_cache[tid] = (time.monotonic() - delegation.CHANGED_TTL_SEC - 1, 1)
        gate, started, git = self._blocking_git()
        mod = delegation.runner()
        saved = mod.git
        mod.git = git
        try:
            t0 = time.monotonic()
            self.assertEqual(delegation._files_changed(tid, "abc"), 1)
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertTrue(started.wait(2))
            gate.set()
            self._wait_idle()
            self.assertEqual(delegation._changed_cache[tid][1], 2)
        finally:
            gate.set()
            mod.git = saved

    def test_a_missing_worktree_does_not_start_git(self):
        mod = delegation.runner()
        called = []
        saved = mod.git
        mod.git = lambda *a, **k: called.append(1) or (0, "", "")
        try:
            self.assertIsNone(delegation._files_changed(928, "abc"))
            self.assertEqual(called, [])
            self.assertNotIn(928, delegation._changed_cache)
        finally:
            mod.git = saved

    def test_names_are_reused_for_a_minute(self):
        with mock.patch.object(delegation, "experts", return_value=["dev"]):
            with mock.patch("identity.get_identity", return_value={"name": "N"}) as got:
                first = delegation.display_names()
                first["dev"] = "changed"
                second = delegation.display_names()
        self.assertEqual(got.call_count, 2)
        self.assertEqual(second, {"": "N", "dev": "N"})

    def test_unchanged_cards_skip_the_ticket_read(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        self.assertTrue(delegation.runs())
        with mock.patch.object(tickets, "get", wraps=tickets.get) as got:
            again = delegation.runs()
        self.assertEqual(got.call_count, 0)
        self.assertEqual(again[0]["ticket"], tid)
        again.clear()
        self.assertEqual(delegation.runs()[0]["ticket"], tid)

    def test_a_changed_card_is_read_again(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        delegation.runs()
        delegation.runner().write_state(tid, phase="done", head="abc")
        with mock.patch.object(tickets, "get", wraps=tickets.get) as got:
            card = [r for r in delegation.runs() if r["ticket"] == tid][0]
        self.assertGreater(got.call_count, 0)
        self.assertEqual(card["head"], "abc")


if __name__ == "__main__":
    unittest.main()
