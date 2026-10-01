"""Commit hooks (.githooks/, plan-execution-workflow pew/E) refuse what the rules forbid, in a throwaway repo: a
non-Conventional subject, a docs/plans change without a `Plan:` trailer, a committed secrets file, a key-shaped added
line. The delegation runner's own commit subjects must pass.
Run: python3 -m unittest tests.test_githooks  (from services/chatbot)
"""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from tests._platform import dev_only_bash  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_staged", ROOT / ".githooks" / "check_staged.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@dev_only_bash
class Hooks(unittest.TestCase):
    def setUp(self):
        # /tmp is mounted noexec on this NAS, and git silently skips a hook it cannot execute
        base = Path(os.environ.get("HOOK_TEST_DIR") or Path.home() / ".cache" / "chatbot-hook-tests")
        base.mkdir(parents=True, exist_ok=True)
        self.repo = Path(tempfile.mkdtemp(dir=str(base)))
        shutil.copytree(str(ROOT / ".githooks"), str(self.repo / ".githooks"))
        self.git("init", "-q")
        self.git("config", "core.hooksPath", ".githooks")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@t")

    def tearDown(self):
        shutil.rmtree(str(self.repo), ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.repo), capture_output=True, text=True)

    def commit(self, rel, text, msg):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self.git("add", rel)
        return self.git("commit", "-qm", msg)

    def test_a_conventional_subject_passes_and_others_do_not(self):
        self.assertNotEqual(self.commit("a.txt", "1", "update stuff").returncode, 0)
        self.assertEqual(self.commit("a.txt", "1", "fix(core): update stuff\n\nTicket: #1").returncode, 0)

    def test_a_code_change_names_its_ticket(self):
        # review of #505-#525: 27 of 29 delegated commits had no Ticket trailer
        r = self.commit("a.txt", "1", "feat(ui): something")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Ticket: #<n>", r.stdout + r.stderr)
        self.assertEqual(self.commit("a.txt", "2", "feat(ui): something\n\nTicket: #4").returncode, 0)
        self.assertEqual(self.commit("b.txt", "1", "docs: notes").returncode, 0)          # not a code change
        self.assertEqual(self.commit("c.txt", "1", "chore(tickets): close #4 -- t").returncode, 0)

    def test_a_worker_on_its_ticket_branch_gets_the_trailer_written(self):
        self.assertEqual(self.commit("a.txt", "1", "chore: start").returncode, 0)
        self.git("checkout", "-q", "-b", "worktree/ticket-77")
        self.assertEqual(self.commit("a.txt", "2", "feat(ui): from a worker").returncode, 0)
        self.assertIn("Ticket: #77", self.git("log", "-1", "--format=%B").stdout)

    def test_plan_changes_need_a_plan_trailer(self):
        self.assertNotEqual(self.commit("docs/plans/x.md", "x", "docs(plans): x").returncode, 0)
        self.assertEqual(self.commit("docs/plans/x.md", "x", "docs(plans): x\n\nPlan: x/A").returncode, 0)

    def test_secrets_are_refused_without_echoing_them(self):
        r = self.commit("data/secrets.env", "K=1", "chore: keys")
        self.assertNotEqual(r.returncode, 0)
        self.git("rm", "-q", "--cached", "data/secrets.env")
        fake = "sk-" + "A" * 30
        r = self.commit("b.py", "KEY = '%s'\n" % fake, "feat: add b")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(fake, r.stdout + r.stderr)
        self.assertEqual(self.commit("b.py", "KEY = '%s'  # %s\n" % (fake, check.ALLOW), "test: fixture").returncode, 0)

    def test_guards_judge_the_staged_snapshot_not_the_shared_tree(self):
        # pew/Q: agents share one working tree; another agent's unstaged work must not decide my commit
        (self.repo / "run-tests.sh").write_text('grep -q bad guard.txt && { echo "failed: guard"; exit 1; }; exit 0\n',
                                                encoding="utf-8")
        self.assertEqual(self.commit("guard.txt", "ok\n", "chore: start").returncode, 0)   # first commit: no HEAD yet
        self.git("add", "run-tests.sh")
        self.assertEqual(self.git("commit", "-qm", "chore: runner").returncode, 0)
        (self.repo / "guard.txt").write_text("bad\n", encoding="utf-8")                   # someone else's unstaged work
        self.assertEqual(self.commit("mine.txt", "x\n", "feat: mine\n\nTicket: #1").returncode, 0)
        (self.repo / "only.txt").write_text("y\n", encoding="utf-8")
        self.git("add", "only.txt")
        self.assertEqual(self.git("commit", "-qm", "feat: by path\n\nTicket: #1", "--", "only.txt").returncode, 0)   # temp index
        self.git("add", "guard.txt")                                                        # now I stage the breakage
        self.assertNotEqual(self.git("commit", "-qm", "feat: breaks").returncode, 0)
        self.git("reset", "-q", "guard.txt")
        self.assertNotEqual(self.git("commit", "-qam", "feat: all").returncode, 0)          # -a stages it too
        worktrees = self.git("worktree", "list").stdout.strip().splitlines()
        self.assertEqual(len(worktrees), 1, "the snapshot worktree must be removed: %s" % worktrees)

    def test_the_hooks_are_committed_executable(self):
        # a hook that lost its exec bit is skipped with only a hint -- the check would vanish silently
        out = subprocess.run(["git", "ls-files", "-s", ".githooks"], cwd=str(ROOT), capture_output=True, text=True).stdout
        modes = {l.split()[-1]: l.split()[0] for l in out.splitlines()}
        for hook in (".githooks/pre-commit", ".githooks/commit-msg"):
            if modes:   # tracked: the index must say 100755
                self.assertEqual(modes.get(hook), "100755", hook)
            self.assertTrue(os.access(str(ROOT / hook), os.X_OK), hook)

    def test_the_runner_commit_subjects_pass(self):
        for s in ("chore(tickets): close #12 -- title", "chore(tickets): #12 gate_failed -- t",
                  "chore(ticket #12): changes the agent left uncommitted"):
            self.assertTrue(check.SUBJECT.match(s), s)


if __name__ == "__main__":
    unittest.main()
