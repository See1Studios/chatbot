"""Document names follow one rule (root AGENTS.md "Naming", 2026-09-28): standing documents -- one copy, always current,
found by name (repo root, docs/, the chat charter folder data/workspace/) -- are UPPERCASE; documents that accumulate
(plans, dated logs) are lower-kebab; no snake_case anywhere. Only tracked files are checked.
Run: python3 -m unittest tests.test_doc_names  (from services/chatbot)
"""
import re
import subprocess
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

ROOT = REPO
UPPER = re.compile(r"^[A-Z0-9][A-Z0-9-]*\.md$")
KEBAB = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")
PLAN_EXCEPTIONS = {"INDEX.md", "_TEMPLATE.md"}


def tracked(pattern):
    out = subprocess.run(["git", "ls-files", pattern], cwd=str(ROOT), capture_output=True, text=True).stdout
    return [Path(p) for p in out.splitlines() if p]


class DocNames(unittest.TestCase):
    def test_standing_documents_are_uppercase(self):
        for folder in ("", "docs/", "data/workspace/"):
            for p in tracked(folder + "*.md"):
                if p.parent.as_posix() != (folder.rstrip("/") or "."):
                    continue   # only the folder itself, not its subfolders
                self.assertRegex(p.name, UPPER, "%s is a standing document: name it in UPPERCASE" % p)

    def test_plans_are_lower_kebab(self):
        for p in tracked("docs/plans/*.md"):
            if "archive" in p.parts or p.name in PLAN_EXCEPTIONS:
                continue
            self.assertRegex(p.name, KEBAB, "%s: plans are lower-kebab (e.g. my-plan.md)" % p)

    def test_no_snake_case_documents(self):
        for p in tracked("docs") + tracked("data/workspace/*.md"):
            if p.suffix == ".md" and p.name not in PLAN_EXCEPTIONS:
                self.assertNotIn("_", p.name, "%s: use hyphens, not underscores" % p)


if __name__ == "__main__":
    unittest.main()
