"""Docs an agent reads stay cheap and findable (AGENT_FIRST_v1): the recent log is small, older days live in one file
per date, and every plan is listed with its state in docs/plans/INDEX.md.
Run: python3 -m unittest tests.test_docs_budget  (from services/chatbot)
"""
import re
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
DEVLOG_MAX_BYTES = 40 * 1024


class DocsBudget(unittest.TestCase):
    def test_the_recent_log_stays_small(self):
        n = (DOCS / "DEVLOG.md").stat().st_size
        self.assertLess(n, DEVLOG_MAX_BYTES, "docs/DEVLOG.md is %d bytes: move its oldest date to docs/devlog/" % n)

    def test_older_days_are_one_file_per_date(self):
        for p in (DOCS / "devlog").glob("*"):
            self.assertRegex(p.name, r"^\d{4}-\d{2}-\d{2}\.md$", p.name)
            self.assertTrue(p.read_text(encoding="utf-8").startswith("# chatbot 개발로그 — " + p.stem), p.name)

    def test_the_recent_log_holds_only_dates_not_moved_out(self):
        moved = {p.stem for p in (DOCS / "devlog").glob("*.md")}
        for head in re.findall(r"(?m)^## .*", (DOCS / "DEVLOG.md").read_text(encoding="utf-8")):
            m = re.search(r"\d{4}-\d{2}-\d{2}", head)
            self.assertTrue(m, head)
            self.assertNotIn(m.group(0), moved, "%s is split between DEVLOG.md and docs/devlog/" % m.group(0))

    def test_every_plan_is_in_the_index(self):
        index = (DOCS / "plans" / "INDEX.md").read_text(encoding="utf-8")
        for p in (DOCS / "plans").glob("*.md"):
            if p.name != "INDEX.md":
                self.assertIn("(%s)" % p.name, index, "add %s to docs/plans/INDEX.md" % p.name)


if __name__ == "__main__":
    unittest.main()
