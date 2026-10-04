"""ROLE_TOOLS_v1 (docs/plans/director-handoff.md dir/A): a character whose every role says `repo: none` (the lead)
does not read or change engine code. Engine path tools refuse it; its own provider tool steps stop the turn.
Run: python3 -m unittest tests.test_role_guard  (from services/chatbot)
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import mcp_server as M  # noqa: E402
import role_guard as R  # noqa: E402
import write_guard as W  # noqa: E402

ROLES = {"lead": "none", "dev": "", "plan": ""}
HOLDERS = {"nono": ["lead"], "coco": ["dev", "plan"], "both": ["lead", "dev"], "loose": []}


class FakeCharacters:
    @staticmethod
    def roles_of(cid, ws=None):
        return HOLDERS.get(cid, [])

    @staticmethod
    def role_pack(role, ws=None):
        return {"role": role, "repo": ROLES.get(role, "")}


class FakeSession:
    def __init__(self, character, own=True):
        self.character, self.adapter, self.stops = character, SimpleNamespace(own_tool_steps=own), []

    def _auto_stop(self, event, hint):
        self.stops.append((event, hint))


class RoleGuard(unittest.TestCase):
    def setUp(self):
        self.saved = R.characters
        R.characters = FakeCharacters

    def tearDown(self):
        R.characters = self.saved

    def test_code_is_everything_in_the_repo_but_docs(self):
        self.assertEqual(R.code_path(str(ROOT / "session.py"), ROOT), "session.py")
        self.assertEqual(R.code_path("static/app.js", ROOT), "static/app.js")
        self.assertEqual(R.code_path(str(ROOT / "docs" / "plans" / "x.md"), ROOT), "")
        self.assertEqual(R.code_path(str(ROOT / "AGENTS.md"), ROOT), "")
        self.assertEqual(R.code_path(str(ROOT), ROOT), "")                    # listing the repo root is fine
        self.assertEqual(R.code_path("/tmp/elsewhere.py", ROOT), "")

    def test_only_a_character_whose_every_role_is_hands_off_is_kept_off_code(self):
        self.assertTrue(R.hands_off("nono"))
        self.assertFalse(R.hands_off("coco"))
        self.assertFalse(R.hands_off("both"))                                 # holding dev too: hands on
        self.assertFalse(R.hands_off("loose"))                                # no roles (shipped build): nothing
        self.assertFalse(R.hands_off(""))

    def test_an_engine_path_tool_is_refused_with_one_line(self):
        line = R.refusal("nono", str(ROOT / "session.py"), ROOT)
        self.assertIn("session.py is engine code", line)
        self.assertIn("delegate", line)
        self.assertEqual(R.refusal("nono", str(ROOT / "docs" / "CONCEPT.md"), ROOT), "")
        self.assertEqual(R.refusal("coco", str(ROOT / "session.py"), ROOT), "")

    def test_a_provider_tool_step_on_code_stops_the_turn(self):
        s = FakeSession("nono")
        self.assertTrue(R.check_step(s, "view_file", {"AbsolutePath": str(ROOT / "tools" / "worktree_runner.py")}, ROOT))
        event, hint = s.stops[0]
        self.assertEqual(event["evidence"], {"rule": "role_repo_none", "tool": "view_file",
                                             "path": "tools/worktree_runner.py"})
        self.assertIn("hand it to the dev role", hint)
        self.assertFalse(R.check_step(s, "view_file", {"AbsolutePath": str(ROOT / "docs" / "DEVLOG.md")}, ROOT))
        self.assertFalse(R.check_step(FakeSession("coco"), "view_file", {"AbsolutePath": str(ROOT / "a.py")}, ROOT))

    def test_steps_that_may_be_a_subagents_are_not_judged(self):
        # grok streams a subagent's read_file as the parent's own (dir/C): the lead may have a subagent read code
        s = FakeSession("nono", own=False)
        self.assertFalse(R.check_step(s, "read_file", {"target_file": str(ROOT / "session.py")}, ROOT))
        self.assertEqual(s.stops, [])

    def test_the_session_hook_runs_the_role_check_first(self):
        s = FakeSession("nono")
        W.check(s, "view_file", {"AbsolutePath": str(ROOT / "session.py")}, ROOT)
        self.assertEqual(len(s.stops), 1)

    def test_mcp_path_tools_refuse_a_hands_off_caller(self):
        # the tool server is its own process: it learns the caller from the chat host (mcp_caller.caller)
        saved = M.mcp_caller.caller
        M.mcp_caller.caller = lambda host_get, port: {"id": "s1", "character": "nono"}
        try:
            out = M.call_tool("read_file", {"path": str(ROOT / "session.py")})
            self.assertFalse(out["success"])
            self.assertIn("engine code", str(out))
            self.assertNotIn("engine code", M._call_refusal("run_command", {"command": "cat session.py"}))   # not judged
            M.mcp_caller.caller = lambda host_get, port: {}                         # unknown caller: not refused here
            self.assertEqual(M._call_refusal("read_file", {"path": str(ROOT / "session.py")}), "")
        finally:
            M.mcp_caller.caller = saved

    def test_the_edition_boundary_still_comes_first(self):
        self.assertIn("shipped build", R.tool_refusal("run_command", {}, True, dict, Path, ROOT))

    def test_adapters_say_whether_their_tool_steps_are_their_own(self):
        from providers.adapter_base import AgentAdapter
        from providers.adapter_grok import GrokAdapter
        self.assertTrue(AgentAdapter.own_tool_steps)
        self.assertFalse(GrokAdapter.own_tool_steps)


class RolePackField(unittest.TestCase):
    def test_role_packs_read_the_repo_field_and_the_lead_template_sets_it(self):
        ws = Path(tempfile.mkdtemp())
        try:
            (ws / "roles" / "lead").mkdir(parents=True)
            (ws / "roles" / "lead" / "ROLE.md").write_text("---\ntitle: L\nrepo: None\n---\n\nbody\n", encoding="utf-8")
            self.assertEqual(C.role_pack("lead", ws)["repo"], "none")
            self.assertEqual(C.role_pack("missing", ws)["repo"], "")
        finally:
            shutil.rmtree(ws, ignore_errors=True)
        tpl = ROOT / "templates" / "dev-workspace"
        self.assertEqual(C.role_pack("lead", tpl)["repo"], "none")
        self.assertEqual(C.role_pack("dev", tpl)["repo"], "")


if __name__ == "__main__":
    unittest.main()
