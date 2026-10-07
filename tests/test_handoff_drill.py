"""HANDOFF_DRILL_v1: the scenario drill runs on a sandbox host and never reaches the live data or ports.
Run: engine/run-tests.sh test_handoff_drill
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "tools"))
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

    def test_every_clis_tool_server_record_is_moved_to_the_sandbox(self):
        # grok (.grok/config.toml) and claude (.mcp.json) keep it in the workspace too, as the live host wrote it
        self.assertEqual(set(D.TOOL_CONFIGS), {".gemini/config/mcp_config.json", ".grok/config.toml", ".mcp.json"})

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

    def test_the_drill_never_reads_what_a_model_said(self):
        # a check on the model's words passes or fails with the model and the language
        # (multilingual-no-language-heuristics): the drill judges by the ledger and the event log only
        src = Path(D.__file__).read_text(encoding="utf-8")
        for read in ('get("text")', 'get("result")', '["text"]', '["result"]'):
            self.assertNotIn(read, src, "the drill reads model text (%s)" % read)

    def test_every_scenario_says_what_it_checks(self):
        for name, fn in D.SCENARIOS.items():
            self.assertTrue((fn.__doc__ or "").strip(), name)


if __name__ == "__main__":
    unittest.main()
