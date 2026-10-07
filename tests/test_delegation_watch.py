"""WORKER_STALL_v1 (delegation_watch.run, AgentAdapter.last_activity): a delegated worker whose provider reports no
activity for the stall limit is stopped like a timeout, so the runner moves to the next brain; a provider without an
activity signal is held to the overall timeout only. agy's signal is the last model call in its own log.
Run: engine/run-tests.sh test_delegation_watch
"""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import delegation_watch as W  # noqa: E402
from providers import accounts  # noqa: E402
from providers.adapter_agy import AgyAdapter  # noqa: E402
from providers.adapter_base import AgentAdapter  # noqa: E402

PY = sys.executable


class Run(unittest.TestCase):
    def test_a_finished_run_returns_its_output_and_takes_stdin_once(self):
        code, out, err = W.run([PY, "-c", "import sys; print(sys.stdin.read().upper())"], stdin="hi", poll_sec=0.05)
        self.assertEqual((code, out, err), (0, "HI", ""))

    def test_no_activity_for_the_limit_stops_it_as_stalled(self):
        t0 = time.time()
        code, _out, err = W.run([PY, "-c", "import time; time.sleep(30)"], timeout=60, stall_sec=1, poll_sec=0.2,
                                activity=lambda pid, started: started)      # never a model call
        self.assertEqual(code, -1)
        self.assertTrue(err.startswith("stalled:"), err)
        self.assertIn("capacity", err, "the runner's unavailable() must read it as a brain that could not work")
        self.assertLess(time.time() - t0, 10)

    def test_recent_activity_keeps_it_running_until_the_timeout(self):
        code, _out, err = W.run([PY, "-c", "import time; time.sleep(30)"], timeout=1, stall_sec=0, poll_sec=0.2,
                                activity=lambda pid, started: time.time())
        self.assertEqual((code, err), (-1, "timed out after 1s"))

    def test_without_a_signal_only_the_timeout_applies(self):
        code, _out, err = W.run([PY, "-c", "import time; time.sleep(30)"], timeout=1, stall_sec=0, poll_sec=0.2,
                                activity=lambda pid, started: None)
        self.assertEqual((code, err), (-1, "timed out after 1s"))
        self.assertIsNone(AgentAdapter.last_activity(AgentAdapter(), 1, 0), "the default: no signal")

    def test_a_broken_probe_never_stops_the_work(self):
        def boom(pid, started):
            raise RuntimeError("probe")
        self.assertEqual(W.run([PY, "-c", "print(1)"], poll_sec=0.05, activity=boom)[0], 0)


class AgyActivity(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.saved = accounts.AGY_LOG_DIR
        accounts.AGY_LOG_DIR = self.dir
        accounts._log_account_cache.clear()
        self.started = time.mktime((2026, 9, 30, 14, 32, 18, 0, 0, -1))

    def tearDown(self):
        accounts.AGY_LOG_DIR = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def log(self, pid, lines):
        (self.dir / "cli-20260930_143218.log").write_text(
            "I0930 14:32:18.851010  50 server.go:1568] Starting language server process with pid %d\n" % pid
            + "".join(l + "\n" for l in lines), encoding="utf-8")

    def test_the_last_model_call_in_the_process_s_log(self):
        call = "I0930 %s.658722     605 http_helpers.go:315] URL: https://x/v1internal:streamGenerateContent?alt=sse"
        self.log(777, [call % "14:32:33", "I0930 14:38:20.767116  1440 http_helpers.go:315] URL: https://x/v1internal:fetchAvailableModels",
                       call % "14:40:05"])
        self.assertEqual(AgyAdapter().last_activity(777, self.started),
                         time.mktime((2026, 9, 30, 14, 40, 5, 0, 0, -1)), "a model list fetch is not work")

    def test_no_call_yet_counts_from_the_start_and_no_log_is_no_signal(self):
        self.log(777, ["I0930 14:32:20.771627       1 printmode.go:405] Print mode: silent auth succeeded"])
        self.assertEqual(AgyAdapter().last_activity(777, self.started), self.started)
        self.assertIsNone(AgyAdapter().last_activity(888, self.started))


class Wiring(unittest.TestCase):
    def test_the_runner_runs_workers_and_reviewers_under_the_watch(self):
        src = (ENGINE / "tools" / "worktree_runner.py").read_text(encoding="utf-8")
        self.assertIn("watch.run(cmd, activity=watch.activity_of(provider)", src)
        self.assertIsNotNone(W.activity_of("agy"))


if __name__ == "__main__":
    unittest.main()
