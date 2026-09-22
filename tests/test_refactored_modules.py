"""Unit tests for newly extracted modular components:
- standby_pool.py
- artifact_manager.py
- session_weights.py
- workspace_status.py
"""
import json
import tempfile
import unittest
from pathlib import Path

import artifact_manager
import session_weights
import standby_pool
import workspace_status


class StandbyPoolTest(unittest.TestCase):
    def test_standby_pool_instantiation(self):
        pool = standby_pool._StandbyPool()
        self.assertIsNone(pool._proc)
        self.assertIsNone(pool._conv_id)
        # try_take returns (None, None) when empty
        proc, cid = pool.try_take()
        self.assertIsNone(proc)
        self.assertIsNone(cid)


class ArtifactManagerTest(unittest.TestCase):
    def test_safe_session_id(self):
        self.assertEqual(artifact_manager._safe_session_id("20260920-123456-abc123"), "20260920-123456-abc123")
        with self.assertRaises(ValueError):
            artifact_manager._safe_session_id("../etc/passwd")
        with self.assertRaises(ValueError):
            artifact_manager._safe_session_id("invalid sid!")

    def test_atomic_write_text(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "sub" / "test.txt"
            content = "Hello, atomic world!\nLine 2"
            artifact_manager._atomic_write_text(target, content)
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), content)


class SessionWeightsTest(unittest.TestCase):
    def test_token_accounting(self):
        history = [
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "hello", "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}},
            {"role": "user", "text": "how are you?"},
            {"role": "assistant", "text": "great", "usage": {"input_tokens": 180, "output_tokens": 40, "total_tokens": 220}},
        ]
        self.assertEqual(session_weights._billed_tokens(history), 370)
        self.assertEqual(session_weights._current_context_tokens(history), 180)

    def test_is_inquiry(self):
        self.assertTrue(session_weights._is_inquiry("지금 몇 시야?"))
        self.assertTrue(session_weights._is_inquiry("어디서 확인할 수 있나요?"))
        self.assertTrue(session_weights._is_inquiry("/btw 서버 상태"))
        self.assertFalse(session_weights._is_inquiry("/q 다음 작업 실행해줘"))
        self.assertFalse(session_weights._is_inquiry("코드 작성하고 파일 저장해"))


class WorkspaceStatusTest(unittest.TestCase):
    def test_extract_yaml_desc(self):
        raw = "---\nname: my-skill\ndescription: A useful skill for testing\n---\nBody content"
        self.assertEqual(workspace_status._extract_yaml_desc(raw), "A useful skill for testing")

        no_frontmatter = "Just markdown content\nNo yaml header"
        self.assertEqual(workspace_status._extract_yaml_desc(no_frontmatter), "")

    def test_read_write_mcp_config(self):
        with tempfile.TemporaryDirectory() as td:
            orig_fn = workspace_status._mcp_config_path
            try:
                cfg_path = Path(td) / "mcp.json"
                workspace_status._mcp_config_path = lambda: cfg_path
                cfg = {"mcpServers": {"test": {"command": "node", "args": ["index.js"]}}}
                workspace_status._write_mcp_config(cfg)
                self.assertTrue(cfg_path.exists())
                read_back = workspace_status._read_mcp_config()
                self.assertEqual(read_back, cfg)
            finally:
                workspace_status._mcp_config_path = orig_fn


if __name__ == "__main__":
    unittest.main()
