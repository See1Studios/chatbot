"""NO_TICKET_WRITE_v1: a live agent's write to a repo file that no live ticket lease covers is reported at once.
Run: python3 -m unittest tests.test_unticketed_write  (from services/chatbot)
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session as S  # noqa: E402
import tickets  # noqa: E402

CTL = Path(__file__).resolve().parent.parent / "chatbot-ctl.sh"


def step(name, params, i=0):
    return {"event": "step_update", "step_update": {"step_index": i, "state": "DONE", "step_type": "tool",
            "tool_name": name, "tool_info": {"name": name, "parameters": params, "output": "ok"}}}


class UnticketedWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        (self.tmp / ".gitignore").write_text("sessions/\nworkspace/out/\n")
        (self.tmp / "workspace" / "skill-observations" / "tickets").mkdir(parents=True)
        self._saved = (S.SESSIONS, S.ROOT)
        S.SESSIONS, S.ROOT = self.tmp / "sessions", self.tmp
        (S.SESSIONS / "t").mkdir(parents=True)
        self.s = S.AgentSession("t", provider="agy")
        self.events = []
        self.s._emit = self.events.append
        self.s.save_meta = lambda: None

    def tearDown(self):
        S.SESSIONS, S.ROOT = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lease(self, paths, ttl=600):
        tickets._write_leases(self.tmp, [{"ticket": 1, "token_sha256": "x", "taken": "", "expires": time.time() + ttl,
                                          "paths": paths, "actor": ""}])

    def warned(self):
        return [e["evidence"]["path"] for e in self.events if (e.get("evidence") or {}).get("rule") == "unticketed_write"]

    def write(self, path, tool="write_to_file", key="TargetFile"):
        self.s._observe_agent_step(step(tool, {key: str(path)}))

    def test_a_write_without_a_lease_warns_once_and_leaves_a_candidate(self):
        self.write(self.tmp / "static" / "app.js")
        self.write(self.tmp / "static" / "app.js")
        self.assertEqual(self.warned(), ["static/app.js"])
        rows = (self.tmp / "workspace" / "skill-observations" / "candidates.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(r)["signal"] for r in rows], ["unticketed_write"])

    def test_a_live_lease_on_the_file_or_its_folder_covers_it(self):
        self.lease(["static/"])
        self.write(self.tmp / "static" / "app.js")
        self.lease([])                                                   # a claim naming no files takes every file
        self.write(self.tmp / "session.py")
        self.assertEqual(self.warned(), [])

    def test_an_expired_or_unrelated_lease_does_not_cover_it(self):
        self.lease(["static/app.js"], ttl=-1)
        self.write(self.tmp / "static" / "app.js")
        self.lease(["static/app"])
        self.write(self.tmp / "static" / "app-session.js")
        self.assertEqual(self.warned(), ["static/app.js", "static/app-session.js"])

    def test_ignored_files_and_files_outside_the_repo_are_not_governed(self):
        self.write(self.tmp / "workspace" / "out" / "story.md")
        self.write(Path(tempfile.gettempdir()) / "elsewhere.txt")
        self.assertEqual(self.warned(), [])

    def test_reads_and_commands_are_not_writes(self):
        self.write(self.tmp / "static" / "app.js", tool="view_file", key="AbsolutePath")
        self.write(self.tmp / "static" / "app.js", tool="run_command", key="Cwd")
        self.assertEqual(self.warned(), [])

    def test_other_tool_shapes_and_relative_paths_are_understood(self):
        self.write(self.tmp / "session.py", tool="Edit", key="file_path")
        self.write("characters/c/card.json", tool="replace_file_content")
        self.assertEqual(self.warned(), ["session.py", "workspace/characters/c/card.json"])

    def test_the_restart_guard_also_covers_static_ui_and_the_dev_charter(self):
        text = CTL.read_text(encoding="utf-8")
        guard = text[text.index("guard_tickets() {"):text.index("guard_tickets OK (active ticket")]
        self.assertIn('"static/"', guard)
        self.assertIn('"templates/dev-workspace/"', guard)   # uds/F: the dev charter and packs; cards are user data


if __name__ == "__main__":
    unittest.main()
