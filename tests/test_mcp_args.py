"""MCP_ARGS_v1 (engine-decides ed/A1): every case here is a call that was refused live (logs/events.jsonl,
2026-09-23..10-03) and now reaches its tool in the schema's shape -- and what must stay refused stays refused."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mcp_args  # noqa: E402

ACT = lambda *a: {"type": "string", "enum": list(a)}
S, A = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
SCHEMAS = {
    "memory": {"action": ACT("show", "search", "add", "forget"), "text": S, "query": S, "section": S},
    "ticket": {"action": ACT("propose", "list", "get", "claim", "note", "release"), "id": {"type": "integer"},
               "title": S, "target": S, "text": S, "paths": A},
    "delegate": {"action": ACT("plan", "start", "status"), "title": S, "paths": A, "instruction": S,
                 "tasks": {"type": "array", "items": {"type": "object", "properties": {
                     "role": S, "title": S, "instruction": S, "paths": A}}}},
    "run_command": {"cmd": S},
    "search_text": {"path": S, "pattern": S},
    "service_ctl": {"action": ACT("start", "stop", "restart", "status"), "name": S},
    "wiki": {"action": ACT("search", "get", "sources"), "query": S, "id": S},
}


def norm(name, args):
    return mcp_args.normalize(name, args, {"inputSchema": {"properties": SCHEMAS[name]}})


class LiveRefusals(unittest.TestCase):
    def test_a_wrapped_call_is_unwrapped(self):
        got, ch = norm("memory", {"Arguments": "{'action': 'add', 'text': 'x'}", "ServerName": "nas", "ToolName": "memory"})
        self.assertEqual(got, {"action": "add", "text": "x"})
        self.assertIn("unwrapped Arguments", ch)
        got, _ = norm("run_command", {"Arguments": "{'cmd': 'ls -la data'}", "ServerName": "nas", "ToolName": "run_command"})
        self.assertEqual(got, {"cmd": "ls -la data"})

    def test_a_wrapped_bare_action_and_a_capitalised_key(self):
        got, _ = norm("service_ctl", {"Arguments": "status", "ServiceName": "chatbot"})
        self.assertEqual(got, {"action": "status", "name": "chatbot"})
        got, _ = norm("ticket", {"Action": "status"})
        self.assertEqual(got, {"action": "list"})

    def test_action_words_models_use(self):
        self.assertEqual(norm("ticket", {"action": "show", "id": 112})[0]["action"], "get")
        self.assertEqual(norm("wiki", {"action": "read", "id": "Home"})[0]["action"], "get")
        self.assertEqual(norm("wiki", {"action": "list"})[0]["action"], "sources")

    def test_a_missing_action_is_read_from_what_was_given(self):
        got, ch = norm("memory", {"category": "user", "fact": "x"})
        self.assertEqual((got["action"], got["text"]), ("add", "x"))
        self.assertEqual(norm("memory", {"category": "user", "query": "공항"})[0]["action"], "search")
        self.assertEqual(norm("ticket", {"title": "t", "target": "x"})[0]["action"], "propose")
        self.assertEqual(norm("ticket", {"action": "ticket", "title": "t"})[0]["action"], "propose")   # the tool's name
        self.assertEqual(norm("ticket", {"category": "open"})[0]["action"], "list")

    def test_other_key_names(self):
        self.assertEqual(norm("run_command", {"command": "git status"})[0], {"cmd": "git status"})
        self.assertEqual(norm("search_text", {"path": "p", "query": "thought"})[0], {"path": "p", "pattern": "thought"})

    def test_arrays_sent_as_text(self):
        got, _ = norm("ticket", {"action": "claim", "id": 79, "paths": "['data/workspace/AGENTS.md']"})
        self.assertEqual(got["paths"], ["data/workspace/AGENTS.md"])
        got, _ = norm("delegate", {"action": "plan", "title": "t",
                                   "tasks": "['{\"instruction\": \"do\", \"paths\": [\"a.md\"], \"role\": \"dev\", \"title\": \"x\"}']"})
        self.assertEqual(got["tasks"], [{"instruction": "do", "paths": ["a.md"], "role": "dev", "title": "x"}])
        got, ch = norm("delegate", {"action": "plan", "title": "t",
                                    "tasks": "[{'description': 'extend args', 'name': 'args', 'role': 'dev'}]"})
        self.assertEqual(got["tasks"], [{"instruction": "extend args", "title": "args", "role": "dev"}])


class Bounds(unittest.TestCase):
    def test_operator_steps_stay_unknown(self):
        for word in ("approve", "run", "land", "merge", "discard"):
            self.assertEqual(norm("delegate", {"action": word})[0]["action"], word)
            self.assertEqual(norm("ticket", {"action": word, "id": 1})[0]["action"], word)

    def test_the_schemas_own_key_wins_and_a_clean_call_is_untouched(self):
        got, ch = norm("search_text", {"path": "p", "pattern": "a", "query": "b"})
        self.assertEqual(got, {"path": "p", "pattern": "a", "query": "b"})
        self.assertEqual(ch, [])
        got, ch = norm("memory", {"action": "show"})
        self.assertEqual((got, ch), ({"action": "show"}, []))

    def test_no_schema_no_change(self):
        self.assertEqual(mcp_args.normalize("x", {"Action": "Y"}, None), ({"Action": "Y"}, []))
        self.assertEqual(mcp_args.normalize("x", "junk", {}), ({}, []))

    def test_text_that_is_not_a_literal_stays_text(self):
        got, _ = norm("ticket", {"action": "propose", "title": "[a] b", "target": "x"})
        self.assertEqual(got["title"], "[a] b")


if __name__ == "__main__":
    unittest.main()
