"""NO_TICKET_WRITE_v1: a live agent's write to a repo file that no live ticket lease covers stops the turn at once.
TREE_WATCH_v1 (director-handoff dir/B): a change no tool step showed (a subagent's) is caught by comparing the git
working tree at the turn's start and end, and stays on hold until the file is clean or leased.
Run: engine/run-tests.sh test_unticketed_write
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import session as S  # noqa: E402
import tickets  # noqa: E402
import write_guard as W  # noqa: E402
from tests._paths import ENGINE  # noqa: E402

CTL = ENGINE / "chatbot-ctl.sh"


def step(name, params, i=0):
    return {"event": "step_update", "step_update": {"step_index": i, "state": "DONE", "step_type": "tool",
            "tool_name": name, "tool_info": {"name": name, "parameters": params, "output": "ok"}}}


class UnticketedWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        (self.tmp / ".gitignore").write_text("sessions/\nworkspace/out/\n")
        (self.tmp / "dev" / "tickets").mkdir(parents=True)
        self._saved = (S.SESSIONS, S.ROOT, S.REPO_ROOT)
        S.SESSIONS, S.ROOT, S.REPO_ROOT = self.tmp / "sessions", self.tmp / "engine", self.tmp
        (S.SESSIONS / "t").mkdir(parents=True)
        self.s = S.AgentSession("t", provider="agy")
        self.events = []
        self.s._emit = self.events.append
        self.s.save_meta = lambda: None
        W.TREE_HOLD.clear()
        # a write stops the turn; the shape tests below write several files in one test, so record the stop only
        self.s._auto_stop = lambda event, hint: (self.events.append(event), setattr(self.s, "_loop_hint", hint))

    def tearDown(self):
        S.SESSIONS, S.ROOT, S.REPO_ROOT = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lease(self, paths, ttl=600):
        tickets._write_leases(self.tmp, [{"ticket": 1, "token_sha256": "x", "taken": "", "expires": time.time() + ttl,
                                          "paths": paths, "actor": ""}])

    def warned(self):
        return [e["evidence"]["path"] for e in self.events if (e.get("evidence") or {}).get("rule") == "unticketed_write"]

    def write(self, path, tool="write_to_file", key="TargetFile"):
        self.s._observe_agent_step(step(tool, {key: str(path)}))

    def test_a_write_without_a_lease_warns_once_and_logs_it(self):
        logged = []
        with mock.patch.object(W.obslog, "event", side_effect=lambda evt, **kw: logged.append((evt, kw.get("path")))):
            self.write(self.tmp / "static" / "app.js")
            self.write(self.tmp / "static" / "app.js")
        self.assertEqual(self.warned(), ["static/app.js"])
        self.assertEqual(logged, [("guard.unticketed_write", "static/app.js")])   # telemetry, not a candidate (il/A)

    def test_a_live_lease_on_the_file_or_its_folder_covers_it(self):
        self.lease(["static/"])
        self.write(self.tmp / "static" / "app.js")
        self.lease([])                                                   # a claim naming no files takes every file
        self.write(self.tmp / "session.py")
        self.assertEqual(self.warned(), [])

    def test_a_claimed_engine_file_is_covered_by_its_repo_path(self):
        # WRITE_GUARD_REPO_v1 (#796): tickets name `engine/delegation.py`; the guard compared `delegation.py` (relative
        # to the engine folder) and stopped a claimed write (#795, 2026-10-08)
        self.lease(["engine/delegation.py"])
        self.write(self.tmp / "engine" / "delegation.py")
        self.assertEqual(self.warned(), [])
        self.write(self.tmp / "engine" / "session.py")
        self.assertEqual(self.warned(), ["engine/session.py"])

    def test_the_guard_is_given_the_repo_root(self):
        import repo_layout
        self.assertEqual(self._saved[2], repo_layout.REPO)
        src = (Path(S.__file__)).read_text(encoding="utf-8") + (Path(S.__file__).parent / "session_turn.py").read_text(encoding="utf-8")
        for call in ("write_guard.check(self, name, params, REPO_ROOT)", "write_guard.turn_end(self, REPO_ROOT, outcome)",
                     "write_guard.turn_start(self, _s().REPO_ROOT)"):
            self.assertIn(call, src)
        self.assertNotRegex(src, r"write_guard\.\w+\([^)]*\bROOT\b", "no guard call gets the engine folder")

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
        self.assertEqual(self.warned(), ["session.py", "characters/c/card.json"])

    def test_a_real_workspace_dir_still_takes_a_relative_write(self):
        (self.tmp / "workspace").mkdir()
        self.write("characters/c/card.json")
        self.assertEqual(self.warned(), ["workspace/characters/c/card.json"])
        self.events.clear()
        self.s._unticketed_warned.clear()
        (self.tmp / "workspace").rmdir()
        (self.tmp / "workspace").symlink_to(".", target_is_directory=True)
        self.write("roles/dev/ROLE.md")
        self.assertEqual(self.warned(), ["roles/dev/ROLE.md"])

    def test_a_visible_write_stops_the_turn_and_tells_the_agent_why(self):
        del self.s._auto_stop                                           # the real stop, this time
        self.s.stop = lambda notify=True: None
        self.write(self.tmp / "static" / "app.js")
        stopped = [e for e in self.events if e.get("event") == "stopped"]
        self.assertEqual(len(stopped), 1)
        self.assertIn("static/app.js", self.s._loop_hint)

    # ---- TREE_WATCH_v1 ----
    def git(self, *a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(self.tmp), check=True,
                       capture_output=True)

    def committed(self):
        (self.tmp / "a.py").write_text("one\n")
        (self.tmp / "old.md").write_text("x\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")

    def held(self):
        return [p for e in self.events if (e.get("evidence") or {}).get("rule") == "unticketed_tree_change"
                for p in e["evidence"]["paths"]]

    def test_a_change_no_tool_step_showed_is_caught_at_the_turn_end_and_held(self):
        self.committed()
        (self.tmp / "dirty.txt").write_text("left by someone before the turn\n")
        self.assertEqual(W.turn_start(self.s, self.tmp), "")
        (self.tmp / "a.py").write_text("two\n")                       # a subagent's edit: no tool step
        (self.tmp / "new.js").write_text("x\n")
        self.assertEqual(W.turn_end(self.s, self.tmp), ["a.py", "new.js"])
        self.assertEqual(self.held(), ["a.py", "new.js"])               # not the file dirty before the turn
        line = W.turn_start(self.s, self.tmp)
        self.assertIn("a.py, new.js", line)
        self.assertEqual(W.turn_end(self.s, self.tmp), [])              # told once, not again each turn

    def test_a_hold_ends_when_the_file_is_clean_or_leased(self):
        self.committed()
        W.turn_start(self.s, self.tmp)
        (self.tmp / "a.py").write_text("two\n")
        (self.tmp / "new.js").write_text("x\n")
        W.turn_end(self.s, self.tmp)
        self.git("checkout", "--", "a.py")
        self.lease(["new.js"])
        self.assertEqual(W.turn_start(self.s, self.tmp), "")
        self.assertEqual(W.TREE_HOLD, {})

    def test_leased_ignored_renamed_and_steered_changes(self):
        self.committed()
        self.lease(["a.py"])
        W.turn_start(self.s, self.tmp)
        (self.tmp / "a.py").write_text("two\n")                       # leased
        (self.tmp / "sessions" / "t" / "x.json").write_text("{}")      # ignored
        self.git("mv", "old.md", "renamed.md")
        self.assertEqual(W.turn_end(self.s, self.tmp, "steer"), [])     # the turn goes on: compared at its real end
        self.assertEqual(W.turn_end(self.s, self.tmp), ["renamed.md"])

    def test_the_turn_hooks_run_in_a_real_turn_end(self):
        self.committed()
        W.turn_start(self.s, self.tmp)
        (self.tmp / "a.py").write_text("two\n")
        self.s._finish_turn("result")
        self.assertEqual(self.held(), ["a.py"])
        src = (Path(S.__file__).parent / "session_turn.py").read_text(encoding="utf-8")
        self.assertIn("write_guard.turn_start(self, _s().REPO_ROOT)", src)

    def test_the_restart_guard_also_covers_static_ui_and_the_dev_charter(self):
        text = CTL.read_text(encoding="utf-8")
        guard = text[text.index("guard_tickets() {"):text.index("guard_tickets OK (active ticket")]
        self.assertIn('"static/"', guard)
        self.assertIn('"templates/dev-workspace/"', guard)   # uds/F: the dev charter and packs; cards are user data


if __name__ == "__main__":
    unittest.main()
