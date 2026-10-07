"""LIVE_AGENT_SUITE_v1: a live chat agent and its subagents (CHATBOT_LIVE_AGENT, set where the host spawns them) run
the guards or named test modules, never the whole suite (2026-10-05: a subagent ran it, agy backgrounded it and
waited, the dev director's handoff turn ran out of time).
Run: python3 -m unittest tests.test_live_agent_suite  (from services/chatbot)
"""
import os
import subprocess
import unittest
from pathlib import Path
from tests._paths import ENGINE, REPO  # noqa: E402

ROOT = REPO


def run(*args, live=True):
    env = dict(os.environ)
    env.pop("CHATBOT_LIVE_AGENT", None)
    if live:
        env["CHATBOT_LIVE_AGENT"] = "1"
    return subprocess.run(["./run-tests.sh", *args], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)


class LiveAgentSuite(unittest.TestCase):
    def test_a_chat_agent_cannot_start_the_whole_suite(self):
        for args in ((), ("--one-process",)):
            r = run(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("Name the modules", r.stderr)

    def test_named_modules_still_run_for_a_chat_agent(self):
        r = run("test_docs_budget")
        self.assertEqual(r.returncode, 0, r.stdout[-500:] + r.stderr[-500:])

    def test_the_host_marks_the_agents_it_spawns(self):
        src = (ENGINE / "session.py").read_text(encoding="utf-8")
        self.assertIn('env["CHATBOT_LIVE_AGENT"] = "1"', src)


    def test_a_chat_agent_cannot_run_unittest_around_the_script(self):
        # live 2026-10-05: a subagent ran `python3 -m unittest discover tests`, held handoff #7 open, against ~/.pe
        env = dict(os.environ, CHATBOT_LIVE_AGENT="1", CHATBOT_DATA="/nonexistent/live")
        env.pop("CHATBOT_TEST_RUNNER", None)
        r = subprocess.run(["python3", "-m", "unittest", "tests.test_data_paths"], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("only as ./run-tests.sh", r.stderr + r.stdout)

    def test_a_test_run_outside_the_script_never_gets_an_installs_data(self):
        import sys
        sys.path.insert(0, str(ENGINE))
        import host_config
        import tickets
        saved_argv, saved_env = sys.argv, dict(os.environ)
        try:
            sys.argv = ["python3 -m unittest", "tests.test_x"]
            os.environ.pop("CHATBOT_TEST_RUNNER", None)
            os.environ["CHATBOT_DATA"] = "/somewhere/live/.pe"
            self.assertTrue(host_config.test_run_outside_runner())
            self.assertEqual(tickets._data_dir(), ENGINE / "data")
            os.environ["CHATBOT_TEST_RUNNER"] = "1"                              # the script's own run
            self.assertFalse(host_config.test_run_outside_runner())
            self.assertEqual(str(tickets._data_dir()), "/somewhere/live/.pe")
            sys.argv = ["server.py"]                                             # the host itself: untouched
            os.environ.pop("CHATBOT_TEST_RUNNER", None)
            self.assertFalse(host_config.test_run_outside_runner())
        finally:
            sys.argv = saved_argv
            os.environ.clear()
            os.environ.update(saved_env)

    def test_the_script_marks_its_own_runs(self):
        self.assertIn("export CHATBOT_TEST_RUNNER=1", (ENGINE / "run-tests.sh").read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
