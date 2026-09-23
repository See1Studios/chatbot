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

# argv: <calls log> <repo> <command> ...; writes the ticket record the way tickets.py would
FAKE_TICKET = r'''
import json, sys
from pathlib import Path
calls, repo, cmd = sys.argv[1], Path(sys.argv[2]), sys.argv[3:]
with open(calls, "a") as f:
    f.write(json.dumps(cmd) + "\n")
rec = repo / "data/workspace/skill-observations/tickets/0007.json"
rec.parent.mkdir(parents=True, exist_ok=True)
rec.write_text(json.dumps({"id": 7, "last": cmd[0]}))
if cmd[0] == "start":
    print("TICKET_ID=7")
    print("CLAIM_TOKEN=tok")
if cmd[0] == "merge-go":
    print("CLAIM_TOKEN=tok2")
'''

PASS = "printf 'VERDICT: PASS\\nSAY: fine'"
# FAIL the first time, PASS after that (a counter file next to the repo)
FAIL_ONCE = ("if [ -f ../../n ]; then printf 'VERDICT: PASS\\nSAY: better'; "
             "else touch ../../n; printf 'VERDICT: FAIL\\nSAY: sloppy\\nFIX: 1. add three'; fi")

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
        (self.repo / "protected_paths.json").write_text(json.dumps(
            {"protect": ["*.py", "tests/", "prot/", "sub/deep/"], "governance": ["gov.txt", "sub/rules.md"]}))
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        self.init = sh(self.repo, "git", "rev-parse", "HEAD")
        self.calls = base / "calls.jsonl"
        (base / "tq.py").write_text(FAKE_TICKET)
        self.base = base
        self.saved = (wr.CHATBOT_REPO, wr.WORKTREE_BASE, wr.TICKET_QUICK, wr.DEFAULT_GATES, dict(wr.PROVIDERS), wr.persona)
        wr.persona = lambda role="": {"name": "W" if not role else "R", "label": role or "writer", "voice": "", "body": ""}
        wr.CHATBOT_REPO, wr.WORKTREE_BASE = self.repo, base / "wt"
        wr.TICKET_QUICK = [sys.executable, str(base / "tq.py"), str(self.calls), str(self.repo)]
        wr.DEFAULT_GATES = ["python3 tests/smoke.py"]

    def tearDown(self) -> None:
        wr.CHATBOT_REPO, wr.WORKTREE_BASE, wr.TICKET_QUICK, wr.DEFAULT_GATES, providers, wr.persona = self.saved
        wr.PROVIDERS.clear()
        wr.PROVIDERS.update(providers)
        self.tmp.cleanup()

    def run_with(self, script: str, paths: str = "a.txt", review: str = PASS, extra: tuple = ()) -> int:
        wr.PROVIDERS["fake"] = {"argv": ["sh", "-c", script], "review_argv": ["sh", "-c", review], "model_flag": "-m",
                                "actor": "fake-agent", "author": ("Fake", "fake@localhost")}
        return wr.main(["run", "--provider", "fake", "--title", "t", "--paths", paths, "--prompt", "p",
                        "--timeout", "30", *extra])

    def code_head(self) -> str:
        """The last commit that is not a ticket record."""
        return sh(self.repo, "git", "log", "-1", "--format=%H", "--", ".", ":!data")

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
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--skip=1", "--format=%an"), "Fake")
        self.assertEqual(self.ticket_cmds(), ["start", "renew", "done"])
        self.assert_clean_up()
        # the ticket record is committed on its own; main is left clean
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "chore(tickets): close #7 -- t")
        self.assertEqual(sh(self.repo, "git", "show", "--name-only", "--format=", "HEAD"),
                         "data/workspace/skill-observations/tickets/0007.json")
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain"), "")

    def test_uncommitted_changes_are_committed_by_the_runner(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt"), 0)
        self.assertIn("left uncommitted", sh(self.repo, "git", "log", "-1", "--skip=1", "--format=%s"))

    def test_change_outside_paths_fails_the_scope_gate(self) -> None:
        self.assertEqual(self.run_with("echo x >> b.txt && git commit -qam change"), 1)
        self.assertEqual(self.code_head(), self.init)
        self.assertEqual(self.ticket_cmds()[-1], "fail")
        self.assertIn("gate_failed", self.last_fail())
        self.assert_clean_up()

    def test_failing_smoke_blocks_the_merge(self) -> None:
        self.assertEqual(self.run_with("echo bad >> a.txt && git commit -qam change"), 1)
        self.assertEqual(self.code_head(), self.init)
        self.assertIn("gate_failed", self.last_fail())
        self.assert_clean_up()

    def test_a_failed_attempt_commits_its_record_too(self) -> None:
        self.assertEqual(self.run_with("true"), 1)
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "chore(tickets): #7 failed -- t")
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain"), "")

    def test_only_the_record_is_committed(self) -> None:
        (self.repo / "b.txt").write_text("operator's own edit\n")
        sh(self.repo, "git", "add", "b.txt")
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c"), 0)
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain"), "M  b.txt")

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
        self.assertEqual(sh(self.repo, "git", "log", "--format=%s", "-4").splitlines(),
                         ["chore(tickets): close #7 -- t", "change", "main-moved", "init"])

    def test_keep_retains_a_failed_worktree(self) -> None:
        self.run_with("true", extra=("--keep",))
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

    def test_review_fail_sends_it_back_and_the_next_round_passes(self) -> None:
        # the writer logs each prompt it gets ($0) and adds a line per round
        script = 'printf "%s" "$0" > ../prompt-$(ls .. | wc -l); echo more >> a.txt; git commit -qam r; echo; echo ---; echo done'
        self.assertEqual(self.run_with(script, review=FAIL_ONCE), 0)
        self.assertEqual((self.repo / "a.txt").read_text(), "one\nmore\nmore\n")
        prompts = sorted(p for p in wr.WORKTREE_BASE.iterdir() if p.name.startswith("prompt-"))
        self.assertIn("1. add three", prompts[-1].read_text())
        self.assertIn("sloppy", prompts[-1].read_text())
        saved = sorted((wr.WORKTREE_BASE / "transcripts").glob("*.json"))
        lines = json.loads(saved[-1].read_text())
        self.assertEqual([(l["name"], l.get("verdict")) for l in lines],
                         [("W", None), ("R", "FAIL"), ("W", None), ("R", "PASS")])
        self.assertEqual(lines[0]["text"], "done")

    def test_review_fail_every_round_blocks_the_merge(self) -> None:
        fail = "printf 'VERDICT: FAIL\\nSAY: no\\nFIX: redo'"
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review=fail), 1)
        self.assertEqual(self.code_head(), self.init)
        self.assertIn("gate_failed", self.last_fail())
        self.assert_clean_up()

    def test_unreadable_review_fails_closed(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review="echo looks good",
                                       extra=("--rounds", "1")), 1)
        self.assertEqual(self.code_head(), self.init)

    def test_a_gate_failure_is_fixed_in_the_next_round(self) -> None:
        # round 1 writes "bad" (smoke fails), round 2 overwrites it
        script = 'if grep -q bad a.txt; then echo good > a.txt; else echo bad >> a.txt; fi; git commit -qam r'
        self.assertEqual(self.run_with(script), 0)
        self.assertEqual((self.repo / "a.txt").read_text(), "good\n")

    def test_no_review_merges_on_the_gates_alone(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review="exit 9",
                                       extra=("--no-review",)), 0)

    def test_parse_review(self) -> None:
        r = wr.parse_review("**VERDICT:** pass\nSAY: 흥, 봐준다\nFIX:\n")
        self.assertEqual((r["verdict"], r["say"]), ("PASS", "흥, 봐준다"))
        r = wr.parse_review("VERDICT: FAIL\nSAY: a\nb\nFIX: 1. x\n2. y")
        self.assertEqual((r["verdict"], r["say"], r["fix"]), ("FAIL", "a\nb", "1. x\n2. y"))
        self.assertEqual(wr.parse_review("PASS probably")["verdict"], "FAIL")

    def test_said_takes_the_line_after_the_last_rule(self) -> None:
        self.assertEqual(wr.said("work\n---\nnot this\n---\n다 했다냥!"), "다 했다냥!")
        self.assertEqual(wr.said("a\nb\nc"), "b\nc")

    # ---- Tier 2: stop before merge, land on the operator's word

    def waiting(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam change", extra=("--stop-before-merge",)), 0)

    def test_stop_before_merge_leaves_main_alone_and_waits(self) -> None:
        self.waiting()
        self.assertEqual(self.code_head(), self.init)
        self.assertEqual(self.ticket_cmds(), ["start", "renew", "await-merge"])
        self.assertTrue((wr.WORKTREE_BASE / "ticket-7").exists())
        self.assertIn("worktree/ticket-7", sh(self.repo, "git", "branch", "--list", "worktree/*"))
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "chore(tickets): #7 awaiting_merge -- t")
        self.assertEqual(wr.read_state(7)["phase"], "awaiting_merge")
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain"), "")

    def test_merge_lands_the_waiting_branch(self) -> None:
        self.waiting()
        self.assertEqual(wr.main(["merge", "--ticket", "7"]), 0)
        self.assertEqual((self.repo / "a.txt").read_text(), "one\ntwo\n")
        self.assertEqual(self.ticket_cmds()[-2:], ["merge-go", "done"])
        self.assertEqual(self.last_fail()[self.last_fail().index("--token") + 1], "tok2")
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "chore(tickets): close #7 -- t")
        self.assertEqual(wr.read_state(7)["phase"], "done")
        self.assert_clean_up()

    def test_merge_with_a_relayed_token_skips_merge_go(self) -> None:
        self.waiting()
        self.assertEqual(wr.main(["merge", "--ticket", "7", "--token", "ui-token"]), 0)
        self.assertNotIn("merge-go", self.ticket_cmds())

    def test_merge_after_main_moved_rebases_and_rechecks(self) -> None:
        self.waiting()
        (self.repo / "c.txt").write_text("c\n")
        sh(self.repo, "git", "add", "c.txt")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "main-moved")
        self.assertEqual(wr.main(["merge", "--ticket", "7"]), 0)
        self.assertEqual(sh(self.repo, "git", "log", "--format=%s", "-3").splitlines()[1:],
                         ["change", "main-moved"])

    def test_merge_that_no_longer_fits_fails_and_cleans_up(self) -> None:
        self.waiting()
        (self.repo / "a.txt").write_text("conflict\n")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "main-moved")
        self.assertEqual(wr.main(["merge", "--ticket", "7"]), 1)
        self.assertEqual((self.repo / "a.txt").read_text(), "conflict\n")
        self.assertEqual(self.ticket_cmds()[-1], "fail")
        self.assertIn("gate_failed", self.last_fail())
        self.assert_clean_up()

    def test_merge_without_a_waiting_run_is_refused(self) -> None:
        self.assertEqual(wr.main(["merge", "--ticket", "7"]), 2)
        self.run_with("echo two >> a.txt && git commit -qam change")   # merged directly, nothing waits
        self.assertEqual(wr.main(["merge", "--ticket", "7"]), 2)

    # ---- tiers (protected_paths.json of the repo worked on)

    def test_tier_3_paths_are_refused_before_a_ticket(self) -> None:
        for paths in ("gov.txt", "a.txt,gov.txt", "tests/", "tests/smoke.py"):
            self.assertEqual(self.run_with("true", paths=paths), 2, paths)
        self.assertFalse(self.calls.exists())

    def test_a_tier_3_file_slipped_in_under_a_directory_fails(self) -> None:
        rc = self.run_with("mkdir -p sub && echo x > sub/rules.md && git add sub && git commit -qm c", paths="sub/",
                           extra=("--rounds", "1"))
        self.assertEqual(rc, 1)
        self.assertFalse((self.repo / "sub" / "rules.md").exists())
        self.assertIn("gate_failed", self.last_fail())
        self.assertIn("Tier 3", self.last_fail()[self.last_fail().index("--note") + 1])

    def test_tier_2_paths_wait_for_the_operator(self) -> None:
        rc = self.run_with("mkdir -p prot && echo x > prot/x.txt && git add prot && git commit -qm c", paths="prot/")
        self.assertEqual(rc, 0)
        self.assertEqual(self.ticket_cmds()[-1], "await-merge")
        self.assertFalse((self.repo / "prot").exists())
        self.assertEqual(wr.read_state(7)["phase"], "awaiting_merge")

    def test_a_tier_2_file_found_in_the_change_also_waits(self) -> None:
        rc = self.run_with("mkdir -p sub/deep && echo x > sub/deep/x.txt && git add sub && git commit -qm c",
                           paths="sub/")
        self.assertEqual(rc, 0)
        self.assertEqual(self.ticket_cmds()[-1], "await-merge")

    def test_without_a_registry_nothing_is_delegated(self) -> None:
        (self.repo / "protected_paths.json").unlink()
        self.assertEqual(self.run_with("true"), 2)


if __name__ == "__main__":
    unittest.main()
