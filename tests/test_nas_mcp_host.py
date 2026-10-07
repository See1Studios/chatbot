"""The NAS host plugin's service tools. The sibling nas-mcp and character-chat services were retired 2026-10-07 (their
log showed health checks only, no tool call): the plugin neither lists nor delegates to them.
Run: engine/run-tests.sh test_nas_mcp_host
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
sys.path.insert(0, str(ENGINE))
import mcp_server as mcp  # noqa: E402
import nas_mcp_host as H  # noqa: E402


class NamesTest(unittest.TestCase):
    def test_chatbot_mcp_healthz_name(self):
        src = (ENGINE / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn('"service": "chatbot-mcp"', src)

    def test_list_services_names_no_retired_service(self):
        r = H.call_tool("list_services", {})
        by_name = {row["name"]: row for row in r["data"]["services"] if "port" in row}
        self.assertEqual(by_name["chatbot-mcp"]["port"], mcp.PORT)
        self.assertNotIn("nas-mcp", by_name)
        self.assertNotIn("nas-mcp", H.SERVICE_CTLS)


class StatusTest(unittest.TestCase):
    def test_hub_status_checks_locally(self):
        with mock.patch.object(mcp, "_run", return_value=(0, "ok", "")):
            r = H.call_tool("sphere_hub_status", {})
        self.assertTrue(r["success"])
        self.assertIn("chatbot_mcp", r["data"])
        self.assertNotIn("nas_mcp", r["data"])
        self.assertNotIn("central_mcp", r["data"])


if __name__ == "__main__":
    unittest.main()
