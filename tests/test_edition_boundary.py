"""The shipped build never lets the agent touch engine code (docs/plans/edition-boundary.md, CONCEPT 「배포판과 개발판」).
With no CHATBOT_EDITION the install is the shipped build: the MCP server offers no run_command, ticket or delegate
tool and refuses them if called by name, and its file tools reach only the install's user data -- not the engine
repo, not host-wide agent folders. CHATBOT_EDITION=dev (in $CHATBOT_DATA/host.env) restores the dev tools and roots.
Run: python3 -m unittest tests.test_edition_boundary  (from services/chatbot)
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests._paths import REPO  # noqa: E402
ROOT = REPO
DEV_ONLY = {"run_command", "ticket", "delegate"}
PROBE = r"""
import json, host_config as h, mcp_server as m
names = [d["name"] for d in m.tool_defs()]
called = m.call_tool("run_command", {"command": "ls"})
print(json.dumps({"edition": h.EDITION, "tools": names, "run_command_ok": bool(called.get("success")),
                  "run_command_msg": called.get("message", ""),
                  "write": [str(p) for p in m._allow_roots()], "read": [str(p) for p in m._read_roots()]}))
"""


def probe(edition):
    env = {k: v for k, v in os.environ.items() if k not in ("CHATBOT_EDITION", "NAS_MCP_HOST_PLUGIN")}
    if edition:
        env["CHATBOT_EDITION"] = edition
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class EditionBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shipped = probe(None)
        cls.dev = probe("dev")

    def test_no_setting_means_the_shipped_build(self):
        self.assertEqual(self.shipped["edition"], "shipped")

    def test_the_shipped_build_has_no_dev_tools_and_refuses_them(self):
        self.assertFalse(DEV_ONLY & set(self.shipped["tools"]), self.shipped["tools"])
        for keep in ("memory", "observation", "choices", "read_file", "write_file"):
            self.assertIn(keep, self.shipped["tools"])
        self.assertFalse(self.shipped["run_command_ok"])
        self.assertIn("not available in this edition", self.shipped["run_command_msg"])

    def test_the_shipped_build_reaches_only_user_data(self):
        repo = str(ROOT.resolve())
        agents = str((Path.home() / ".agents").resolve())
        for kind in ("write", "read"):
            for p in self.shipped[kind]:
                self.assertFalse(p == repo or (p + "/").startswith(repo + "/") and "/data" not in p[len(repo):],
                                 "%s root %s is the engine repo" % (kind, p))
                self.assertNotEqual(p, agents, "%s root reaches host-wide agent folders" % kind)
        self.assertNotIn(repo, self.shipped["write"])

    def test_the_dev_build_keeps_its_tools_and_the_repo(self):
        self.assertTrue({"run_command", "ticket"} <= set(self.dev["tools"]))
        self.assertIn(str(ROOT.resolve()), self.dev["write"])


if __name__ == "__main__":
    unittest.main()
