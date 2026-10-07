"""mcp_core.py: the core's MCP adapters (`memory`, `observation`, `ticket`) as a module of their own.

It is a layer over the core and knows nothing about the server that hosts it: these tests load it in a process where the
server, the host plugin and every other layer module are forbidden. How the server wires it in is tested in test_mcp_server.py.
Run: python3 -m unittest tests.test_mcp_core  (from services/chatbot)
"""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
import re
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
sys.path.insert(0, str(ENGINE))
import mcp_core  # noqa: E402  -- deliberately not the server

CORE = json.loads((ENGINE / "core_modules.json").read_text(encoding="utf-8"))["core"]
LAYERS = sorted(p.stem for p in ENGINE.glob("*.py") if p.stem not in CORE and p.stem != "mcp_core")
SECRET = __import__("re").compile(r"(?i)api[_-]?key\s*[:=]")

SCENARIO = r'''
import importlib.abc, json, re, sys, tempfile
from pathlib import Path

code, layers = sys.argv[1], json.loads(sys.argv[2])
sys.path.insert(0, code)


class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".")[0] in layers:
            raise ImportError("layer module imported by the adapters: " + fullname)


sys.meta_path.insert(0, Block())
import mcp_core

data = Path(tempfile.mkdtemp())
(data / "sessions" / "s1").mkdir(parents=True)
(data / "sessions" / "s1" / "events.jsonl").write_text('{"event":"a"}\n{"event":"b"}\n', encoding="utf-8")
secret = re.compile(r"api_key\s*=")
out = []
r = mcp_core.call("memory", {"action": "add", "text": "커피는 아메리카노"}, data, secret); out.append(r["success"])
r = mcp_core.call("memory", {"action": "search", "query": "커피"}, data, secret); out.append(len(r["data"]["hits"]) == 1)
r = mcp_core.call("observation", {"action": "add", "title": "T", "body": "B"}, data, secret); out.append(r["success"])
r = mcp_core.call("observation", {"action": "list"}, data, secret); out.append(len(r["data"]["observations"]) == 1)
r = mcp_core.call("ticket", {"action": "propose", "title": "T", "target": "x", "evidence": ["event:s1#2"]}, data, secret); out.append(r["success"])
r = mcp_core.call("ticket", {"action": "approve", "id": 1}, data, secret); out.append(not r["success"])
loaded = [m for m in sys.modules if m in layers]
print(json.dumps({"ok": out, "layers_loaded": loaded}))
'''


class AdapterModuleTest(unittest.TestCase):
    def test_definitions_match_the_names_it_serves(self):
        self.assertEqual([t["name"] for t in mcp_core.TOOL_DEFS], list(mcp_core.NAMES))
        enums = {t["name"]: t["inputSchema"]["properties"]["action"]["enum"] for t in mcp_core.TOOL_DEFS}
        self.assertEqual(enums["memory"], ["show", "search", "add", "forget"])
        self.assertEqual(enums["observation"], ["add", "list", "get", "resolve", "review", "reviewed"])
        self.assertEqual(enums["ticket"], ["propose", "list", "get", "claim", "note", "release"])
        json.dumps(mcp_core.TOOL_DEFS)  # what goes over the wire

    def test_it_runs_with_the_server_and_every_other_layer_forbidden(self):
        r = subprocess.run([sys.executable, "-c", SCENARIO, str(CODE), json.dumps(LAYERS)], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(res["ok"], [True] * 6)
        self.assertEqual(res["layers_loaded"], [])
        for server in ("mcp_server", "nas_mcp_host"):
            self.assertIn(server, LAYERS)  # the things being kept out are really there to keep out

    def test_only_the_standard_library_and_the_core_are_imported(self):
        tree = ast.parse((ENGINE / "mcp_core.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "pathlib", "typing"} | set(CORE))
        source = (ENGINE / "mcp_core.py").read_text(encoding="utf-8")
        for name in ("mcp_server", "nas_mcp_host"):
            self.assertNotIn(name, source)

    def test_an_unknown_tool_or_a_failing_core_is_an_envelope_not_a_crash(self):
        data = Path(tempfile.mkdtemp())
        r = mcp_core.call("delete_everything", {}, data, SECRET)
        self.assertEqual((r["success"], r["message"]), (False, "unknown tool: delete_everything"))
        saved = mcp_core.memory_store
        try:
            class Boom:
                MemoryRefused = ValueError

                @staticmethod
                def read(*a):
                    raise RuntimeError("disk on fire")
            mcp_core.memory_store = Boom
            r = mcp_core.call("memory", {"action": "show"}, data, SECRET)
            self.assertFalse(r["success"])
            self.assertIn("disk on fire", r["message"])
        finally:
            mcp_core.memory_store = saved

    def test_the_hosts_secret_pattern_is_what_decides(self):
        data = Path(tempfile.mkdtemp())
        self.assertFalse(mcp_core.call("memory", {"action": "add", "text": "api_key = 1"}, data, SECRET)["success"])
        never = __import__("re").compile(r"(?!x)x")  # a host that forbids nothing
        self.assertTrue(mcp_core.call("memory", {"action": "add", "text": "api_key = 1"}, data, never)["success"])

    def test_the_envelope_has_the_servers_shape(self):
        self.assertEqual(mcp_core.envelope(True, "m", {"a": 1}), {"success": True, "message": "m", "data": {"a": 1}})
        self.assertEqual(set(mcp_core.envelope(False, "x")), {"success", "message", "data"})



class TicketListTest(unittest.TestCase):
    """live 2026-10-05: an unfiltered list was all 652 tickets (180 KB), and status "open" matched nothing."""
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        d = self.data / "workspace" / "skill-observations" / "tickets"
        d.mkdir(parents=True)
        for i in range(1, 31):
            status = {1: "proposed", 2: "in_progress"}.get(i, "done")
            (d / ("%04d.json" % i)).write_text(json.dumps({"id": i, "title": "t%d" % i, "target": "x", "status": status,
                                                           "attempts": 0, "gate_failures": 0, "updated": ""}))

    def list(self, **args):
        r = mcp_core.call("ticket", {"action": "list", **args}, self.data, SECRET)
        self.assertTrue(r["success"], r)
        return r

    def test_open_is_every_state_not_closed(self):
        self.assertEqual([t["id"] for t in self.list(status="open")["data"]["tickets"]], [1, 2])
        self.assertEqual(len(self.list(status="done")["data"]["tickets"]), 28)

    def test_an_unfiltered_list_is_the_open_ones_and_the_latest(self):
        r = self.list()
        ids = [t["id"] for t in r["data"]["tickets"]]
        self.assertEqual(ids[:2], [1, 2])
        self.assertEqual(ids[2:], list(range(11, 31)))                  # the latest 20, no repeats
        self.assertIn("30 tickets", r["message"])


class PrivateSessionTest(unittest.TestCase):
    def test_a_private_session_cannot_touch_work_memory_observations_or_tickets(self):
        import mcp_core
        for name, args in (("memory", {"action": "show"}), ("memory", {"action": "add", "text": "x"}),
                           ("observation", {"action": "list"}), ("ticket", {"action": "list"})):
            r = mcp_core.call(name, args, Path(tempfile.mkdtemp()), re.compile("SECRET"), private=True)
            self.assertFalse(r["success"], name)
            self.assertIn("private session", r["message"])


if __name__ == "__main__":
    unittest.main()
