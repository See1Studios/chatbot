"""tools/link_dev_workspace.py: a dev install's workspace links to the engine's own instructions, never copies them
(user-data-separation §0.1). Fixture dirs only. Engine role packs under templates/dev-workspace/ are linked like the
charter; packs that exist only live (e.g. art) are outside the tool's scan and stay untouched.
Run: python3 -m unittest tests.test_link_dev_workspace  (from services/chatbot)
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import link_dev_workspace as L  # noqa: E402


class LinkDevWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.dev = self.tmp / "dev"
        for rel, text in (("AGENTS.md", "charter"), ("roles/dev/ROLE.md", "role"), ("PROJECT.md", "map"),
                          ("docs/guide.md", "guide"), ("roles/lead/ROLE.md", "lead"), ("SELF-MODIFY.md", "bounds")):
            (self.dev / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.dev / rel).write_text(text, encoding="utf-8")
        self.data = self.tmp / "pe"
        self.ws = self.data / "workspace"
        (self.ws / "roles" / "dev").mkdir(parents=True)
        (self.ws / "AGENTS.md").write_text("charter", encoding="utf-8")            # an equal copy
        (self.ws / "roles" / "dev" / "ROLE.md").write_text("edited", encoding="utf-8")  # differs: backup then link
        (self.ws / "roles" / "lead").mkdir()
        (self.ws / "roles" / "lead" / "ROLE.md").symlink_to(self.dev / "roles" / "lead" / "ROLE.md")   # linked before
        (self.ws / "roles" / "art").mkdir()
        (self.ws / "roles" / "art" / "ROLE.md").write_text("art-live", encoding="utf-8")  # live-only: never touched
        (self.ws / "SELF-MODIFY.md").write_text("changed", encoding="utf-8")       # an engine file someone changed
        (self.ws / "PROJECT.md").symlink_to(self.tmp / "elsewhere.md")             # a link to the wrong place
        (self.ws / "team.json").write_text("{}", encoding="utf-8")                 # user data: never touched

    def test_the_plan_names_each_case(self):
        self.assertEqual(L.plan(self.data, self.dev), [("link", "AGENTS.md"), ("relink", "PROJECT.md"),
                                                       ("backup", "SELF-MODIFY.md"), ("link", "docs/guide.md"),
                                                       ("backup", "roles/dev/ROLE.md"), ("ok", "roles/lead/ROLE.md")])

    def test_apply_links_engine_files_including_role_packs(self):
        backup = L.apply(self.data, L.plan(self.data, self.dev), self.dev, stamp="t")
        for rel in ("AGENTS.md", "PROJECT.md", "docs/guide.md", "SELF-MODIFY.md",
                    "roles/dev/ROLE.md", "roles/lead/ROLE.md"):
            p = self.ws / rel
            self.assertTrue(p.is_symlink(), rel)
            self.assertEqual(p.resolve(), (self.dev / rel).resolve(), rel)
        self.assertEqual((backup / "SELF-MODIFY.md").read_text(encoding="utf-8"), "changed")
        self.assertEqual((backup / "roles" / "dev" / "ROLE.md").read_text(encoding="utf-8"), "edited")
        self.assertEqual(sorted(p.relative_to(backup).as_posix() for p in backup.rglob("*") if p.is_file()),
                         ["SELF-MODIFY.md", "roles/dev/ROLE.md"])
        art = self.ws / "roles" / "art" / "ROLE.md"
        self.assertFalse(art.is_symlink(), "live-only art pack stays a local file")
        self.assertEqual(art.read_text(encoding="utf-8"), "art-live")
        self.assertEqual((self.ws / "team.json").read_text(encoding="utf-8"), "{}")
        self.assertEqual({a for a, _ in L.plan(self.data, self.dev)}, {"ok"}, "a second run has nothing to do")

    def test_the_dry_run_changes_nothing(self):
        before = sorted((p.as_posix(), p.is_symlink()) for p in self.ws.rglob("*"))
        self.assertEqual(L.main(["--data", str(self.data)]), 0)
        self.assertEqual(sorted((p.as_posix(), p.is_symlink()) for p in self.ws.rglob("*")), before)

    def test_it_links_the_repos_dev_templates_by_default(self):
        self.assertEqual(L.DEV, ROOT / "templates" / "dev-workspace")
        self.assertTrue((L.DEV / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()

