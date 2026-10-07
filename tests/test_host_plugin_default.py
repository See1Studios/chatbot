"""A fresh install is not this NAS (align/F, direction-alignment D3): with no host settings the NAS host plugin is
off, the web root sits in the install's own data, and a web root that does not exist is not handed to agents.
$CHATBOT_DATA/host.env (templates/host.env.example) turns the plugin on and names a real web root.
Run: python3 -m unittest tests.test_host_plugin_default  (from services/chatbot)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ("import json, host_config as h, mcp_server as m; "
         "print(json.dumps({'plugin': bool(m.HOST_PLUGIN), 'web': str(h.WEB_ROOT), 'mcp_web': str(m.WEB_ROOT), "
         "'add_dirs': h.ADD_DIRS}))")


def probe(extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("NAS_MCP_HOST_PLUGIN", "CHATBOT_WEB_ROOT")}
    env.update(extra)
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class HostPluginDefault(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())

    def test_no_settings_means_no_host_plugin_and_a_local_web_root(self):
        got = probe({"CHATBOT_DATA": str(self.data)})
        self.assertFalse(got["plugin"])
        self.assertEqual(got["web"], str(self.data / "web"))
        self.assertEqual(got["mcp_web"], str(self.data / "web"))
        self.assertNotIn(str(self.data / "web" / "chat"), got["add_dirs"])   # does not exist: not given to agents

    def test_host_settings_turn_the_plugin_on_and_name_the_web_root(self):
        web = self.data / "site"
        (web / "chat").mkdir(parents=True)
        got = probe({"CHATBOT_DATA": str(self.data), "NAS_MCP_HOST_PLUGIN": "1", "CHATBOT_WEB_ROOT": str(web)})
        self.assertTrue(got["plugin"])
        self.assertEqual(got["web"], str(web))
        self.assertIn(str(web / "chat"), got["add_dirs"])


if __name__ == "__main__":
    unittest.main()
