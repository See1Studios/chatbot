"""Every character is equal: cards carry no role; a role is a pack (roles/<role>/ROLE.md: instructions, skills,
tool grants) and the roster (team.json) says who holds it and whom the app opens with (TEAM_ROLES_v1).
Run: engine/run-tests.sh test_team_roles
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
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
            (self.ws / "roles" / role / "ROLE.md").write_text(text, encoding="utf-8")
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

    def test_roles_follow_the_roster_not_the_card(self):
        C.save_team(C.load_team(self.ws), self.ws)   # the roster the cards imply
        C.save_team({"default": self.b, "members": {self.b: ["pd", "staff"], self.c: ["staff"]}}, self.ws)
        self.assertEqual(C.by_role("pd", self.ws), self.b)
        self.assertEqual(C.default_character(self.ws), self.b)
        self.assertEqual(C.tools_of(self.b, self.ws), sorted(set(C.BASE_TOOLS + ("delegate", "house-memory"))))
        self.assertEqual(C.tools_of(self.a, self.ws), list(C.BASE_TOOLS))
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

    def test_a_role_is_played_by_a_holder_other_than_the_default(self):
        C.save_team({"default": self.a, "members": {self.a: ["dev", "lead"], self.c: ["dev"]}}, self.ws)
        self.assertEqual(C.by_role("dev", self.ws), self.c, "the default also holds dev; the work goes to the other")
        self.assertEqual(C.by_role("lead", self.ws), self.a, "only the default holds it")
        self.assertIsNone(C.by_role("art", self.ws))

    def test_without_a_roster_the_oldest_card_is_the_default_whatever_its_role(self):
        self.assertEqual(C.load_team(self.ws)["default"], self.a)
        C.save(self.a, C.new_card("A", "staff", description="a body"), self.ws)
        self.assertEqual(C.load_team(self.ws)["default"], self.a)

    def test_engine_code_names_no_role(self):
        # the enforcer of the rule above: a role id quoted in engine code is the old hardcoding coming back
        pattern = re.compile(r"""["'](pd|staff|artist|lead)["']""")
        files = sorted(list(ENGINE.glob("*.py")) + list((ENGINE / "tools").glob("*.py")) + list((ENGINE / "providers").glob("*.py")))
        hits = ["%s:%d" % (f.name, n) for f in files
                for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
        self.assertEqual(hits, [], "engine code must not name a role (roles live in team.json and roles/)")

    def test_every_character_gets_the_same_bundle_shape(self):
        C.save_team(C.load_team(self.ws), self.ws)   # the roster the cards imply
        pd = I.build_instruction_bundle()["text"]                                    # the default character
        self.assertIn("a body", pd)
        self.assertIn("You plan and delegate.", pd)
        self.assertIn("- planning", pd)                                               # a skill the PD pack claims
        self.assertIn("- drawing", pd)                                                # no role claims it: the default's
        staff = I.build_instruction_bundle(character=self.b)["text"]
        self.assertIn("You do the work.", staff)
        self.assertNotIn("You plan and delegate.", staff)
        self.assertNotIn("- planning", staff)
        self.assertNotIn("- drawing", staff, "a skill no role claims is the default character's (DEFAULT_ROLE_v1)")
        no_role = I.NO_ROLE_NOTE.split("]")[0]   # "[No role" -- the rest names the default character (CARD_MACROS_v1)
        self.assertIn(no_role, I.build_instruction_bundle(character=self.c)["text"])
        self.assertNotIn(no_role, staff)

    def test_the_dev_charter_no_longer_makes_everyone_the_pd(self):
        dev = ROOT / "templates" / "dev-workspace"   # uds/F: the dev build's tracked charter and packs; teams are user data
        for charter in ((dev.parent / "workspace" / "AGENTS.md").read_text(encoding="utf-8"),
                        (dev / "DEV-CHARTER.md").read_text(encoding="utf-8")):   # one charter + dev rules (DEV_SPLIT_v1)
            self.assertNotIn("You are the PD", charter)
            self.assertNotIn("role `pd`", charter)
        packs = [C.role_pack(d.name, dev) for d in sorted((dev / "roles").iterdir())]   # delegation is a pack grant
        self.assertTrue(any("delegate" in p["tools"] for p in packs), [p["role"] for p in packs])


    def test_pack_files_take_the_upper_case_name(self):
        # pew/R: roles/<role>/ROLE.md and PROCEDURE.md, like SKILL.md (the old lower-case names: dropped 2026-10-07)
        d = self.ws / "roles" / "pd"
        self.assertEqual(C.pack_file("pd", "role", self.ws).name, "ROLE.md")
        self.assertEqual(C.pack_file("pd", "procedure", self.ws).name, "PROCEDURE.md")  # none yet: the name it takes
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
        self.assertIn("roles/staff/ROLE.md", ids)
        self.assertIn("roles/pd/PROCEDURE.md", ids)

    def test_ticket_456_neutral_roles_in_delegation_and_workspace(self):
        # Ticket #456: Engine role neutralization
        import delegation as D
        import workspace_status as W
        import identity as Id

        tmp_data = Path(tempfile.mkdtemp()).resolve()
        test_ws = tmp_data / "workspace"
        test_ws.mkdir()
        try:
            c1, c2 = sorted([C.new_id(), C.new_id()])
            C.save(c1, C.new_card("Host"), test_ws)
            C.save(c2, C.new_card("Worker"), test_ws)

            # 1. delegation.experts() returns non-default characters' roles
            saved_data = D.DATA
            D.DATA = tmp_data
            try:
                C.save_team({"default": c1, "members": {c1: ["host-role"], c2: ["worker-role"]}}, test_ws)
                self.assertEqual(D.experts(), ["worker-role"])
                C.save_team({"default": c2, "members": {c1: ["host-role"], c2: ["worker-role"]}}, test_ws)
                self.assertEqual(D.experts(), ["host-role"])
            finally:
                D.DATA = saved_data

            # 2. workspace_status._instruction_files() marks default as 'always' and others as 'on_demand'
            saved_ws = W.WORKSPACE
            W.WORKSPACE = test_ws
            try:
                C.save_team({"default": c1, "members": {c1: ["pd"], c2: ["staff"]}}, test_ws)
                items = {i[0]: i[3] for i in W._instruction_files() if "card.json" in i[0]}
                self.assertEqual(items.get("characters/%s/card.json" % c1), "always")
                self.assertEqual(items.get("characters/%s/card.json" % c2), "on_demand")
            finally:
                W.WORKSPACE = saved_ws

            # 3. characters.load_team fallback without team.json uses oldest card as default
            empty_ws = tmp_data / "empty_ws"
            empty_ws.mkdir()
            cards = [{"id": c1, "card": C.new_card("Oldest")}, {"id": c2, "card": C.new_card("Newer")}]
            roster = C.load_team(ws=empty_ws, cards=cards)
            self.assertEqual(roster["default"], c1)

            # 4. identity.seed_workspace_files seeds default character with empty roles (no hardcoded roles)
            seed_ws = tmp_data / "seed_ws"
            seed_ws.mkdir()
            Id.seed_workspace_files(workspace=seed_ws)
            seeded_team = C.load_team(seed_ws)
            def_id = seeded_team["default"]
            self.assertTrue(def_id)
            self.assertEqual(seeded_team["members"].get(def_id), [], "seeded character holds no hardcoded role")
        finally:
            shutil.rmtree(tmp_data, ignore_errors=True)

class SessionsAndGrants(unittest.TestCase):
    def setUp(self):
        import session as S
        self.S = S
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        (self.ws / "roles" / "pd").mkdir(parents=True)
        (self.ws / "roles" / "pd" / "ROLE.md").write_text(PD, encoding="utf-8")
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
        self.assertEqual(C.tools_of(self.a, self.ws), sorted(set(C.BASE_TOOLS + ("delegate", "house-memory"))))
        self.assertEqual(C.tools_of(self.b, self.ws), list(C.BASE_TOOLS))


class RoleManagementApi(unittest.TestCase):
    def setUp(self):
        import workspace_status as WS
        self.WS = WS
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        (self.ws / "roles").mkdir()
        (self.ws / ".agents" / "skills" / "handoff-brief").mkdir(parents=True)
        (self.ws / ".agents" / "skills" / "handoff-brief" / "SKILL.md").write_text(
            "---\nname: handoff-brief\ndescription: brief handoff\n---\n", encoding="utf-8")
        self.saved_ws = WS.WORKSPACE
        self.saved_i = (I.WORKSPACE, I.WS_SKILLS_DIR)
        WS.WORKSPACE = self.ws
        I.WORKSPACE, I.WS_SKILLS_DIR = self.ws, self.ws / ".agents" / "skills"
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("TesterChar"), self.ws)
        C.save_team({"default": self.cid, "members": {self.cid: []}}, self.ws)

    def tearDown(self):
        I.WORKSPACE, I.WS_SKILLS_DIR = self.saved_i
        self.WS.WORKSPACE = self.saved_ws
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_put_role_crud(self):
        # 1. Create role
        code, res = self.WS.experts_api("PUT", "/api/experts/roles/custom-worker", {
            "title": "Custom Worker",
            "owns": "custom tasks",
            "tools": ["delegate", "workspace"],
            "skills": ["custom-skill"],
            "description": "Handle custom work.",
        })
        self.assertEqual(code, 200)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("role"), "custom-worker")
        role_md = self.ws / "roles" / "custom-worker" / "ROLE.md"
        self.assertTrue(role_md.is_file())
        content = role_md.read_text(encoding="utf-8")
        self.assertIn("title: Custom Worker", content)
        self.assertIn("owns: custom tasks", content)
        self.assertIn("tools: delegate, workspace", content)
        self.assertIn("Handle custom work.", content)

        # 2. Overview includes metadata
        overview = self.WS.experts_overview()
        found = [r for r in overview.get("roles", []) if r["role"] == "custom-worker"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "Custom Worker")
        self.assertEqual(found[0]["owns"], "custom tasks")
        self.assertFalse(found[0]["builtin"])

        # 3. Refuse delete when assigned
        C.save_team({"default": self.cid, "members": {self.cid: ["custom-worker"]}}, self.ws)
        del_code, del_res = self.WS.experts_api("PUT", "/api/experts/roles/custom-worker", {"delete": True})
        self.assertEqual(del_code, 409)
        self.assertFalse(del_res.get("ok"))

        # 4. Delete succeeds when unassigned
        C.save_team({"default": self.cid, "members": {self.cid: []}}, self.ws)
        del_code, del_res = self.WS.experts_api("PUT", "/api/experts/roles/custom-worker", {"delete": True})
        self.assertEqual(del_code, 200)
        self.assertTrue(del_res.get("ok"))
        self.assertFalse((self.ws / "roles" / "custom-worker").exists())

    def test_base_baseline_granted_to_all_characters(self):
        # Character without any role still has BASE_TOOLS
        self.assertEqual(C.tools_of(self.cid, self.ws), list(C.BASE_TOOLS))
        # Base skills are included regardless of role
        skills = I._skills_text(character=self.cid)
        for bs in I.BASE_SKILLS:
            self.assertIn(bs, skills)

    def test_add_role_modal_ui_and_i18n(self):
        # Ticket #846: Add role modal 3-tier layout, validation & tool chips
        ko = json.loads((ROOT / "static" / "i18n" / "ko.json").read_text(encoding="utf-8"))
        en = json.loads((ROOT / "static" / "i18n" / "en.json").read_text(encoding="utf-8"))
        for key in ("team.role_id_invalid", "team.role_id_exists"):
            self.assertIn(key, ko)
            self.assertIn(key, en)
            self.assertTrue(ko[key].strip())
            self.assertTrue(en[key].strip())

        js = (ROOT / "static" / "app-team.js").read_text(encoding="utf-8")
        self.assertIn("function openAddRoleModal", js)
        self.assertIn("modal-head", js)
        self.assertIn("modal-body", js)
        self.assertIn("modal-foot", js)
        self.assertIn("card-field-row", js)
        self.assertIn("team.role_id_invalid", js)
        self.assertIn("team.role_id_exists", js)
        for tool in ("delegate", "memory", "status"):
            self.assertIn(tool, js)


if __name__ == "__main__":
    unittest.main()

