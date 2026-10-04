"""LIVE_AGENT_SUITE_v1: a live chat agent and its subagents (CHATBOT_LIVE_AGENT, set where the host spawns them) run
the guards or named test modules, never the whole suite (2026-10-05: a subagent ran it, agy backgrounded it and
waited, the dev director's handoff turn ran out of time).
Run: python3 -m unittest tests.test_live_agent_suite  (from services/chatbot)
"""
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
        src = (ROOT / "session.py").read_text(encoding="utf-8")
        self.assertIn('env["CHATBOT_LIVE_AGENT"] = "1"', src)


if __name__ == "__main__":
    unittest.main()
