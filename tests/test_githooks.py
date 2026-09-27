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

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_staged", ROOT / ".githooks" / "check_staged.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


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
        self.assertEqual(self.commit("a.txt", "1", "fix(core): update stuff").returncode, 0)

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
