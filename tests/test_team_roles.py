"""Every character is equal: cards carry no role; a role is a pack (roles/<role>/role.md: instructions, skills,
tool grants) and the roster (team.json) says who holds it and whom the app opens with (TEAM_ROLES_v1).
Run: python3 -m unittest tests.test_team_roles  (from services/chatbot)
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import instructions as I  # noqa: E402

PD = "---\ntitle: PD\ntools: delegate, house-memory\nskills: planning\n---\n\n# Role: PD\nYou plan and delegate.\n"
STAFF = "---\ntitle: Staff\ntools:\n---\n\n# Role: Staff\nYou do the work.\n"


class Roster(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        (self.ws / "memory").mkdir()
        (self.ws / "AGENTS.md").write_text("charter", encoding="utf-8")
        for role, text in (("pd", PD), ("staff", STAFF)):
            (self.ws / "roles" / role).mkdir(parents=True)
            (self.ws / "roles" / role / "role.md").write_text(text, encoding="utf-8")
        for skill in ("planning", "drawing"):
            (self.ws / ".agents" / "skills" / skill).mkdir(parents=True)
            (self.ws / ".agents" / "skills" / skill / "SKILL.md").write_text(
                "---\nname: %s\ndescription: %s skill\n---\n" % (skill, skill), encoding="utf-8")
        self.a, self.b, self.c = sorted(C.new_id() for _ in range(3))   # a is the oldest: the default without a roster
        C.save(self.a, C.new_card("A", "pd", description="a body"), self.ws)       # old cards with a role
        C.save(self.b, C.new_card("B", "staff", description="b body"), self.ws)
        C.save(self.c, C.new_card("Cc", description="c body"), self.ws)
        self.saved = (I.WORKSPACE, I.WS_SKILLS_DIR, I.MEMORY_FILE)
        I.WORKSPACE, I.WS_SKILLS_DIR, I.MEMORY_FILE = self.ws, self.ws / ".agents" / "skills", self.ws / "memory" / "MEMORY.md"

    def tearDown(self):
        I.WORKSPACE, I.WS_SKILLS_DIR, I.MEMORY_FILE = self.saved
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_the_old_card_roles_become_a_roster_and_leave_the_cards(self):
        self.assertEqual(C.by_role("pd", self.ws), self.a)                          # derived before migrating
        self.assertTrue(C.migrate_team(self.ws))
        self.assertFalse(C.migrate_team(self.ws))                                   # once
        team = json.loads((self.ws / "team.json").read_text(encoding="utf-8"))
        self.assertEqual(team, {"default": self.a, "members": {self.a: ["pd"], self.b: ["staff"]}})
        for cid in (self.a, self.b, self.c):
            self.assertNotIn("role", C.ext(C.load(cid, self.ws)))
        self.assertEqual({c["id"]: c["roles"] for c in C.listing(self.ws)},
                         {self.a: ["pd"], self.b: ["staff"], self.c: []})

    def test_roles_follow_the_roster_not_the_card(self):
        C.migrate_team(self.ws)
        C.save_team({"default": self.b, "members": {self.b: ["pd", "staff"], self.c: ["staff"]}}, self.ws)
        self.assertEqual(C.by_role("pd", self.ws), self.b)
        self.assertEqual(C.default_character(self.ws), self.b)
        self.assertEqual(C.tools_of(self.b, self.ws), ["delegate", "house-memory"])
        self.assertEqual(C.tools_of(self.a, self.ws), [])
        self.assertEqual(C.role_pack("pd", self.ws)["skills"], ["planning"])
        self.assertEqual(C.role_pack("nope", self.ws)["text"], "")
        self.assertIn("You do the work.", C.work_text(C.load(self.c, self.ws), self.c, self.ws))

    def test_a_missing_default_falls_back_to_the_oldest(self):
        C.save_team({"default": C.new_id(), "members": {}}, self.ws)
        self.assertEqual(C.default_character(self.ws), min(self.a, self.b, self.c))   # TypeIDs sort by time

    def test_the_default_is_a_position_not_a_role_name(self):
        # engine/A (#456, operator 2026-09-30: "roles are user data; the engine must not know them")
        C.save_team({"default": self.c, "members": {self.a: ["pd"], self.b: ["staff"], self.c: ["lead", "dev"]}},
                    self.ws)
        self.assertEqual(C.default_character(self.ws), self.c)
        self.assertEqual(C.expert_roles(self.ws), ["pd", "staff"], "a card holding a role called pd is just an expert")
        C.save_team({"default": self.a, "members": {self.a: ["staff"], self.b: ["staff"]}}, self.ws)
        self.assertEqual(C.expert_roles(self.ws), ["staff"], "a role the default also holds stays delegable to others")

    def test_without_a_roster_the_oldest_card_is_the_default_whatever_its_role(self):
        self.assertEqual(C.load_team(self.ws)["default"], self.a)
        C.save(self.a, C.new_card("A", "staff", description="a body"), self.ws)
        self.assertEqual(C.load_team(self.ws)["default"], self.a)

    def test_engine_code_names_no_role(self):
        # the enforcer of the rule above: a role id quoted in engine code is the old hardcoding coming back
        pattern = re.compile(r"""["'](pd|staff|artist|lead)["']""")
        files = sorted(list(ROOT.glob("*.py")) + list((ROOT / "tools").glob("*.py")) + list((ROOT / "providers").glob("*.py")))
        hits = ["%s:%d" % (f.name, n) for f in files
                for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
        self.assertEqual(hits, [], "engine code must not name a role (roles live in team.json and roles/)")

    def test_every_character_gets_the_same_bundle_shape(self):
        C.migrate_team(self.ws)
        pd = I.build_instruction_bundle()["text"]                                    # the default character
        self.assertIn("a body", pd)
        self.assertIn("You plan and delegate.", pd)
        self.assertIn("- planning", pd)                                               # a skill the PD pack claims
        self.assertIn("- drawing", pd)
        staff = I.build_instruction_bundle(character=self.b)["text"]
        self.assertIn("You do the work.", staff)
        self.assertNotIn("You plan and delegate.", staff)
        self.assertNotIn("- planning", staff)
        self.assertIn("- drawing", staff)
        no_role = I.NO_ROLE_NOTE.split("]")[0]   # "[No role" -- the rest names the default character (CARD_MACROS_v1)
        self.assertIn(no_role, I.build_instruction_bundle(character=self.c)["text"])
        self.assertNotIn(no_role, staff)

    def test_the_live_charter_no_longer_makes_everyone_the_pd(self):
        charter = (ROOT / "data" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("You are the PD", charter)
        self.assertNotIn("role `pd`", charter)
        pack = C.role_pack("pd", ROOT / "data" / "workspace")
        self.assertIn("delegate", pack["tools"])
        self.assertIn("You are the PD", pack["text"])


    def test_pack_files_take_the_upper_case_name_and_still_read_the_old_one(self):
        # pew/R: roles/<role>/ROLE.md and PROCEDURE.md, like SKILL.md; a pack written before keeps working
        d = self.ws / "roles" / "pd"
        self.assertEqual(C.pack_file("pd", "role", self.ws).name, "role.md")          # only the old name exists
        self.assertEqual(C.pack_file("pd", "procedure", self.ws).name, "PROCEDURE.md")  # neither: the new name
        (d / "role.md").unlink()   # first: on a case-insensitive disk (Windows, macOS) role.md IS ROLE.md (#411)
        (d / "ROLE.md").write_text(PD.replace("You plan and delegate.", "New name wins."), encoding="utf-8")
        self.assertIn("New name wins.", C.role_pack("pd", self.ws)["text"])
        self.assertEqual(C.role_pack("pd", self.ws)["tools"], ["delegate", "house-memory"])
        import workspace_status as W
        saved = W.WORKSPACE
        W.WORKSPACE = self.ws
        try:
            ids = [i[0] for i in W._instruction_files() if i[0].startswith("roles/")]
        finally:
            W.WORKSPACE = saved
        self.assertIn("roles/pd/ROLE.md", ids)          # the rules API and the team tab name the file on disk
        self.assertIn("roles/staff/role.md", ids)
        self.assertIn("roles/pd/PROCEDURE.md", ids)

class SessionsAndGrants(unittest.TestCase):
    def setUp(self):
        import session as S
        self.S = S
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        (self.ws / "roles" / "pd").mkdir(parents=True)
        (self.ws / "roles" / "pd" / "role.md").write_text(PD, encoding="utf-8")
        self.a, self.b = C.new_id(), C.new_id()
        C.save(self.a, C.new_card("A"), self.ws)
        C.save(self.b, C.new_card("B"), self.ws)
        C.save_team({"default": self.b, "members": {self.a: ["pd"]}}, self.ws)
        self.saved = (S.SESSIONS, S.WORKSPACE)
        S.SESSIONS, S.WORKSPACE = self.tmp / "sessions", self.ws
        S.SESSIONS.mkdir()

    def tearDown(self):
        self.S.SESSIONS, self.S.WORKSPACE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_old_sessions_become_the_default_character_s(self):
        d = self.S.SESSIONS / "20260921-100000-old001"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": d.name, "history": [{"role": "user", "text": "hi"}]}),
                                     encoding="utf-8")
        import os
        os.utime(d / "meta.json", (1_700_000_000, 1_700_000_000))
        self.assertEqual(self.S.migrate_session_characters(), 1)
        self.assertEqual(int((d / "meta.json").stat().st_mtime), 1_700_000_000)   # the list orders by it
        self.assertEqual(self.S.migrate_session_characters(), 0)
        self.assertEqual(json.loads((d / "meta.json").read_text(encoding="utf-8"))["character"], self.b)
        reg = self.S.Registry()
        self.assertEqual(reg.get_active().sid, d.name)                     # the default (B) is not the PD (A)
        self.assertEqual(reg.get_active(self.b).sid, d.name)
        self.assertNotEqual(reg.get_active(self.a).sid, d.name)

    def test_grants_come_from_held_roles(self):
        self.assertEqual(C.tools_of(self.a, self.ws), ["delegate", "house-memory"])
        self.assertEqual(C.tools_of(self.b, self.ws), [])


if __name__ == "__main__":
    unittest.main()
