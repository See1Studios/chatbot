"""GIT_AUTOCOMMIT_v2 (#571): a card save's auto-commit runs on its own thread, one at a time, and gives git time to
finish -- the commit hook runs the guard tests (~40 s), and the old 10 s timeout killed git mid-commit, leaving
.git/index.lock behind (2026-10-02 12:38). Nothing here touches a real repository: git is a recorder.
Run: python3 -m unittest tests.test_git_autocommit  (from services/chatbot)
"""
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import workspace_status as WS  # noqa: E402


class AutoCommit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.card = self.tmp / "card.json"
        self.card.write_text("{}", encoding="utf-8")
        self.calls, self.release = [], threading.Event()

    def fake_run(self, cmd, **kw):
        self.calls.append((cmd[1], kw.get("timeout"), threading.current_thread().name))
        if cmd[1] == "diff":
            return SimpleNamespace(returncode=1, stdout="", stderr="")       # something staged
        if cmd[1] == "commit":
            self.release.wait(5)                                              # the hook's tests, slow
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_the_save_does_not_wait_and_git_is_not_cut_short(self):
        with mock.patch.object(WS.subprocess, "run", side_effect=self.fake_run):
            t0 = time.monotonic()
            self.assertTrue(WS._maybe_git_commit(self.card, "chore(team): update card x"))
            self.assertLess(time.monotonic() - t0, 0.5, "the save answers at once")
            self.release.set()
            for t in threading.enumerate():
                if t.name == "git-autocommit":
                    t.join(5)
        commit = [c for c in self.calls if c[0] == "commit"][0]
        self.assertGreaterEqual(commit[1], 300, "time for the hook's guard tests; a kill leaves index.lock")
        self.assertEqual(commit[2], "git-autocommit")

    def test_commits_run_one_at_a_time(self):
        running, most = [0], [0]

        def run(cmd, **kw):
            if cmd[1] == "commit":
                running[0] += 1
                most[0] = max(most[0], running[0])
                time.sleep(0.05)
                running[0] -= 1
            return SimpleNamespace(returncode=1 if cmd[1] == "diff" else 0, stdout="", stderr="")
        with mock.patch.object(WS.subprocess, "run", side_effect=run):
            for _ in range(4):
                WS._maybe_git_commit(self.card, "chore(team): x")
            for t in threading.enumerate():
                if t.name == "git-autocommit":
                    t.join(5)
        self.assertEqual(most[0], 1)


if __name__ == "__main__":
    unittest.main()
