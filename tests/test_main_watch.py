"""MAIN_WATCH_v1 (#825): after main moves, the whole suite checks it once in the background and the event log says
whether main is green. 2026-10-08: #817/#821/#822 left four modules red on main past the commit hook's guards.
Run: engine/run-tests.sh test_main_watch
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402

sys.path.insert(0, str(ENGINE))
from health import main_watch  # noqa: E402


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


class MainWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        (self.repo / "engine").mkdir(parents=True)
        self.runner = self.repo / "engine" / "run-tests.sh"
        self.runner.write_text("echo ok\nexit 0\n", encoding="utf-8")
        sh(self.repo, "git", "init", "-q", "-b", "main")
        self.commit("init")
        self.saved = main_watch.STATE
        main_watch.STATE = base / "state"

    def tearDown(self):
        main_watch.STATE = self.saved
        self.tmp.cleanup()

    def commit(self, msg):
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, "--allow-empty")
        return sh(self.repo, "git", "rev-parse", "HEAD")

    def test_the_suite_runs_on_mains_commit_and_names_what_failed(self):
        self.runner.write_text('echo "FAIL test_x"\necho "failed: test_x test_y"\nexit 1\n', encoding="utf-8")
        sha = self.commit("break")
        self.runner.write_text("echo ok\nexit 0\n", encoding="utf-8")       # the shared tree is not what is judged
        r = main_watch.suite(sha, self.repo)
        self.assertEqual((r["ok"], r["failed"]), (False, ["test_x", "test_y"]))
        self.assertEqual(sh(self.repo, "git", "worktree", "list").count("\n"), 0, "the snapshot is removed")
        self.assertTrue(main_watch.suite(self.commit("fix"), self.repo)["ok"])

    def test_one_check_at_a_time_and_a_move_meanwhile_is_checked_again(self):
        seen, notes = [], []

        def check(sha, repo):
            seen.append(sha)
            if len(seen) == 1:
                self.commit("landed while the suite ran")
                self.assertEqual(main_watch.run(0, self.repo, check, lambda *a: None), 0)   # a second kick
            return {"ok": True, "failed": [], "dur_s": 0, "tail": ""}

        self.assertEqual(main_watch.run(0, self.repo, check, lambda sha, r: notes.append(sha)), 2)
        self.assertEqual(seen[-1], sh(self.repo, "git", "rev-parse", "main"))
        self.assertEqual(notes, seen)

    def test_the_check_is_recorded_as_main_check(self):
        log = Path(self.tmp.name) / "events.jsonl"
        import host_config
        with mock.patch.object(host_config, "EVENTS_LOG", log):
            main_watch.record(sh(self.repo, "git", "rev-parse", "HEAD"),
                              {"ok": False, "failed": ["test_x"], "dur_s": 9, "tail": "failed: test_x"})
        text = log.read_text(encoding="utf-8")
        self.assertIn('"evt": "main.check"', text.replace('":"', '": "'))
        self.assertIn("test_x", text)

    def test_the_hook_starts_it_in_the_background_when_main_has_moved(self):
        hook = (REPO / ".githooks" / "reference-transaction").read_text(encoding="utf-8")
        self.assertIn('main_watch.py"', hook)
        self.assertIn("committed", hook)
        self.assertIn('run >>"$state/watch.log" 2>&1 </dev/null & }', hook)
        self.assertIn('[ -n "${CHATBOT_TEST_RUNNER:-}" ] && exit 0', hook, "a test run never starts a check")

if __name__ == "__main__":
    unittest.main()
