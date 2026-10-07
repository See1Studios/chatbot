"""Docs an agent reads stay cheap and findable (AGENT_FIRST_v1): the recent log is small, older days live in one file
per date, (Plan/INDEX pairing moved to test_plans_index.)
Run: engine/run-tests.sh test_docs_budget
"""
import re
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

DOCS = REPO / "docs"
HISTORY_MAX_BYTES = 40 * 1024


class DocsBudget(unittest.TestCase):
    def test_the_recent_log_stays_small(self):
        n = (REPO / "HISTORY.md").stat().st_size
        self.assertLess(n, HISTORY_MAX_BYTES, "HISTORY.md is %d bytes: move its oldest date to docs/history/" % n)

    def test_older_days_are_one_file_per_date(self):
        for p in (DOCS / "history").glob("*"):
            self.assertRegex(p.name, r"^\d{4}-\d{2}-\d{2}\.md$", p.name)
            self.assertTrue(p.read_text(encoding="utf-8").startswith("# chatbot 개발로그 — " + p.stem), p.name)

    def test_the_recent_log_holds_only_dates_not_moved_out(self):
        moved = {p.stem for p in (DOCS / "history").glob("*.md")}
        for head in re.findall(r"(?m)^## .*", (REPO / "HISTORY.md").read_text(encoding="utf-8")):
            m = re.search(r"\d{4}-\d{2}-\d{2}", head)
            self.assertTrue(m, head)
            self.assertNotIn(m.group(0), moved, "%s is split between HISTORY.md and docs/history/" % m.group(0))


if __name__ == "__main__":
    unittest.main()
