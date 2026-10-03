"""The workspace templates stay classified and carry nothing of this host (user-data-separation uds/C5, uds/F).
templates/workspace/ is what a new install copies; templates/dev-workspace/ holds the dev build's own files (its
charter, engine role packs, engine skills and tools), tracked here because an install's workspace is user data outside
the repo. templates/workspace-manifest.json lists every such file exactly once: 'same' (shipped as is), 'variant'
(the shipped copy differs on purpose; the dev copy lives in dev-workspace) or 'not_shipped' (dev-workspace only, with a
reason); 'per_install' files (this user's or this host's) are in neither. An unlisted file on either side, or a
listed one missing, fails here.
Run: python3 -m unittest tests.test_workspace_template  (from services/chatbot)
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import instructions as I  # noqa: E402

TEMPLATE = ROOT / "templates" / "workspace"
DEV = ROOT / "templates" / "dev-workspace"
MANIFEST = json.loads((ROOT / "templates" / "workspace-manifest.json").read_text(encoding="utf-8"))
HOST_MARKERS = ("DiskStation", "/volume1", "/var/services", "Sphere", "실장님", "냥", "services/chatbot",  # l10n-ok
                "FIREBAT", "~/AGENTS.md", "~/services", "NyangPD")
DEV_MARKERS = ("`ticket` tool", "claiming an approved ticket", "SELF-MODIFY.md", "PROJECT.md", "docs/plans/",
               "--no-verify", "run-tests.sh", "`dev` role", "delegate")
FIX = "edit templates/workspace-manifest.json (move the path to 'variant' or 'not_shipped' with a reason)"


def _files(base):
    return {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def template_files():
    return _files(TEMPLATE)


def dev_files():
    return _files(DEV)


class WorkspaceTemplate(unittest.TestCase):
    def test_each_path_is_classified_once(self):
        groups = [set(MANIFEST["same"]), set(MANIFEST["variant"]), set(MANIFEST["not_shipped"]),
                  set(MANIFEST["per_install"])]
        seen = set()
        for g in groups:
            self.assertFalse(seen & g, "listed twice: %s" % sorted(seen & g))
            seen |= g
        dev = dev_files()
        self.assertEqual(sorted(dev - set(MANIFEST["not_shipped"]) - set(MANIFEST["variant"])), [],
                         "unclassified templates/dev-workspace files; " + FIX)
        self.assertEqual(sorted(set(MANIFEST["not_shipped"]) - dev), [],
                         "not_shipped files missing from templates/dev-workspace/")

    def test_a_users_or_hosts_own_file_is_in_neither_template(self):
        # SSOT user-data-separation §0.1: personal or host-specific files live in ~/.pe only
        for rel, why in MANIFEST["per_install"].items():
            self.assertTrue(str(why).strip(), "%s needs a reason" % rel)
            self.assertFalse((TEMPLATE / rel).exists(), "templates/workspace/%s is per_install" % rel)
            self.assertFalse((DEV / rel).exists(), "templates/dev-workspace/%s is per_install" % rel)

    def test_same_files_have_one_copy(self):
        for rel in MANIFEST["same"]:
            self.assertTrue((TEMPLATE / rel).is_file(), "template copy missing: templates/workspace/%s" % rel)
            self.assertFalse((DEV / rel).exists(), "templates/dev-workspace/%s duplicates a shipped file" % rel)

    def test_the_template_holds_only_listed_files(self):
        listed = set(MANIFEST["same"]) | set(MANIFEST["variant"])
        self.assertEqual(sorted(template_files() - listed), [], "unlisted template files; " + FIX)
        self.assertEqual(sorted(listed - template_files()), [], "listed but missing in templates/workspace/")
        for rel, why in list(MANIFEST["variant"].items()) + list(MANIFEST["not_shipped"].items()):
            self.assertTrue(str(why).strip(), "%s needs a reason" % rel)

    def test_nothing_of_this_host_ships(self):
        for rel in sorted(template_files()):
            text = (TEMPLATE / rel).read_text(encoding="utf-8", errors="replace")
            for m in HOST_MARKERS:
                self.assertNotIn(m, text, "templates/workspace/%s names this host: %r" % (rel, m))

    def test_the_shipped_charter_and_roles_carry_no_engine_work(self):
        for rel in ["AGENTS.md"] + sorted(r for r in template_files() if r.startswith("roles/")):
            text = (TEMPLATE / rel).read_text(encoding="utf-8")
            for m in DEV_MARKERS:
                self.assertNotIn(m, text, "templates/workspace/%s: %r is engine work (dev build only)" % (rel, m))

    def test_the_shipped_charter_keeps_the_sections_private_sessions_read(self):
        charter = (TEMPLATE / "AGENTS.md").read_text(encoding="utf-8")
        for name in I.PRIVATE_CHARTER_SECTIONS:
            self.assertIn("\n## %s\n" % name, charter)

    def test_the_template_roster_is_valid_json(self):
        team = json.loads((TEMPLATE / "team.json").read_text(encoding="utf-8"))
        self.assertIsInstance(team.get("members"), dict)


if __name__ == "__main__":
    unittest.main()
