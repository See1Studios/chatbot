"""The shipped workspace template does not drift from the live workspace and carries nothing of this host
(user-data-separation uds/C5). templates/workspace-manifest.json lists every tracked data/workspace file outside the
per-user folders exactly once: 'same' (template copy byte-equal), 'variant' (own version, with a reason) or
'not_shipped' (with a reason). A new workspace file, an edit to one side of a 'same' pair, or a template file nobody
listed fails here.
Run: python3 -m unittest tests.test_workspace_template  (from services/chatbot)
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import instructions as I  # noqa: E402

TEMPLATE = ROOT / "templates" / "workspace"
LIVE = ROOT / "data" / "workspace"
MANIFEST = json.loads((ROOT / "templates" / "workspace-manifest.json").read_text(encoding="utf-8"))
HOST_MARKERS = ("DiskStation", "/volume1", "/var/services", "Sphere", "실장님", "냥", "services/chatbot",  # l10n-ok
                "FIREBAT", "~/AGENTS.md", "~/services", "NyangPD")
DEV_MARKERS = ("`ticket` tool", "claiming an approved ticket", "SELF-MODIFY.md", "PROJECT.md", "docs/plans/",
               "--no-verify", "run-tests.sh", "`dev` role", "delegate")
FIX = "edit templates/workspace-manifest.json (move the path to 'variant' or 'not_shipped' with a reason)"


def tracked_live():
    r = subprocess.run(["git", "ls-files", "-z", "--", "data/workspace"], cwd=str(ROOT), capture_output=True, timeout=60)
    names = [n[len("data/workspace/"):] for n in r.stdout.decode("utf-8", "replace").split("\0") if n]
    return {n for n in names if not n.startswith(tuple(MANIFEST["per_user"]))}


def template_files():
    return {p.relative_to(TEMPLATE).as_posix() for p in TEMPLATE.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


class WorkspaceTemplate(unittest.TestCase):
    def test_each_path_is_classified_once(self):
        groups = [set(MANIFEST["same"]), set(MANIFEST["variant"]), set(MANIFEST["not_shipped"])]
        seen = set()
        for g in groups:
            self.assertFalse(seen & g, "listed twice: %s" % sorted(seen & g))
            seen |= g
        live = tracked_live()
        if not live:
            self.skipTest("no git checkout of data/workspace")
        self.assertEqual(sorted(live - seen), [], "unclassified workspace files; " + FIX)
        self.assertEqual(sorted((set(MANIFEST["not_shipped"]) | set(MANIFEST["same"])) - live), [],
                         "manifest names files the workspace no longer tracks")

    def test_same_files_stay_byte_equal(self):
        for rel in MANIFEST["same"]:
            a, b = LIVE / rel, TEMPLATE / rel
            self.assertTrue(b.is_file(), "template copy missing: templates/workspace/%s" % rel)
            if not a.is_file():
                continue  # a release checkout has no live workspace; the template is the SSOT
            self.assertEqual(a.read_bytes(), b.read_bytes(),
                             "data/workspace/%s and its template copy differ: copy the change to "
                             "templates/workspace/%s, or %s" % (rel, rel, FIX))

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
