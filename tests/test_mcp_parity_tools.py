"""Tools HTTP brains get so they work like CLI brains (PARITY_TOOLS_v1, mcp_server.py, api-adapter-parity.md):
edit_file (Claude's Edit contract: one exact match, or replace_all; write_file's rules), find_files (glob under an
allowlisted directory, secret names skipped) and skill (list, load). Scratch directories, no network.
Run: python3 -m unittest tests.test_mcp_parity_tools  (from services/chatbot)
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# the same import environment as test_mcp_server, whichever of the two loads the server first in a run
os.environ.setdefault("NAS_MCP_HOST_PLUGIN", "1")
os.environ.setdefault("CHATBOT_EDITION", "dev")
import mcp_parity  # noqa: E402
import mcp_server as mcp  # noqa: E402


class ParityTools(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.patches = [mock.patch.object(mcp, "_allow_roots", return_value=[self.tmp]),
                        mock.patch.object(mcp, "_read_roots", return_value=[self.tmp]),
                        mock.patch.object(mcp_parity, "_skills_dir", return_value=self.tmp / "skills")]
        for p in self.patches:
            p.start()
        self.f = self.tmp / "notes.md"
        self.f.write_text("alpha\nbeta\nalpha\n", encoding="utf-8")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, tool, **args):
        return mcp.call_tool(tool, args)

    def test_edit_replaces_one_exact_match(self):
        r = self.call("edit_file", path=str(self.f), old_string="beta", new_string="gamma")
        self.assertTrue(r["success"], r)
        self.assertEqual(self.f.read_text(), "alpha\ngamma\nalpha\n")

    def test_edit_refuses_an_ambiguous_or_missing_match_unless_asked(self):
        r = self.call("edit_file", path=str(self.f), old_string="alpha", new_string="A")
        self.assertFalse(r["success"])
        self.assertIn("2 times", r["message"])
        self.assertFalse(self.call("edit_file", path=str(self.f), old_string="zeta", new_string="z")["success"])
        r = self.call("edit_file", path=str(self.f), old_string="alpha", new_string="A", replace_all=True)
        self.assertEqual((r["success"], r["data"]["replacements"]), (True, 2))
        self.assertEqual(self.f.read_text(), "A\nbeta\nA\n")

    def test_edit_keeps_write_files_rules(self):
        outside = Path(tempfile.mkdtemp()) / "x.md"
        outside.write_text("beta")
        try:
            self.assertFalse(self.call("edit_file", path=str(outside), old_string="beta", new_string="b")["success"])
        finally:
            shutil.rmtree(outside.parent, ignore_errors=True)
        fake = 'api_key = "sk-abcdefghijklmnopqrstuvwxyz0123"'   # pragma: allowlist secret -- must be refused
        r = self.call("edit_file", path=str(self.f), old_string="beta", new_string=fake)
        self.assertFalse(r["success"])
        self.assertIn("beta", self.f.read_text(), "nothing written on a refusal")

    def test_find_files_globs_and_skips_secrets(self):
        (self.tmp / "a" / "b").mkdir(parents=True)
        (self.tmp / "a" / "b" / "c.md").write_text("x")
        (self.tmp / "a" / ".env").write_text("x")
        (self.tmp / ".git").mkdir()
        (self.tmp / ".git" / "d.md").write_text("x")
        r = self.call("find_files", path=str(self.tmp), pattern="**/*.md")
        names = sorted(Path(p).name for p in r["data"]["files"])
        self.assertEqual(names, ["c.md", "notes.md"])
        self.assertFalse(self.call("find_files", path=str(self.tmp), pattern="../*")["success"])
        self.assertFalse(self.call("find_files", path="/etc", pattern="*")["success"])

    def test_skills_list_and_load(self):
        d = self.tmp / "skills" / "character-art"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: character-art\ndescription: >\n  Image format.\n  Read first.\nx: 1\n---\nBody")
        (d / "references").mkdir()
        (d / "references" / "a.md").write_text("ref")
        r = self.call("skill", action="list")
        self.assertEqual(r["data"]["skills"], [{"name": "character-art", "description": "Image format. Read first."}])
        r = self.call("skill", action="load", name="character-art")
        self.assertTrue(r["data"]["content"].endswith("Body"))
        self.assertEqual(r["data"]["files"], ["references/a.md"])
        self.assertFalse(self.call("skill", action="load", name="../x")["success"])
        self.assertFalse(self.call("skill", action="load", name="nope")["success"])


if __name__ == "__main__":
    unittest.main()
