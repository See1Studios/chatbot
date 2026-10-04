"""Roles make a director better, not fenced (operator 2026-10-05). ROLE_TOOLS_v1's stops are off: a role's own tool
steps on code are not stopped, and what stays is the edition boundary and the tool server's per-caller scope. Every
skill a role pack names exists, so a role's `skills:` line equips it.
Run: python3 -m unittest tests.test_role_guard  (from services/chatbot)
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import role_guard as R  # noqa: E402
import write_guard as W  # noqa: E402

TEMPLATES = (ROOT / "templates" / "dev-workspace", ROOT / "templates" / "workspace")


class Roles(unittest.TestCase):
    def test_a_role_is_not_stopped_for_reading_code(self):
        stops = []
        s = SimpleNamespace(character="any", adapter=SimpleNamespace(), _auto_stop=lambda event, hint: stops.append(event))
        W.check(s, "view_file", {"AbsolutePath": str(ROOT / "session.py")}, ROOT)
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


if __name__ == "__main__":
    unittest.main()
