"""Engine-development rules reach only the characters that do engine work (plan pew/L). The shared charter
(data/workspace/AGENTS.md) is injected into every character and, in the shipped build, into characters that never
touch the engine; tickets, claims, plans and the commit rules live in the `dev` role pack (roles/dev/), held through
team.json. A character without that role gets none of it in its bundle.
Run: python3 -m unittest tests.test_dev_role  (from services/chatbot)
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import instructions as I  # noqa: E402

WS = ROOT / "data" / "workspace"
# Text that only engine work needs; any of it in the charter or a non-dev role's every-turn part is a leak.
DEV_MARKERS = ("## Self-modification", "`ticket` tool", "claiming an approved ticket", "SELF-MODIFY.md",
               "docs/plans/", "--no-verify", "run-tests.sh", "PROJECT.md", "⚡소생")


class DevRulesStayInTheDevPack(unittest.TestCase):
    def test_the_shared_charter_carries_no_engine_procedure(self):
        charter = (WS / "AGENTS.md").read_text(encoding="utf-8")
        for m in DEV_MARKERS:
            self.assertNotIn(m, charter, "engine procedure %r belongs in roles/dev/procedure.md" % m)

    def test_the_dev_pack_holds_what_left_the_charter(self):
        role = (WS / "roles" / "dev" / "role.md").read_text(encoding="utf-8")
        proc = (WS / "roles" / "dev" / "procedure.md").read_text(encoding="utf-8")
        self.assertIn("roles/dev/procedure.md", role)
        for m in ("`ticket` tool", "claiming an approved ticket", "SELF-MODIFY.md", "docs/plans/INDEX.md",
                  "--no-verify", "run-tests.sh", "AGENTS.md"):
            self.assertIn(m, proc)

    def test_other_roles_every_turn_part_has_no_engine_procedure(self):
        for pack in sorted((WS / "roles").glob("*/role.md")):
            if pack.parent.name == "dev":
                continue
            text = pack.read_text(encoding="utf-8")
            for m in DEV_MARKERS:
                self.assertNotIn(m, text, "%s: %r" % (pack.relative_to(ROOT), m))


class OnlyDevHoldersGetIt(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        (self.ws / "memory").mkdir()
        shutil.copy(WS / "AGENTS.md", self.ws / "AGENTS.md")
        shutil.copytree(WS / "roles", self.ws / "roles")
        self.dev, self.other = C.new_id(), C.new_id()
        C.save(self.dev, C.new_card("D", description="d body"), self.ws)
        C.save(self.other, C.new_card("O", description="o body"), self.ws)
        C.save_team({"default": self.dev, "members": {self.dev: ["pd", "dev"], self.other: ["artist"]}}, self.ws)
        self.saved = (I.WORKSPACE, I.WS_SKILLS_DIR, I.MEMORY_FILE)
        I.WORKSPACE, I.WS_SKILLS_DIR, I.MEMORY_FILE = self.ws, self.ws / ".agents" / "skills", self.ws / "memory" / "MEMORY.md"

    def tearDown(self):
        I.WORKSPACE, I.WS_SKILLS_DIR, I.MEMORY_FILE = self.saved
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_the_bundle_names_the_dev_procedure_only_for_dev_holders(self):
        dev = I.build_instruction_bundle(character=self.dev)["text"]
        other = I.build_instruction_bundle(character=self.other)["text"]
        self.assertIn("# Role: Developer", dev)
        self.assertNotIn("# Role: Developer", other)
        self.assertNotIn("roles/dev/procedure.md", other)
        for m in DEV_MARKERS:
            self.assertNotIn(m, other)


if __name__ == "__main__":
    unittest.main()
