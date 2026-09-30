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
from tests._platform import dev_only_bash  # noqa: E402

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
# FAIL the first time, PASS after that (a counter file; the test puts in its absolute path -- reviewers run in an empty room)
FAIL_ONCE = ("if [ -f ../../n ]; then printf 'VERDICT: PASS\\nSAY: better'; "
             "else touch ../../n; printf 'VERDICT: FAIL\\nSAY: sloppy\\nFIX: 1. add three'; fi")

SMOKE = '''import sys
from pathlib import Path
sys.exit(1 if "bad" in Path(__file__).resolve().parents[1].joinpath("a.txt").read_text() else 0)
'''


def sh(cwd: Path, *cmd: str) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), text=True).strip()


@dev_only_bash
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
        self.saved = (wr.CHATBOT_REPO, wr.WORKTREE_BASE, wr.TICKET_QUICK, wr.DEFAULT_GATES, dict(wr.PROVIDERS), wr.persona,
                      wr.workspace_dir)
        self.ws = base / "ws"                       # characters/<id>/ and pd-brain.json for this test
        wr.workspace_dir = lambda: self.ws
        wr.persona = lambda role="": {"name": "S" if role == "staff" else "P", "label": role or "pd", "voice": "", "body": ""}
        wr.CHATBOT_REPO, wr.WORKTREE_BASE = self.repo, base / "wt"
        wr.TICKET_QUICK = [sys.executable, str(base / "tq.py"), str(self.calls), str(self.repo)]
        wr.DEFAULT_GATES = ["python3 tests/smoke.py"]

    def tearDown(self) -> None:
        (wr.CHATBOT_REPO, wr.WORKTREE_BASE, wr.TICKET_QUICK, wr.DEFAULT_GATES, providers, wr.persona,
         wr.workspace_dir) = self.saved
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

    def test_a_timeout_says_so(self) -> None:
        # DELEGATION_CLARITY_v1: not "exited with -1"
        self.assertEqual(self.run_with("sleep 5", extra=("--timeout", "1")), 1)
        self.assertIn("timed out after 1s", " ".join(map(str, self.last_fail())))
        self.assert_clean_up()

    def test_when_no_brain_can_work_the_attempt_is_not_counted(self) -> None:
        # DELEGATION_HARDENING_v1: the last brain out of quota releases as `unavailable`, not `failed`
        self.assertEqual(self.run_with("echo 'Error: quota exceeded' >&2; exit 1"), 1)
        self.assertIn("unavailable", self.last_fail())
        self.assert_clean_up()

    def test_a_stdin_cli_gets_the_whole_instruction(self) -> None:
        long = "x" * 3000 + " THE-END"
        wr.PROVIDERS["fake"] = {"argv": ["sh", "-c", "cat > ../prompt.txt; echo two >> a.txt; git commit -qam c"],
                                "stdin_prompt": [], "review_argv": ["sh", "-c", PASS], "model_flag": "-m",
                                "actor": "fake-agent", "author": ("Fake", "fake@localhost")}
        self.assertEqual(wr.main(["run", "--provider", "fake", "--title", "t", "--paths", "a.txt", "--prompt", long,
                                  "--timeout", "30"]), 0)
        self.assertIn("THE-END", (wr.WORKTREE_BASE / "prompt.txt").read_text())

    def test_a_worker_asking_for_more_files_pauses_and_keeps_the_work(self) -> None:
        # NEED_PATH_v1: the attempt is released as `paused`, the branch kept, the request recorded
        script = "echo two >> a.txt && git commit -qam part; echo 'NEED_PATH: b.txt -- the helper lives there'"
        self.assertEqual(self.run_with(script), 1)
        self.assertIn("paused", self.last_fail())
        st = wr.read_state(7)
        self.assertEqual(st["phase"], "paused")
        self.assertEqual(st["need_paths"], [{"path": "b.txt", "why": "the helper lives there"}])
        self.assertTrue((wr.WORKTREE_BASE / "ticket-7").exists())            # the work waits for the operator
        self.assertEqual(wr.need_paths("NEED_PATH: a.txt -- in scope\nNEED_PATH: /etc/x\n", ["a.txt"]), [])

    def test_main_that_moved_is_rebased_onto(self) -> None:
        script = ("echo two >> a.txt && git commit -qam change && "
                  "cd %s && echo c > c.txt && git add c.txt && git commit -qm main-moved" % self.repo)
        self.assertEqual(self.run_with(script), 0)
        self.assertEqual(sh(self.repo, "git", "log", "--format=%s", "-4").splitlines(),
                         ["chore(tickets): close #7 -- t", "change", "main-moved", "init"])

    def test_a_failed_attempt_keeps_its_head_in_the_attic(self) -> None:
        fail = "printf 'VERDICT: FAIL\\nSAY: no\\nFIX: 1. more'"
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam part", review=fail), 1)
        self.assertIn("gate_failed", self.last_fail())
        self.assert_clean_up()
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s", wr.attic_ref(7)), "part")

    def test_from_attic_goes_on_from_the_kept_work_and_drops_it_on_merge(self) -> None:
        fail = "printf 'VERDICT: FAIL\\nSAY: no\\nFIX: 1. more'"
        self.run_with("echo two >> a.txt && git commit -qam part", review=fail, extra=("--rounds", "1"))
        sh(self.repo, "sh", "-c", "echo c > c.txt && git add c.txt && git -c user.name=t -c user.email=t@t "
                                  "commit -qm main-moved")
        rc = self.run_with("echo three >> a.txt && git commit -qam more",
                           extra=("--ticket", "7", "--token", "tok", "--from-attic"))
        self.assertEqual(rc, 0)
        self.assertEqual((self.repo / "a.txt").read_text(), "one\ntwo\nthree\n")
        self.assertEqual(wr.read_state(7)["pending_base"], self.init)       # the review diff covers "part" too
        self.assertNotEqual(subprocess.call(["git", "rev-parse", "--verify", "--quiet", wr.attic_ref(7)],
                                            cwd=str(self.repo), stdout=subprocess.DEVNULL), 0)

    def test_from_attic_without_one_fails(self) -> None:
        self.assertEqual(self.run_with("true", extra=("--ticket", "7", "--token", "tok", "--from-attic")), 1)
        self.assertIn("no refs/attic/ticket-7", " ".join(map(str, self.last_fail())))

    def test_reads_reach_the_worker_but_not_the_scope(self) -> None:
        wr.write_state(7, plan={"tasks": [{"role": "staff", "title": "t", "instruction": "i", "paths": ["a.txt"],
                                           "reads": ["b.txt", "a.txt"]}]})
        rc = self.run_with("cat > /dev/null; echo two >> a.txt && git commit -qam c",
                           extra=("--ticket", "7", "--token", "tok", "--plan-from-state"))
        self.assertEqual(rc, 0)
        tasks = wr.plan_tasks(type("A", (), {"resume": False, "plan_from_state": True, "title": "t"})(),
                              wr.read_state(7), ["a.txt"])
        self.assertEqual(tasks[0]["reads"], ["b.txt"])
        prompt = wr.writer_prompt(7, "t", "b", self.base, ["a.txt"], [], "i", "", reads=["b.txt"])
        self.assertIn("reference only; do not change them: b.txt", prompt)

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
        self.character("staff")             # an expert besides the default character: the task goes to it
        self.assertEqual(self.run_with(script, review=FAIL_ONCE.replace("../../n", str(self.base / "n"))), 0)
        self.assertEqual((self.repo / "a.txt").read_text(), "one\nmore\nmore\n")
        prompts = sorted(p for p in wr.WORKTREE_BASE.iterdir() if p.name.startswith("prompt-"))
        self.assertIn("1. add three", prompts[-1].read_text())
        self.assertIn("your producer (PD)", prompts[0].read_text())      # the staff character works for the PD
        self.assertIn("sloppy", prompts[-1].read_text())
        saved = sorted((wr.WORKTREE_BASE / "transcripts").glob("*.json"))
        lines = json.loads(saved[-1].read_text())
        self.assertEqual([(l["name"], l.get("verdict")) for l in lines],
                         [("S", None), ("P", "FAIL"), ("S", None), ("P", "PASS")])
        self.assertEqual(lines[0]["text"], "done")

    def test_review_fail_every_round_blocks_the_merge(self) -> None:
        fail = "printf 'VERDICT: FAIL\\nSAY: no\\nFIX: redo'"
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review=fail), 1)
        self.assertEqual(self.code_head(), self.init)
        self.assertIn("gate_failed", self.last_fail())
        self.assert_clean_up()

    def test_a_doc_task_waits_for_the_operator_with_the_review_as_advice(self) -> None:
        # DOC_LANE_v1: #443 failed a nearly finished plan on its review limit
        (self.repo / "plan.md").write_text("# plan\n")
        sh(self.repo, "git", "add", "plan.md")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "plan")
        seen = self.base / "review-prompt.txt"
        fail = "printf '%%s' \"$0\" > %s; printf 'VERDICT: FAIL\\nSAY: no\\nFIX: 1. keep the table'" % seen
        rc = self.run_with("echo more >> plan.md && git commit -qam doc", paths="plan.md", review=fail,
                           extra=("--stop-before-merge",))
        self.assertEqual(rc, 0)
        self.assertEqual(self.ticket_cmds()[-1], "await-merge")                 # the operator decides
        st = wr.read_state(7)
        self.assertIn("doc review FAIL", st["doc_advice"])
        self.assertIn("keep the table", st["doc_advice"])
        self.assertIn("This is a documentation change", seen.read_text())

    def test_a_code_task_still_fails_on_its_review(self) -> None:
        fail = "printf 'VERDICT: FAIL\\nSAY: no\\nFIX: redo'"
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review=fail,
                                       extra=("--stop-before-merge",)), 1)
        self.assertIn("gate_failed", self.last_fail())

    def test_doc_lane_parts(self) -> None:
        self.assertTrue(wr.is_doc_task(["docs/a.md", "b.md"], 0))
        self.assertFalse(wr.is_doc_task(["docs/a.md", "x.py"], 0))
        self.assertFalse(wr.is_doc_task(["AGENTS.md"], 3))
        diff = "--- a/p.md\n+++ b/p.md\n" + "-old\n" * 25 + "+new\n"
        self.assertEqual(wr.deleted_lines(diff), 25)
        base = "intro\nAs the producer, confirm the work: ..."
        self.assertIn("deletes 25 lines", wr.doc_review_prompt(base, diff))
        self.assertNotIn("WARNING", wr.doc_review_prompt(base, "-a\n+b\n"))

    def test_unreadable_review_fails_closed(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review="echo looks good",
                                       extra=("--rounds", "1")), 1)
        self.assertEqual(self.code_head(), self.init)

    def test_a_gate_failure_is_fixed_in_the_next_round(self) -> None:
        # round 1 writes "bad" (smoke fails), round 2 overwrites it
        script = 'if grep -q bad a.txt; then echo good > a.txt; else echo bad >> a.txt; fi; git commit -qam r'
        self.assertEqual(self.run_with(script), 0)
        self.assertEqual((self.repo / "a.txt").read_text(), "good\n")

    def test_guard_and_related_gates_come_from_run_tests_sh(self) -> None:
        # pew/F: guard files are named as paths (protected by gate_files); related tests are not (a task may edit them)
        (self.repo / "tests").mkdir(exist_ok=True)
        for name in ("test_guard", "test_widget"):
            (self.repo / "tests" / (name + ".py")).write_text("", encoding="utf-8")
        (self.repo / "run-tests.sh").write_text("FAST=(\n  test_guard\n  test_missing\n)\n", encoding="utf-8")
        guard = wr.guard_gate(self.repo)
        self.assertEqual(guard, "./run-tests.sh tests/test_guard.py")
        self.assertIn("tests/test_guard.py", wr.gate_files(self.repo, [guard]))
        related = wr.related_gate(self.repo, ["widget.py", "none.py"])
        self.assertEqual(related, "./run-tests.sh test_widget")
        self.assertEqual(wr.gate_files(self.repo, [related]), ["run-tests.sh"])
        self.assertIsNone(wr.related_gate(self.repo, ["tests/test_guard.py"]))   # a guard already runs in DEFAULT_GATES
        # the runner itself is a pass condition: a worker must not be able to edit it (tier 3)
        self.assertEqual(wr.tier_of(self.repo, "run-tests.sh", wr.gate_files(self.repo, [guard]))[0], 3)

    def test_related_tests_include_importers_and_mentions(self) -> None:
        # pew/P: a config change must pull in the tests that read it (protected_paths.json -> test_lifecycle, 2026-09-28)
        t = self.repo / "tests"
        t.mkdir(exist_ok=True)
        (t / "test_reads_cfg.py").write_text('CFG = "registry.json"\n', encoding="utf-8")
        (t / "test_imports.py").write_text("import helper_mod\n", encoding="utf-8")
        (t / "test_from_pkg.py").write_text("from providers import helper_mod\n", encoding="utf-8")
        (t / "test_word_only.py").write_text("# helper_mod is discussed here but not used\n", encoding="utf-8")
        (t / "test_page.py").write_text("from tests.page_source import app_bundle\n", encoding="utf-8")
        self.assertEqual(wr.related_gate(self.repo, ["registry.json"]), "./run-tests.sh test_reads_cfg")
        self.assertEqual(wr.related_gate(self.repo, ["providers/helper_mod.py"]), "./run-tests.sh test_from_pkg test_imports")
        self.assertEqual(wr.related_gate(self.repo, ["static/app-x.js"]), "./run-tests.sh test_page")

    def test_no_review_merges_on_the_gates_alone(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review="exit 9",
                                       extra=("--no-review",)), 0)

    def test_parse_review(self) -> None:
        r = wr.parse_review("**VERDICT:** pass\nSAY: 흥, 봐준다\nFIX:\n")
        self.assertEqual((r["verdict"], r["say"]), ("PASS", "흥, 봐준다"))
        r = wr.parse_review("VERDICT: FAIL\nSAY: a\nb\nFIX: 1. x\n2. y")
        self.assertEqual((r["verdict"], r["say"], r["fix"]), ("FAIL", "a\nb", "1. x\n2. y"))
        self.assertEqual(wr.parse_review("PASS probably")["verdict"], "FAIL")
        r = wr.parse_review("VERDICT: PASS\n\n흥, 이번엔 봐준다거든!\n")      # no SAY label
        self.assertEqual((r["verdict"], r["say"]), ("PASS", "흥, 이번엔 봐준다거든!"))
        r = wr.parse_review("VERDICT: FAIL\n**다시 해.**\nFIX: 1. x")
        self.assertEqual((r["say"], r["fix"]), ("다시 해.", "1. x"))
        self.assertIn("VERDICT: FAIL", r["raw"])

    def test_said_takes_the_line_after_the_last_rule(self) -> None:
        self.assertEqual(wr.said("work\n---\nnot this\n---\n다 했다냥!"), "다 했다냥!")
        self.assertEqual(wr.said("a\nb\nc"), "b\nc")

    def test_report_reaches_the_reviewer(self) -> None:
        out = "| case | old |\n|---|---|\n| x | fail |\nLEARNED: skip me\n---\n다 적어 왔거든?"
        self.assertEqual(wr.report(out), "| case | old |\n|---|---|\n| x | fail |")
        self.assertEqual(wr.report("a" * 10, limit=4), "…aaaa")
        p = wr.review_prompt(1, "t", "do it", "다 했다냥", "", None, "PD", partner_report="the table")
        self.assertIn("the table", p)
        self.assertNotIn("report (their", wr.review_prompt(1, "t", "do it", "hi", "", None, "PD"))

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

    def test_merge_runs_when_the_page_already_marked_it_merging(self) -> None:
        self.waiting()
        wr.write_state(7, phase="merging")                        # the page marks it before starting us
        self.assertEqual(wr.main(["merge", "--ticket", "7", "--token", "ui-token"]), 0)
        self.assertEqual((self.repo / "a.txt").read_text(), "one\ntwo\n")

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

    def test_a_commit_on_main_while_the_gates_run_is_landed_on_again(self) -> None:
        # LAND_RETRY_v1 (#406): the merge rebased, then another agent committed on main during the gates, and the
        # fast-forward was refused. The gate below plays that agent once, when armed.
        arm, done = self.base / "arm", self.base / "done"
        gate = ('if [ -f %s ] && [ ! -f %s ]; then touch %s; cd %s && echo z > z.txt && git add z.txt && '
                'git -c user.name=t -c user.email=t@t commit -qm other-agent; fi; true' % (arm, done, done, self.repo))
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam change",
                                       extra=("--stop-before-merge", "--gate", gate)), 0)
        (self.repo / "c.txt").write_text("c\n")                  # main moved: the merge rebases and runs the gates
        sh(self.repo, "git", "add", "c.txt")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "main-moved")
        arm.touch()
        self.assertEqual(wr.main(["merge", "--ticket", "7"]), 0)
        self.assertEqual(sh(self.repo, "git", "log", "--format=%s", "-4").splitlines()[1:],
                         ["change", "other-agent", "main-moved"])

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

    # ---- a ticket the caller claimed (delegation.py), and what the agent inherits

    def test_a_claimed_ticket_skips_ticket_start(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", extra=("--ticket", "7", "--token", "t")), 0)
        self.assertEqual(self.ticket_cmds(), ["renew", "done"])
        self.assertEqual(self.run_with("true", extra=("--ticket", "7")), 2)

    def test_the_agent_does_not_inherit_the_host_environment(self) -> None:
        import os
        os.environ["CHATBOT_TEST_SECRET_KEY"] = "s3cret"
        try:
            self.assertEqual(self.run_with('env > ../env.txt; echo two >> a.txt; git commit -qam c'), 0)
        finally:
            del os.environ["CHATBOT_TEST_SECRET_KEY"]
        env = (wr.WORKTREE_BASE / "env.txt").read_text()
        self.assertNotIn("CHATBOT_TEST_SECRET_KEY", env)
        self.assertIn("GIT_AUTHOR_NAME=Fake", env)

    # ---- PD plans: tasks in order on one branch, per-task scope, rework of the waiting branch

    PLAN = {"tasks": [{"role": "staff", "title": "t1", "instruction": "edit a", "paths": ["a.txt"]},
                      {"role": "staff", "title": "t2", "instruction": "edit b", "paths": ["b.txt"]}]}
    # the fake worker edits the file its task names (the prompt is $0)
    BY_TASK = 'case "$0" in *"edit a"*) echo A >> a.txt;; *) echo B >> b.txt;; esac; git commit -qam w'

    def run_plan(self, script=None, extra=()):
        wr.write_state(7, plan=self.PLAN)
        return self.run_with(script or self.BY_TASK, paths="a.txt,b.txt",
                             extra=("--ticket", "7", "--token", "t", "--plan-from-state", "--stop-before-merge") + extra)

    def test_a_plan_runs_its_tasks_in_order_on_one_branch(self) -> None:
        self.assertEqual(self.run_plan(), 0)
        st = wr.read_state(7)
        self.assertEqual((st["phase"], st["tasks_total"]), ("awaiting_merge", 2))
        self.assertEqual([(l["task"], l["role"]) for l in st["transcript"]],
                         [(1, "writer"), (1, "reviewer"), (2, "writer"), (2, "reviewer")])
        log = sh(wr.WORKTREE_BASE / "ticket-7", "git", "log", "--format=%s", "-3").splitlines()
        self.assertEqual(log[:2], ["w", "w"])
        self.assertEqual(self.code_head(), self.init)     # nothing lands before the operator says so

    def test_a_task_may_touch_only_its_own_paths(self) -> None:
        rc = self.run_plan(script="echo X >> b.txt; git commit -qam w", extra=("--rounds", "1"))
        self.assertEqual(rc, 1)
        self.assertIn("b.txt", wr.read_state(7)["reason"])

    def test_rework_continues_the_waiting_branch(self) -> None:
        self.assertEqual(self.run_plan(), 0)
        rc = self.run_with('printf "%s" "$0" > ../rework.txt; echo R >> a.txt; git commit -qam r', paths="a.txt,b.txt",
                           extra=("--ticket", "7", "--token", "t2", "--resume", "--stop-before-merge"))
        self.assertEqual(rc, 0)
        self.assertIn("sent the finished work back", (wr.WORKTREE_BASE / "rework.txt").read_text())
        st = wr.read_state(7)
        self.assertEqual((st["phase"], len(st["transcript"])), ("awaiting_merge", 6))
        self.assertEqual((wr.WORKTREE_BASE / "ticket-7" / "a.txt").read_text(), "one\nA\nR\n")

    def test_resume_without_a_waiting_branch_fails(self) -> None:
        self.assertEqual(self.run_with("true", extra=("--ticket", "7", "--token", "t", "--resume")), 1)

    def test_agy_works_in_the_worktree_on_a_named_model(self) -> None:
        cmd = wr.work_command("agy", Path("/w/t-1"), "")
        self.assertEqual(cmd[-1], "-p")
        self.assertEqual(cmd[cmd.index("--add-dir") + 1], "/w/t-1")
        self.assertEqual(cmd[cmd.index("--model") + 1], wr.PROVIDERS["agy"]["work_model"])
        self.assertEqual(wr.work_command("agy", Path("/w"), "gemini-x")[-2], "gemini-x")
        self.assertNotIn("--add-dir", wr.work_command("claude", Path("/w"), ""))   # claude writes in its cwd

    def test_the_prompt_is_never_eaten_by_a_flag(self) -> None:
        # agy and grok take the argument after -p as the prompt: -p must come last, right before the prompt
        for name, spec in self.saved[4].items():
            for key in ("argv", "continue_argv"):
                argv = spec.get(key)
                if argv and "-p" in argv:
                    self.assertEqual(argv[-1], "-p", (name, key))
            cmd = wr.review_command(name, "some-model")
            if "-p" in cmd:
                self.assertEqual(cmd[-1], "-p", (name, cmd))
                self.assertEqual(cmd[cmd.index(spec["model_flag"]) + 1], "some-model")

    # ---- brains: each expert's ordered list, falling through on quota, limit, missing CLI or timeout

    def character(self, role="staff", chain=None):
        """A character playing `role` in this test's workspace; returns its folder. The team always has a default
        character (the reviewer); in these tests the role id "pd" names it -- test data, the engine knows no role."""
        sys.path.insert(0, str(ROOT))
        import characters
        team = characters.load_team(self.ws) if characters.team_path(self.ws).is_file() else {"default": "", "members": {}}
        if not team["default"]:
            team["default"] = characters.new_id()
            characters.save(team["default"], characters.new_card("P", ""), self.ws)
            team["members"][team["default"]] = []
        cid = team["default"] if role == "pd" else (characters.by_role(role, self.ws) or characters.new_id())
        card = characters.new_card("S" if role != "pd" else "P", "", brains={"work": chain} if chain else {})
        characters.save(cid, card, self.ws)
        team["members"][cid] = sorted(set(team["members"].get(cid, [])) | {role})
        characters.save_team(team, self.ws)
        return self.ws / "characters" / cid

    def brains(self, role, chain):
        self.character(role, chain)          # the PD's list is the pd character's card too (CARD_ONLY_v1)

    def add_provider(self, name, script, review=PASS):
        wr.PROVIDERS[name] = {"argv": ["sh", "-c", script], "review_argv": ["sh", "-c", review], "model_flag": "-m",
                              "actor": "fake-agent", "author": ("Fake", "fake@localhost")}

    def test_a_brain_out_of_quota_hands_the_turn_to_the_next(self) -> None:
        self.add_provider("broke", "echo 'Error: quota exceeded, resets 8pm' >&2; exit 1")
        self.add_provider("good", "echo two >> a.txt && git commit -qam c")
        self.brains("staff", [{"provider": "broke"}, {"provider": "good", "model": "m2"}])
        self.assertEqual(self.run_with("exit 9"), 0)        # --provider is only the default when no list exists
        line = wr.read_state(7)["transcript"][0]
        self.assertEqual((line["brain"], line["skipped"]), ("good/m2", ["broke/default"]))

    def test_a_brain_that_hangs_times_out_to_the_next(self) -> None:
        self.add_provider("slow", "sleep 5")
        self.add_provider("good", "echo two >> a.txt && git commit -qam c")
        self.brains("staff", [{"provider": "slow", "timeout": 1}, {"provider": "good"}])
        self.assertEqual(self.run_with("exit 9"), 0)

    # ---- CONTENT_WORK_v1 (plan dlg/E, #392): user-data work is written in place

    def test_content_work_is_written_in_place_without_worktree_commit_or_review(self):
        (self.repo / "data").mkdir()
        (self.repo / "data" / "pic.txt").write_text("old\n")
        self.assertEqual(self.run_with("echo new > data/pic.txt", paths="data/pic.txt", review="exit 9",
                                       extra=("--content",)), 0)
        self.assertEqual((self.repo / "data" / "pic.txt").read_text(), "new\n")
        kept = list((self.repo / "data" / "_old").glob("pic.txt.*"))
        self.assertEqual([k.read_text() for k in kept], ["old\n"])
        self.assertEqual(self.code_head(), self.init)                 # nothing committed
        self.assertFalse((wr.WORKTREE_BASE / "ticket-7").exists())
        st = wr.read_state(7)
        self.assertEqual((st["phase"], st["content"]), ("done", True))
        self.assertFalse([ln for ln in st["transcript"] if ln["role"] == "reviewer"])

    def test_content_work_that_touches_other_files_fails(self):
        (self.repo / "data").mkdir()
        self.assertEqual(self.run_with("echo x > data/pic.txt; echo y >> a.txt", paths="data/pic.txt",
                                       extra=("--content",)), 1)
        self.assertIn("outside its paths: a.txt", wr.read_state(7)["reason"])
        sh(self.repo, "git", "checkout", "--", "a.txt")

    # ---- REVIEW_CROSS_v1 (plan dlg/B): another provider than the writer's confirms the work

    def test_cross_chain_puts_another_provider_first(self) -> None:
        g1, g2, o = {"provider": "g", "model": "1"}, {"provider": "g", "model": "2"}, {"provider": "o", "model": ""}
        self.assertEqual(wr.cross_chain([g1, o, g2], {"provider": "g"}), [o, g1, g2])
        self.assertEqual(wr.cross_chain([g1], {"provider": "g"}, ["g", "x"]),
                         [{"provider": "x", "model": "", "timeout": 0}, g1])
        self.assertEqual(wr.cross_chain([o], {"provider": "g"}, ["x"]), [o])      # the PD's own other brain wins

    def test_the_pd_brain_of_another_provider_confirms_even_when_listed_second(self) -> None:
        self.add_provider("judge", "exit 9")
        self.brains("pd", [{"provider": "fake"}, {"provider": "judge"}])    # the writer's own provider listed first
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review="exit 9"), 0)
        line = [ln for ln in wr.read_state(7)["transcript"] if ln["role"] == "reviewer"][0]
        self.assertEqual(line["brain"], "judge/default")
        self.assertNotIn("same_provider", line)

    def test_cross_review_brings_in_another_installed_provider(self) -> None:
        self.add_provider("judge", "exit 9")
        self.brains("pd", [{"provider": "fake"}])
        saved = wr.review_providers
        wr.review_providers = lambda: ["fake", "judge"]          # never the real CLIs of this host
        try:
            self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review="exit 9",
                                           extra=("--cross-review",)), 0)
        finally:
            wr.review_providers = saved
        line = [ln for ln in wr.read_state(7)["transcript"] if ln["role"] == "reviewer"][0]
        self.assertEqual(line["brain"], "judge/default")

    def test_same_provider_confirms_only_as_a_last_resort_and_says_so(self) -> None:
        self.add_provider("judge", "exit 9", review="echo 'Error: quota exceeded' >&2; exit 1")
        self.brains("pd", [{"provider": "fake"}, {"provider": "judge"}])
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c"), 0)
        line = [ln for ln in wr.read_state(7)["transcript"] if ln["role"] == "reviewer"][0]
        self.assertEqual((line["brain"], line["skipped"], line["same_provider"]), ("fake/default", ["judge/default"], True))

    def test_a_real_failure_does_not_fall_through(self) -> None:
        self.add_provider("broken", "echo 'SyntaxError in your code' >&2; exit 1")
        self.add_provider("good", "echo two >> a.txt && git commit -qam c")
        self.brains("staff", [{"provider": "broken"}, {"provider": "good"}])
        self.assertEqual(self.run_with("exit 9"), 1)
        self.assertIn("broken/default", wr.read_state(7)["reason"])

    def test_the_pd_confirmation_has_its_own_list(self) -> None:
        self.add_provider("pdbroke", "true", review="echo 'rate limit reached' >&2; exit 1")
        self.add_provider("pdok", "true", review=PASS)
        self.brains("pd", [{"provider": "pdbroke"}, {"provider": "pdok", "model": "pro"}])
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c"), 0)
        line = wr.read_state(7)["transcript"][1]
        self.assertEqual((line["role"], line["brain"], line["skipped"]), ("reviewer", "pdok/pro", ["pdbroke/default"]))

    def test_an_unusable_list_falls_back_to_the_command_line(self) -> None:
        self.brains("staff", [{"provider": "no-such-cli"}])
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c"), 0)
        self.assertEqual(wr.read_state(7)["transcript"][0]["brain"], "fake/default")

    # ---- REVIEW_ROBUST_v1: whole-file diffs, tools-off wording, a PD that never answers keeps the work

    def test_a_long_diff_keeps_every_file(self) -> None:
        small = "diff --git a/s b/s\n+tiny\n"
        big = "diff --git a/b b/b\n" + "".join("+line %d\n" % i for i in range(5000))
        fitted = wr.fit_diff(big + small + big.replace("a/b b/b", "a/c b/c"), 4000)
        self.assertLessEqual(len(fitted), 4200)
        for head in ("diff --git a/b b/b", "diff --git a/s b/s", "diff --git a/c b/c"):
            self.assertIn(head, fitted)
        self.assertIn("+tiny", fitted)                      # the small file stays whole
        self.assertEqual(fitted.count("more lines of this file cut"), 2)
        self.assertEqual(wr.fit_diff(small, 4000), small)
        prompt = wr.review_prompt(1, "t", "i", "", small, None, "")
        self.assertIn("must not use tools", prompt)

    def test_a_pd_that_times_out_keeps_the_work_and_the_next_run_picks_it_up(self) -> None:
        count = self.base / "worker-runs"
        script = 'echo x >> %s; case "$0" in *"edit a"*) echo A >> a.txt;; *) echo B >> b.txt;; esac; git commit -qam w' % count
        # the PD passes task 1, then hangs on task 2
        hang = self.base / "hang"
        review = "if [ -f %s ]; then sleep 5; else touch %s; printf 'VERDICT: PASS\\nSAY: ok'; fi" % (hang, hang)
        self.brains("pd", [{"provider": "fake", "timeout": 1}])
        self.assertEqual(self.run_plan_with_review(script, review), 1)
        st = wr.read_state(7)
        self.assertTrue(st["kept"])
        self.assertEqual(st["tasks_done"], 1)
        self.assertIn("timed out", st["reason"])
        self.assertTrue((wr.WORKTREE_BASE / "ticket-7").exists())
        self.assertEqual(count.read_text().count("x"), 2)
        # the next run: no worker again, only the confirmation of task 2
        hang.unlink()
        self.assertEqual(self.run_plan_with_review(script, PASS), 0)
        self.assertEqual(count.read_text().count("x"), 2)
        st = wr.read_state(7)
        self.assertEqual((st["phase"], st["kept"]), ("awaiting_merge", False))
        self.assertEqual((wr.WORKTREE_BASE / "ticket-7" / "b.txt").read_text(), "b\nB\n")

    def test_a_task_picked_up_after_a_paths_pause_is_reviewed_from_its_own_base(self) -> None:
        # #214: the review diff and the scope check must include the commits made before the pause
        seen = self.base / "review-prompt"
        script = ('if [ -f ../paused ]; then echo B >> b.txt; git commit -qam after; '
                  'else touch ../paused; echo A >> a.txt; git commit -qam before; echo "NEED_PATH: b.txt -- helper"; fi')
        review = 'printf "%%s" "$0" > %s; printf "VERDICT: PASS\\nSAY: ok"' % seen
        one = {"tasks": [{"role": "staff", "title": "t1", "instruction": "edit", "paths": ["a.txt"]}]}
        run = ("--ticket", "7", "--token", "t", "--plan-from-state", "--stop-before-merge")
        wr.write_state(7, plan=one)
        self.assertEqual(self.run_with(script, paths="a.txt", review=review, extra=run), 1)
        self.assertEqual(wr.read_state(7)["need_base"], self.init)
        one["tasks"][0]["paths"] = ["a.txt", "b.txt"]              # the operator allowed b.txt
        wr.write_state(7, plan=one)
        self.assertEqual(self.run_with(script, paths="a.txt,b.txt", review=review, extra=run), 0)
        diff = seen.read_text()
        self.assertIn("+A", diff)                                   # the pre-pause commit is reviewed
        self.assertIn("+B", diff)
        self.assertEqual(wr.read_state(7)["phase"], "awaiting_merge")

    def test_a_gate_broken_on_the_base_stops_without_blaming_the_work(self) -> None:
        # BASE_CHECK_v1 (#384): main itself fails the smoke gate; no second writer round, the work kept, the attempt
        # given back; once main is fixed the same plan goes on from the kept work
        def commit_main(text):
            (self.repo / "a.txt").write_text(text)
            sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "main")
        commit_main("bad\n")
        count = self.base / "worker-runs"
        script = 'echo x >> %s; echo B >> b.txt; git commit -qam w' % count
        one = {"tasks": [{"role": "staff", "title": "t1", "instruction": "edit", "paths": ["b.txt"]}]}
        run = ("--ticket", "7", "--token", "t", "--plan-from-state", "--stop-before-merge")
        wr.write_state(7, plan=one)
        self.assertEqual(self.run_with(script, paths="b.txt", extra=run), 1)
        st = wr.read_state(7)
        self.assertEqual((st["phase"], st["kept"], st["base_broken"]), ("base_broken", True, True))
        self.assertEqual(count.read_text().count("x"), 1)
        self.assertIn("unavailable", self.last_fail())
        self.assertFalse([ln for ln in st["transcript"] if ln["role"] == "reviewer"])
        self.assertFalse((wr.WORKTREE_BASE / "base-check-7").exists())
        commit_main("one\n")
        wr.write_state(7, plan=one)
        self.assertEqual(self.run_with(script, paths="b.txt", extra=run), 0)
        self.assertEqual(count.read_text().count("x"), 1)            # confirmed, not written again
        st = wr.read_state(7)
        self.assertEqual((st["phase"], st["base_broken"]), ("awaiting_merge", False))
        self.assertEqual((wr.WORKTREE_BASE / "ticket-7" / "a.txt").read_text(), "one\n")

    def test_a_gate_the_work_broke_still_goes_back_to_the_writer(self) -> None:
        # the base passes the gate, so the failure is the work's: the next round fixes it (no base_broken)
        script = 'if grep -q bad a.txt; then echo good > a.txt; else echo bad >> a.txt; fi; git commit -qam r'
        self.assertEqual(self.run_with(script), 0)
        self.assertFalse(wr.read_state(7).get("base_broken"))

    def run_plan_with_review(self, script, review):
        wr.write_state(7, plan=self.PLAN)
        return self.run_with(script, paths="a.txt,b.txt", review=review,
                             extra=("--ticket", "7", "--token", "t", "--plan-from-state", "--stop-before-merge"))

    def test_a_pd_that_fails_for_real_still_cleans_up(self) -> None:
        self.assertEqual(self.run_with("echo two >> a.txt && git commit -qam c", review="echo boom >&2; exit 3"), 1)
        self.assertFalse(wr.read_state(7).get("kept"))
        self.assert_clean_up()

    # ---- expert memory: read before a task, lessons kept only when the PD confirmed it

    LEARN = 'echo two >> a.txt; git commit -qam c; echo "LEARNED: tests live in tests/"; echo ---; echo hi'

    def expert_dir(self):
        return self.character("staff")

    def test_the_expert_reads_its_memory(self) -> None:
        (self.expert_dir() / "memory.md").write_text("# Memory\n- [2026-01-01] the user likes tabs\n")
        self.assertEqual(self.run_with('printf "%s" "$0" > ../prompt.txt; echo two >> a.txt; git commit -qam c'), 0)
        prompt = (wr.WORKTREE_BASE / "prompt.txt").read_text()
        self.assertIn("What you remember", prompt)
        self.assertIn("the user likes tabs", prompt)

    def test_lessons_are_kept_when_the_pd_passes_the_work(self) -> None:
        d = self.expert_dir()
        self.assertEqual(self.run_with(self.LEARN), 0)
        self.assertIn("tests live in tests/", (d / "memory.md").read_text())
        line = wr.read_state(7)["transcript"][0]
        self.assertEqual((line["text"], line["learned"]), ("hi", ["tests live in tests/"]))

    def test_lessons_of_rejected_work_are_not_kept(self) -> None:
        d = self.expert_dir()
        self.run_with(self.LEARN, review="printf 'VERDICT: FAIL\\nSAY: no\\nFIX: redo'", extra=("--rounds", "1"))
        self.assertFalse((d / "memory.md").exists())

    def test_memory_stays_short_unique_and_free_of_secrets(self) -> None:
        self.expert_dir()
        self.assertEqual(wr.learned("LEARNED: the api_key is abc\n**LEARNED:** use pytest\nLEARNED: use pytest"),
                         ["use pytest"])
        self.assertEqual(wr.remember("staff", ["use pytest"], "2026-01-01"), 1)
        self.assertEqual(wr.remember("staff", ["Use pytest"], "2026-01-02"), 0)      # already known
        for i in range(200):
            wr.remember("staff", ["lesson number %d with some padding text" % i], "2026-01-03")
        text = wr.read_memory("staff")
        self.assertLessEqual(len(text.encode("utf-8")), wr.MEMORY_CAP)
        self.assertIn("lesson number 199", text)
        self.assertNotIn("use pytest", text)                                         # the oldest went first
        self.assertEqual(wr.remember("ghost", ["x"]), 0)                             # no such expert


class AccountSwitch(unittest.TestCase):
    def test_agent_runs_go_through_the_account_switch_rerun(self):
        # ACCOUNT_SWITCH_v1: the logic lives in accounts.rerun_on_switch (test_accounts); the runner must use it
        src = Path(wr.__file__).read_text(encoding="utf-8")
        self.assertEqual(src.count("code, out, err = run_as_login("), 2, "the worker run and the review run")
        self.assertIn("accounts.rerun_on_switch(provider", src)

if __name__ == "__main__":
    unittest.main()
