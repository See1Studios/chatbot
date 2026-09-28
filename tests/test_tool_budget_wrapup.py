"""TOOL_BUDGET_WRAPUP_v1 (providers/adapter_openai.py::OpenAIDialectAdapter.stream_turn): when a model spends every
tool round, the turn gets one more request with tool_choice "none" and the host note, so what the tools returned
becomes an answer instead of being discarded behind an error. If that request still yields no text, the cap error
stands.
Run: python3 -m unittest tests.test_tool_budget_wrapup  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import adapter_openai as A  # noqa: E402


def make(answer_on_wrapup: str):
    a = A.OpenAIDialectAdapter(id="t", base_url="http://x/v1", api_key_env="NONE", default_model="m")
    a.MAX_TOOL_HOPS = 3
    calls = []

    def stream_once(session, messages, tools, seq=None, tool_choice=None):
        calls.append({"tool_choice": tool_choice, "last": messages[-1]})
        if tool_choice == "none":
            return (answer_on_wrapup, {}, None, "stop", "m")
        yield from ()
        return ("", {0: {"id": "c%d" % len(calls), "name": "list_dir", "arguments": "{}"}}, None, "tool_calls", "m")

    a._stream_once = stream_once
    a.finalize_turn = lambda **kw: {"event": "result", "text": kw["text"]}
    return a, calls


def run(a):
    session = SimpleNamespace(model="m", current_text="", _turn_seq=None)
    with mock.patch.object(A, "_mcp_openai_tools", return_value=[{"type": "function"}]), \
            mock.patch.object(A, "_mcp_call_tool", return_value='{"success": true}'):
        return list(a.stream_turn(session, [{"role": "user", "content": "review"}]))


class ToolBudgetWrapup(unittest.TestCase):
    def test_the_cap_turns_into_one_answer_without_tools(self):
        a, calls = make("found three things; did not check the rest")
        events = run(a)
        self.assertEqual([c["tool_choice"] for c in calls], [None, None, None, "none"])
        self.assertEqual(calls[-1]["last"], {"role": "user", "content": a.TOOL_BUDGET_NOTE})
        self.assertEqual(events[-1], {"event": "result", "text": "found three things; did not check the rest"})
        self.assertFalse([e for e in events if e.get("event") == "error"])

    def test_no_text_on_the_last_request_keeps_the_cap_error(self):
        a, calls = make("")
        events = run(a)
        self.assertEqual(len(calls), a.MAX_TOOL_HOPS + 1)            # exactly one extra request, never more
        self.assertEqual(events[-1]["event"], "error")

    def test_a_private_turn_has_a_smaller_budget_than_a_work_turn(self):
        # PARITY_TOOLS_v1 (api-adapter-parity D3): work 40, private 8
        a = A.OpenAIDialectAdapter(id="t", base_url="http://x/v1", api_key_env="NONE", default_model="m")
        self.assertEqual((a.MAX_TOOL_HOPS, a.PRIVATE_TOOL_HOPS), (40, 8))
        self.assertEqual(a.tool_budget(SimpleNamespace(is_private=True)), 8)
        self.assertEqual(a.tool_budget(SimpleNamespace(is_private=False)), 40)
        self.assertEqual(a.tool_budget(SimpleNamespace()), 40)

    def test_tool_choice_reaches_the_request_body_only_with_tools(self):
        src = Path(A.__file__).read_text(encoding="utf-8")
        self.assertIn('body["tool_choice"] = tool_choice', src)


if __name__ == "__main__":
    unittest.main()
