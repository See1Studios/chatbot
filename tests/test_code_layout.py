"""Moving code into a folder must not move it out of protection (FOLDERS_PROVIDERS_v1): protected_paths.json's `*.py`
covers only the root, so every code folder needs its own entry. A module an agent could change without a ticket is
a hole in the self-modification rules.
Run: engine/run-tests.sh test_code_layout
"""
import re
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import evolution  # noqa: E402

CODE_DIRS = ["", "providers", "tools"]   # folders of host code; add one here when you make it


class CodeLayout(unittest.TestCase):
    def test_every_host_module_is_protected(self):
        for d in CODE_DIRS:
            for p in sorted((ENGINE / d).glob("*.py")):
                self.assertTrue(evolution.is_protected(ROOT, p), "%s is not protected: add its folder to "
                                "protected_paths.json" % p.relative_to(ROOT))

    def test_every_code_folder_is_listed(self):
        for p in ENGINE.iterdir():
            if p.is_dir() and (p / "__init__.py").exists():
                self.assertIn(p.name, CODE_DIRS, "%s/ is a code package: list it in CODE_DIRS and protect it" % p.name)

    def test_every_pass_condition_is_governance(self):
        # a guard, the runner that calls it, the hooks and the charter are pass conditions: tier 3, operator only
        import re
        fast = re.search(r"^FAST=\((.*?)^\)", (ENGINE / "run-tests.sh").read_text(encoding="utf-8"), re.S | re.M)
        paths = ["tests/%s.py" % m for m in fast.group(1).split()]
        paths += ["engine/run-tests.sh", ".githooks/pre-commit", ".githooks/check_staged.py", "AGENTS.md", "CLAUDE.md",
                  "GEMINI.md", "engine/tools/worktree_runner.py", "engine/tools/review_checklist.py"]   # the runner and its verdict
        for rel in paths:
            self.assertEqual(evolution.delegation_tier(ROOT, rel)[0], 3,
                             "%s must be listed under governance in protected_paths.json" % rel)

    def test_governance_entries_point_at_real_paths(self):
        import json
        for g in json.loads((ENGINE / "protected_paths.json").read_text(encoding="utf-8"))["governance"]:
            path = g["path"]
            if path.startswith("data/"):
                continue  # dev-install data, not in the release tree
            if path.startswith("~/") or any(c in path for c in "*?"):
                continue
            self.assertTrue((ROOT / path).exists(), "governance lists %s, which is gone: fix or drop it" % path)


class OnePlaceForRoots(unittest.TestCase):
    """LAYOUT_v1 (docs/plans/repo-layout.md layout/B): the repo root and the engine folder are decided in repo_layout.py
    (code) and tests/_paths.py (tests) only, so moving the code into engine/ changes no constant."""
    SCRIPT_TESTS = {"smoke.py", "test_identity_wiring.py"}   # run as `python3 tests/x.py` by the runner: they bootstrap
    ROOT_FROM_FILE = re.compile(r"Path\(__file__\)\.resolve\(\)\.(?:parent\.parent|parents\[1\])")
    REPO_DIR_FROM_FILE = re.compile(r"Path\(__file__\)[\w.()\[\]]*\s*/\s*\"(?:static|templates|tests|docs)\"")

    def test_the_test_helper_and_the_code_agree(self):
        import repo_layout
        self.assertEqual((REPO, ENGINE), (repo_layout.REPO, repo_layout.ENGINE))

    def test_no_test_computes_the_root_itself(self):
        hits = [p.name for p in sorted((REPO / "tests").glob("*.py"))   # not probes/: scripts run by hand
                if p.name not in self.SCRIPT_TESTS | {"_paths.py"}
                and self.ROOT_FROM_FILE.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [], "use `from tests._paths import REPO, ENGINE`")

    def test_no_code_finds_a_repo_folder_from_its_own_file(self):
        files = [p for d in CODE_DIRS for p in sorted((ENGINE / d).glob("*.py")) if p.name != "repo_layout.py"]
        hits = [p.name for p in files if self.REPO_DIR_FROM_FILE.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [], "static/, templates/, tests/, docs/ come from repo_layout (REPO, STATIC, TEMPLATES)")


if __name__ == "__main__":
    unittest.main()
