#!/usr/bin/env python3
"""tools/worktree_runner.py lifecycle against a throwaway repo, a fake agent and a fake ticket-quick.

  python3 tests/test_worktree_runner.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import worktree_runner as wr

FAKE_TICKET = r'''
import json, sys
with open(sys.argv[1], "a") as f:
    f.write(json.dumps(sys.argv[2:]) + "\n")
if sys.argv[2] == "start":
    print("TICKET_ID=7")
    print("CLAIM_TOKEN=tok")
'''

SMOKE = '''import sys
from pathlib import Path
sys.exit(1 if "bad" in Path(__file__).resolve().parents[1].joinpath("a.txt").read_text() else 0)
'''


def sh(cwd: Path, *cmd: str) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), text=True).strip()


class WorktreeRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        (self.repo / "tests").mkdir(parents=True)
        (self.repo / "tests" / "smoke.py").write_text(SMOKE)
        (self.repo / "a.txt").write_text("one\n")
        (self.repo / "b.txt").write_text("b\n")
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        self.calls = base / "calls.jsonl"
        (base / "tq.py").write_text(FAKE_TICKET)
        self.saved = (wr.CHATBOT_REPO, wr.WORKTREE_BASE, wr.TICKET_QUICK, wr.DEFAULT_GATES, dict(wr.PROVIDERS))
        wr.CHATBOT_REPO, wr.WORKTREE_BASE = self.repo, base / "wt"
        wr.TICKET_QUICK = [sys.executable, str(base / "tq.py"), str(self.calls)]
        wr.DEFAULT_GATES = ["python3 tests/smoke.py"]

    def tearDown(self) -> None:
        wr.CHATBOT_REPO, wr.WORKTREE_BASE, wr.TICKET_QUICK, wr.DEFAULT_GATES, providers = self.saved
        wr.PROVIDERS.clear()
        wr.PROVIDERS.update(providers)
        self.tmp.cleanup()

    def run_with(self, script: str, paths: str = "a.txt") -> int:
        wr.PROVIDERS["fake"] = {"argv": ["sh", "-c", script], "actor": "fake-agent", "author": ("Fake", "fake@localhost")}
        return wr.main(["run", "--provider", "fake", "--title", "t", "--paths", paths, "--prompt", "p", "--timeout", "30"])

    def ticket_cmds(self) -> list:
        return [json.loads(line)[0] for line in self.calls.read_text().splitlines()]

    def last_fail(self) -> list:
        return [json.loads(line) for line in self.calls.read_text().splitlines()][-1]

    def assert_clean_up(self) -> None:
        self.assertFalse((wr.WORKTREE_BASE / "ticket-7").exists())
        self.assertEqual(sh(self.repo, "git", "branch", "--list", "worktree/*"), "")

    def test_passing_branch_is_merged_and_ticket_done(self) -> None:
        rc = self.run_with("echo two >> a.txt && git commit -qam change")
        self.assertEqual(rc, 0)
        self.assertEqual((self.repo / "a.txt").read_text(), "one\ntwo\n")
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%an"), "Fake")
        self.assertEqual(self.ticket_cmds(), ["start", "renew", "done"])
        self.assert_clean_up()

    def test_uncommitted_changes_are_committed_by_the_runner(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt"), 0)
        self.assertIn("left uncommitted", sh(self.repo, "git", "log", "-1", "--format=%s"))

    def test_change_outside_paths_fails_the_scope_gate(self) -> None:
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        self.assertEqual(self.run_with("echo x >> b.txt && git commit -qam change"), 1)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), head)
        self.assertEqual(self.ticket_cmds(), ["start", "fail"])
        self.assertIn("gate_failed", self.last_fail())
        self.assert_clean_up()

    def test_failing_smoke_blocks_the_merge(self) -> None:
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        self.assertEqual(self.run_with("echo bad >> a.txt && git commit -qam change"), 1)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), head)
        self.assertIn("gate_failed", self.last_fail())
        self.assert_clean_up()

    def test_no_change_and_agent_error_fail(self) -> None:
        self.assertEqual(self.run_with("true"), 1)
        self.assertIn("failed", self.last_fail())
        self.assertEqual(self.run_with("exit 3"), 1)
        self.assertIn("failed", self.last_fail())
        self.assert_clean_up()

    def test_main_that_moved_is_rebased_onto(self) -> None:
        script = ("echo two >> a.txt && git commit -qam change && "
                  "cd %s && echo c > c.txt && git add c.txt && git commit -qm main-moved" % self.repo)
        self.assertEqual(self.run_with(script), 0)
        self.assertEqual(sh(self.repo, "git", "log", "--format=%s", "-3").splitlines(),
                         ["change", "main-moved", "init"])

    def test_keep_retains_a_failed_worktree(self) -> None:
        wr.PROVIDERS["fake"] = {"argv": ["sh", "-c", "true"], "actor": "fake-agent", "author": ("Fake", "f@l")}
        wr.main(["run", "--provider", "fake", "--title", "t", "--paths", "a.txt", "--prompt", "p", "--keep"])
        self.assertTrue((wr.WORKTREE_BASE / "ticket-7").exists())
        # a leftover blocks the next run until cleanup
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam change"), 1)
        self.assertIn("left over", self.last_fail()[-3])
        wr.main(["cleanup", "--ticket", "7"])
        self.assert_clean_up()

    def test_refuses_a_timeout_beyond_the_lease(self) -> None:
        wr.PROVIDERS["fake"] = {"argv": ["true"], "actor": "fake-agent", "author": ("Fake", "f@l")}
        self.assertEqual(wr.main(["run", "--provider", "fake", "--title", "t", "--paths", "a.txt", "--prompt", "p",
                                  "--timeout", "99999"]), 2)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
