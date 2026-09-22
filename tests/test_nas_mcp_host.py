"""Host MCP split leftovers: names, 3015 healthz, central delegation.
Run: python3 -m unittest tests.test_nas_mcp_host  (from services/chatbot)
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import mcp_server as mcp  # noqa: E402
import nas_mcp_host as H  # noqa: E402

HOST_MCP_SRC = CODE.parent / "nas-mcp" / "server.py"


class _Rpc:
    def __init__(self, text):
        self._raw = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": text}]},
        }).encode("utf-8")

    def read(self, *a, **k):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class NamesTest(unittest.TestCase):
    def test_chatbot_mcp_healthz_name(self):
        src = (CODE / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn('"service": "chatbot-mcp"', src)
        self.assertNotIn('"service": "nas-mcp"', src)

    def test_list_services_splits_ports(self):
        r = H.call_tool("list_services", {})
        by_name = {row["name"]: row for row in r["data"]["services"] if "port" in row}
        self.assertEqual(by_name["chatbot-mcp"]["port"], mcp.PORT)
        self.assertEqual(by_name["nas-mcp"]["port"], H.PORT_HOST_MCP)
        self.assertIn("/healthz", by_name["nas-mcp"]["url"])
        self.assertIn("3015", by_name["nas-mcp"]["url"])


class HostMcpHealthTest(unittest.TestCase):
    def test_host_mcp_probes_healthz_not_streamable_root(self):
        src = HOST_MCP_SRC.read_text(encoding="utf-8")
        self.assertIn('path in ("/healthz", "/health")', src)
        self.assertIn("http://127.0.0.1:3015/healthz", src)
        self.assertNotIn('("nas_mcp", "http://127.0.0.1:3015/")', src)


class DelegationTest(unittest.TestCase):
    def test_sphere_factory_hermes_use_central_when_it_answers(self):
        with mock.patch.object(H.urllib.request, "urlopen", return_value=_Rpc("- nas_mcp: UP")):
            for name in ("sphere_hub_status", "factory_status", "hermes_status"):
                r = H.call_tool(name, {})
                self.assertTrue(r["success"], name)
                self.assertTrue(r["data"].get("central_mcp"), name)
                self.assertIn("nas_mcp: UP", r["data"]["output"])

    def test_fallback_when_central_is_down(self):
        with mock.patch.object(H.urllib.request, "urlopen", side_effect=OSError("down")):
            with mock.patch.object(mcp, "_run", return_value=(0, "ok", "")):
                r = H.call_tool("sphere_hub_status", {})
        self.assertTrue(r["success"])
        self.assertNotIn("central_mcp", r["data"])
        self.assertIn("chatbot_mcp", r["data"])
        self.assertIn("nas_mcp", r["data"])


if __name__ == "__main__":
    unittest.main()
