"""Unit tests for choices MCP tool (OUT_OF_BAND_CHOICES_v1 1b, ticket #145).
Verifies:
1. choices tool definition & schema
2. Validation: item count (2-4), label length (<=120), payload length (<=500), kind (say|action|command)
3. Command allowlist for command kind
4. Reflection into session event stream, disk events.jsonl, and history
5. host_config PERSISTED_LOG_KINDS inclusion

Run: engine/run-tests.sh test_choices_tool
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))

import host_config  # noqa: E402
import mcp_server as mcp  # noqa: E402


class ChoicesToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self._orig_data = mcp.DATA
        mcp.DATA = self.tmp

    def tearDown(self):
        mcp.DATA = self._orig_data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persisted_log_kinds(self):
        self.assertIn("choices", host_config.PERSISTED_LOG_KINDS)
        self.assertIn("action", host_config.PERSISTED_LOG_KINDS)

    def test_tool_defs_has_choices(self):
        defs = {t["name"]: t for t in mcp.tool_defs()}
        self.assertIn("choices", defs)
        tool = defs["choices"]
        self.assertEqual(tool["inputSchema"]["type"], "object")
        props = tool["inputSchema"]["properties"]
        self.assertIn("items", props)
        self.assertIn("action", props)
        self.assertEqual(props["action"]["enum"], ["choices"])
        self.assertIn("items", tool["inputSchema"]["required"])

    def test_validate_item_count(self):
        valid_items = [
            {"label": "선택 A", "kind": "say"},
            {"label": "선택 B", "kind": "say"},
        ]
        ok, msg, cleaned = mcp.validate_choices(valid_items)
        self.assertTrue(ok)
        self.assertEqual(len(cleaned), 2)

        # Under 2 items rejected
        ok, msg, _ = mcp.validate_choices([{"label": "하나만", "kind": "say"}])
        self.assertFalse(ok)
        self.assertIn("between 2 and 4", msg)

        # Over 4 items rejected
        too_many = [{"label": f"선택 {i}", "kind": "say"} for i in range(5)]
        ok, msg, _ = mcp.validate_choices(too_many)
        self.assertFalse(ok)
        self.assertIn("between 2 and 4", msg)

        # Non-array rejected
        ok, msg, _ = mcp.validate_choices("not a list")
        self.assertFalse(ok)

    def test_validate_label_and_kind(self):
        # Empty label rejected
        bad_label = [{"label": "", "kind": "say"}, {"label": "B", "kind": "say"}]
        ok, msg, _ = mcp.validate_choices(bad_label)
        self.assertFalse(ok)
        self.assertIn("empty label", msg)

        # Long label (>120) rejected
        long_label = [{"label": "A" * 121, "kind": "say"}, {"label": "B", "kind": "say"}]
        ok, msg, _ = mcp.validate_choices(long_label)
        self.assertFalse(ok)
        self.assertIn("exceeds 120", msg)

        # Invalid kind rejected
        bad_kind = [{"label": "A", "kind": "jump"}, {"label": "B", "kind": "say"}]
        ok, msg, _ = mcp.validate_choices(bad_kind)
        self.assertFalse(ok)
        self.assertIn("invalid kind", msg)

        # Non-dict item rejected
        ok, msg, _ = mcp.validate_choices(["string_item", {"label": "B", "kind": "say"}])
        self.assertFalse(ok)

    def test_payload_default_and_limit(self):
        items = [
            {"label": "보기 A", "kind": "say"},
            {"label": "보기 B", "kind": "action", "payload": "(고개를 끄덕인다)"},
        ]
        ok, msg, cleaned = mcp.validate_choices(items)
        self.assertTrue(ok)
        self.assertEqual(cleaned[0]["payload"], "보기 A")
        self.assertEqual(cleaned[1]["payload"], "(고개를 끄덕인다)")

        # Long payload (>500) rejected
        long_payload = [
            {"label": "A", "kind": "say", "payload": "x" * 501},
            {"label": "B", "kind": "say"},
        ]
        ok, msg, _ = mcp.validate_choices(long_payload)
        self.assertFalse(ok)
        self.assertIn("exceeds 500", msg)

    def test_command_allowlist(self):
        # Allowlisted ticket command passes
        items = [
            {"label": "승인", "kind": "command", "payload": "/ticket approve 42"},
            {"label": "취소", "kind": "say"},
        ]
        ok, msg, _ = mcp.validate_choices(items)
        self.assertTrue(ok, msg)

        # Bare ticket command passes too
        items[0]["payload"] = "ticket delegate 1"
        ok, msg, _ = mcp.validate_choices(items)
        self.assertTrue(ok, msg)

        # Slash commands pass
        for cmd in ("/help", "/status", "/clear"):
            items[0]["payload"] = cmd
            ok, msg, _ = mcp.validate_choices(items)
            self.assertTrue(ok, f"expected {cmd} to pass")

        # Disallowed command rejected
        items[0]["payload"] = "rm -rf /"
        ok, msg, _ = mcp.validate_choices(items)
        self.assertFalse(ok)
        self.assertIn("not allowlisted", msg)

        items[0]["payload"] = "/ticket hack 99"
        ok, msg, _ = mcp.validate_choices(items)
        self.assertFalse(ok)
        self.assertIn("not allowlisted", msg)

    def test_call_tool_choices(self):
        items = [
            {"label": "찬성", "kind": "say"},
            {"label": "반대", "kind": "action", "payload": "(고개를 젓는다)"},
        ]
        # Valid call
        r = mcp.call_tool("choices", {"items": items})
        self.assertTrue(r["success"])
        self.assertEqual(len(r["data"]["choices"]), 2)

        # With action parameter
        r = mcp.call_tool("choices", {"action": "choices", "items": items})
        self.assertTrue(r["success"])

        # Invalid action parameter
        r = mcp.call_tool("choices", {"action": "invalid", "items": items})
        self.assertFalse(r["success"])
        self.assertIn("unknown action", r["message"])

        # Invalid items
        r = mcp.call_tool("choices", {"items": [{"label": "하나", "kind": "say"}]})
        self.assertFalse(r["success"])

    def test_session_event_and_history_reflection(self):
        import session
        sess = session.REG.create()
        sess.history.append({"role": "assistant", "text": "선택해주세요."})
        emitted = []
        sess.subscribers.append(type("FakeQueue", (), {"put_nowait": emitted.append})())

        items = [
            {"label": "선택 1", "kind": "say"},
            {"label": "선택 2", "kind": "action", "payload": "(행동)"},
        ]
        r = mcp.call_tool("choices", {"items": items, "session_id": sess.sid})
        self.assertTrue(r["success"])

        # Emitted choices event
        choices_ev = [ev for ev in emitted if ev.get("event") == "choices"]
        self.assertEqual(len(choices_ev), 1)
        expected = [
            {"label": "선택 1", "kind": "say", "payload": "선택 1"},
            {"label": "선택 2", "kind": "action", "payload": "(행동)"},
        ]
        self.assertEqual(choices_ev[0]["choices"], expected)

        # History updated
        self.assertEqual(sess.history[-1]["choices"], expected)
        self.assertEqual(sess.current_choices, expected)

        # Cleanup
        session.REG.delete(sess.sid)


if __name__ == "__main__":
    unittest.main()
