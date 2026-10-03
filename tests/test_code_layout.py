"""Moving code into a folder must not move it out of protection (FOLDERS_PROVIDERS_v1): protected_paths.json's `*.py`
covers only the root, so every code folder needs its own entry. A module an agent could change without a ticket is
a hole in the self-modification rules.
Run: python3 -m unittest tests.test_code_layout  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import evolution  # noqa: E402

CODE_DIRS = ["", "providers", "tools"]   # folders of host code; add one here when you make it


class CodeLayout(unittest.TestCase):
    def test_every_host_module_is_protected(self):
        for d in CODE_DIRS:
            for p in sorted((ROOT / d).glob("*.py")):
                self.assertTrue(evolution.is_protected(ROOT, p), "%s is not protected: add its folder to "
                                "protected_paths.json" % p.relative_to(ROOT))

    def test_every_code_folder_is_listed(self):
        for p in ROOT.iterdir():
            if p.is_dir() and (p / "__init__.py").exists():
                self.assertIn(p.name, CODE_DIRS, "%s/ is a code package: list it in CODE_DIRS and protect it" % p.name)

    def test_every_pass_condition_is_governance(self):
        # a guard, the runner that calls it, the hooks and the charter are pass conditions: tier 3, operator only
        import re
        fast = re.search(r"^FAST=\((.*?)^\)", (ROOT / "run-tests.sh").read_text(encoding="utf-8"), re.S | re.M)
        paths = ["tests/%s.py" % m for m in fast.group(1).split()]
        paths += ["run-tests.sh", ".githooks/pre-commit", ".githooks/check_staged.py", "AGENTS.md", "CLAUDE.md",
                  "GEMINI.md", "tools/worktree_runner.py", "tools/review_checklist.py"]   # the runner and its verdict
        for rel in paths:
            self.assertEqual(evolution.delegation_tier(ROOT, rel)[0], 3,
                             "%s must be listed under governance in protected_paths.json" % rel)

    def test_governance_entries_point_at_real_paths(self):
        import json
        for g in json.loads((ROOT / "protected_paths.json").read_text(encoding="utf-8"))["governance"]:
            path = g["path"]
            if path.startswith("data/"):
                continue  # dev-install data, not in the release tree
            if path.startswith("~/") or any(c in path for c in "*?"):
                continue
            self.assertTrue((ROOT / path).exists(), "governance lists %s, which is gone: fix or drop it" % path)


if __name__ == "__main__":
    unittest.main()
