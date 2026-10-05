"""HANDOFF_DRILL_v1: the scenario drill runs on a sandbox host and never reaches the live data or ports.
Run: python3 -m unittest tests.test_handoff_drill  (from services/chatbot)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("CHATBOT_DRILL_DATA", tempfile.mkdtemp())
import handoff_drill as D  # noqa: E402


class Sandbox(unittest.TestCase):
    def test_the_host_runs_on_its_own_data_logs_and_ports(self):
        env = D._env()
        self.assertEqual(env["CHATBOT_DATA"], str(D.DRILL))
        for k in ("CHATBOT_LOG_DIR", "CHATBOT_OBSLOG_PATH", "CHATBOT_EVENTS_DIR", "CHATBOT_DIALOGS_DIR"):
            self.assertTrue(env[k].startswith(str(D.DRILL)), k)
        self.assertEqual((env["CHATBOT_PORT"], env["NAS_MCP_PORT"]), ("3021", "3022"))
        self.assertNotIn("CHATBOT_HANDOFFS_FILE", env)
        self.assertEqual(env["HOME"], str(D.DRILL / "home"))   # the agent CLI's own tool-server config is the sandbox's

    def test_the_drills_ledger_is_the_sandboxs(self):
        self.assertEqual(Path(os.environ["CHATBOT_HANDOFFS_FILE"]).parent, D.DRILL)

    def test_it_refuses_to_rebuild_the_live_folder(self):
        with mock.patch.object(D, "DRILL", D.LIVE), self.assertRaises(SystemExit):
            D.build()

    def test_the_operators_records_are_not_copied(self):
        for name in ("sessions", "dialogs", "handoffs.jsonl", "events", "tickets.db"):
            self.assertNotIn(name, D.COPY)
        self.assertTrue({"artifacts", "skill-observations", "memory"} <= D.SKIP)


class Reporting(unittest.TestCase):
    def test_a_scenario_passes_only_with_every_check(self):
        r = D.Run("x")
        self.assertFalse(r.ok, "no check is no pass")
        r.check(True, "a")
        r.check(False, "b")
        self.assertFalse(r.ok)
        self.assertIn("FAIL x", D.report(r))
        self.assertIn("✗ b", D.report(r))

    def test_every_scenario_says_what_it_checks(self):
        for name, fn in D.SCENARIOS.items():
            self.assertTrue((fn.__doc__ or "").strip(), name)


if __name__ == "__main__":
    unittest.main()
