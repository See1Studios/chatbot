"""Roles make a director better, not fenced (operator 2026-10-05). ROLE_TOOLS_v1's stops are off: a role's own tool
steps on code are not stopped, and what stays is the edition boundary and the tool server's per-caller scope. Every
skill a role pack names exists, so a role's `skills:` line equips it.
Run: engine/run-tests.sh test_role_guard
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import characters as C  # noqa: E402
import mcp_server  # noqa: E402
import personal_turn  # noqa: E402
import role_guard as R  # noqa: E402
import write_guard as W  # noqa: E402

TEMPLATES = (ROOT / "templates" / "dev-workspace", ROOT / "templates" / "workspace")


class Roles(unittest.TestCase):
    def test_a_role_is_not_stopped_for_reading_code(self):
        stops = []
        s = SimpleNamespace(character="any", adapter=SimpleNamespace(), _auto_stop=lambda event, hint: stops.append(event))
        W.check(s, "view_file", {"AbsolutePath": str(ENGINE / "session.py")}, ROOT)
        self.assertEqual(stops, [])
        self.assertFalse(hasattr(R, "check_step"))

    def test_the_edition_boundary_and_the_per_caller_scope_stay(self):
        self.assertIn("shipped build", R.tool_refusal("run_command", {}, True))
        self.assertEqual(R.tool_refusal("read_file", {"path": "session.py"}, False, None, None, None), "")
        busy = [{"id": "s1", "mode": "work", "turn": None, "tools": ["delegate"]}]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(R.live_scope(busy, "delegate", Path(d)), (False, False))
            self.assertEqual(R.live_scope(busy, "web", Path(d)), (False, True))   # TEAM_ROLES_v2: no grant

    def test_every_skill_a_role_names_exists(self):
        for root in (ROOT / "templates" / "dev-workspace",):
            for role_md in sorted((root / "roles").glob("*/ROLE.md")):
                for skill in C.role_pack(role_md.parent.name, root)["skills"]:
                    found = [t for t in TEMPLATES if (t / ".agents" / "skills" / skill / "SKILL.md").is_file()]
                    self.assertTrue(found, "%s names skill %r, which no template has" % (role_md.parent.name, skill))

    def test_the_directors_are_equipped(self):
        tpl = ROOT / "templates" / "dev-workspace"
        self.assertEqual(C.role_pack("lead", tpl)["skills"], ["progress-report", "handoff-brief"])
        self.assertEqual(C.role_pack("dev", tpl)["skills"], ["subagent-investigate"])
        self.assertEqual(C.role_pack("plan", tpl)["skills"], ["plan-doc"])
        lead = (tpl / "roles" / "lead" / "ROLE.md").read_text(encoding="utf-8")
        self.assertNotIn("repo: none", lead)
        self.assertNotIn("engine stops", lead)
        for role in ("dev", "plan", "scout"):
            self.assertIn("handoff-brief", C.role_pack(role, tpl)["text"], role)

    def test_caller_session_isolation_from_concurrent_private_session(self):
        busy = [
            {"id": "p1", "mode": "private", "turn": None, "tools": []},
            {"id": "w1", "mode": "work", "turn": None, "tools": ["delegate"]},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            # Caller is the work session: not closed despite concurrent private session
            self.assertEqual(R.live_scope(busy, "delegate", p, {"id": "w1", "mode": "work"}), (False, False))
            self.assertEqual(R.live_scope(busy, "web", p, {"id": "w1", "mode": "work"}), (False, True))
            # Caller is the private session: closed
            self.assertEqual(R.live_scope(busy, "delegate", p, {"id": "p1", "mode": "private"}), (True, False))

    def test_caller_session_isolation_from_personal_turn(self):
        busy = [
            {"id": "w1", "mode": "work", "turn": 1000.0, "tools": ["delegate"]},
            {"id": "w2", "mode": "work", "turn": 2000.0, "tools": ["delegate"]},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "w1").mkdir()
            (p / "w2").mkdir()
            self.assertTrue(personal_turn.mark(p, "w1", 1000.0))
            # w2 is not affected by w1's marked personal turn
            self.assertEqual(R.live_scope(busy, "delegate", p, {"id": "w2", "mode": "work"}), (False, False))
            # w1 is closed for work tools during its marked turn
            self.assertEqual(R.live_scope(busy, "delegate", p, {"id": "w1", "mode": "work"}), (True, False))

    def test_fail_open_mitigation_on_busy_lookup_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            # When host busy lookup returns empty (failure), private caller is still closed
            self.assertEqual(R.live_scope([], "delegate", p, {"id": "p1", "mode": "private"}), (True, False))
            self.assertEqual(R.live_scope([], "delegate", p, {"id": "p1", "private": True}), (True, False))
            # Work caller with tools provided is evaluated safely
            caller = {"id": "w1", "mode": "work", "tools": ["delegate"]}
            self.assertEqual(R.live_scope([], "delegate", p, caller), (False, False))
            self.assertEqual(R.live_scope([], "web", p, caller), (False, True))

    def test_fallback_when_caller_unidentified(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            busy_priv = [{"id": "p1", "mode": "private", "turn": None, "tools": []}]
            self.assertEqual(R.live_scope(busy_priv, "delegate", p, {}), (True, False))
            self.assertEqual(R.live_scope(busy_priv, "delegate", p, None), (True, False))
            busy_work = [{"id": "w1", "mode": "work", "turn": None, "tools": ["delegate"]}]
            self.assertEqual(R.live_scope(busy_work, "delegate", p, {}), (False, False))
            self.assertEqual(R.live_scope(busy_work, "web", p, {}), (False, True))

    def test_mcp_server_live_scope_passes_caller(self):
        busy = [
            {"id": "p1", "mode": "private", "turn": None, "tools": []},
            {"id": "w1", "mode": "work", "turn": None, "tools": ["delegate"]},
        ]
        with mock.patch.object(mcp_server, "_busy_sessions", return_value=busy):
            with mock.patch("mcp_caller.caller", return_value={"id": "w1", "mode": "work"}):
                self.assertEqual(mcp_server._live_scope("delegate"), (False, False))
                self.assertEqual(mcp_server._live_scope("web"), (False, True))
            with mock.patch("mcp_caller.caller", return_value={"id": "p1", "mode": "private"}):
                self.assertEqual(mcp_server._live_scope("delegate"), (True, False))

    def test_live_scope_reads_meta_json_when_caller_mode_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            s_priv = p / "s_priv"
            s_priv.mkdir()
            (s_priv / "meta.json").write_text(json.dumps({"mode": "private"}), encoding="utf-8")
            self.assertEqual(R.live_scope([], "delegate", p, {"id": "s_priv"}), (True, False))

            s_work = p / "s_work"
            s_work.mkdir()
            (s_work / "meta.json").write_text(json.dumps({"mode": "work"}), encoding="utf-8")
            self.assertEqual(R.live_scope([], "delegate", p, {"id": "s_work"}), (False, False))

    def test_live_scope_fails_closed_when_meta_json_corrupted_or_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            s_bad = p / "s_bad"
            s_bad.mkdir()
            (s_bad / "meta.json").write_text("{corrupt json", encoding="utf-8")
            self.assertEqual(R.live_scope([], "delegate", p, {"id": "s_bad"}), (True, False))

            self.assertEqual(R.live_scope([], "delegate", p, {"id": "s_nonexistent"}), (True, False))

    def test_live_scope_resolves_denied_via_characters_tools_of(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            caller = {"id": "w1", "mode": "work", "character": "dev_test"}
            with mock.patch("characters.tools_of", return_value=["delegate"]):
                self.assertEqual(R.live_scope([], "delegate", p, caller), (False, False))
                self.assertEqual(R.live_scope([], "web", p, caller), (False, True))

    def test_live_scope_personal_turn_when_busy_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "w1").mkdir()
            self.assertTrue(personal_turn.mark(p, "w1", 1000.0))
            caller_marked = {"id": "w1", "mode": "work", "turn": 1000.0, "tools": ["delegate"]}
            self.assertEqual(R.live_scope([], "delegate", p, caller_marked), (True, False))

            caller_unmarked = {"id": "w1", "mode": "work", "turn": 2000.0, "tools": ["delegate"]}
            self.assertEqual(R.live_scope([], "delegate", p, caller_unmarked), (False, False))

    def test_mcp_server_caller_fallback_and_obs_tool_call(self):
        with mock.patch("mcp_caller.caller", side_effect=RuntimeError("connection dropped")):
            with mock.patch.object(mcp_server, "_busy_sessions", return_value=[]):
                self.assertEqual(mcp_server._live_scope("delegate"), (False, False))

                out = mcp_server._obs_tool_call("delegate", {"request": "test request"})
                self.assertIsInstance(out, dict)


if __name__ == "__main__":
    unittest.main()
