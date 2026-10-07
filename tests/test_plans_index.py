"""docs/plans/INDEX.md is the plan-status SSOT (INDEX "아카이브 절차", plan-execution-workflow pew/D): every plan file has
exactly one row, active rows point at docs/plans/*.md, archived rows at archive/YYYY/*.md, every status cell starts with
one of the four values, and a plan's own "상태" line agrees with its row.
Run: python3 -m unittest tests.test_plans_index  (from services/chatbot)
"""
import re
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

PLANS = REPO / "docs" / "plans"
STATES = ("active", "done", "superseded", "abandoned")
NOT_PLANS = {"INDEX.md", "_TEMPLATE.md"}


def section_rows(title):
    text = (PLANS / "INDEX.md").read_text(encoding="utf-8")
    block = text[text.index(title):]
    nxt = block.find("\n## ", len(title))
    block = block[:nxt] if nxt > 0 else block
    rows = []
    for line in block.splitlines():
        m = re.match(r"\| \[[^\]]+\]\(([^)]+)\) \| (.+?) \|", line)
        if m:
            status = re.sub(r"[`*]", "", m.group(2)).split()[0] if m.group(2).strip() else ""
            rows.append((m.group(1), status))
    return rows


class PlansIndex(unittest.TestCase):
    def test_every_active_plan_file_has_exactly_one_active_row(self):
        rows = [t for t, _ in section_rows("## Active")]
        files = sorted(p.name for p in PLANS.glob("*.md") if p.name not in NOT_PLANS)
        self.assertEqual(len(rows), len(set(rows)), "a plan is listed twice in INDEX Active")
        self.assertEqual(sorted(rows), files, "INDEX Active rows and docs/plans/*.md differ: add or archive the row")

    def test_active_rows_say_active(self):
        for target, status in section_rows("## Active"):
            self.assertEqual(status, "active", "%s: an Active row starts with `active` (else archive it)" % target)

    def test_archived_rows_point_at_archive_files_with_an_end_state(self):
        rows = section_rows("## Archived")
        for target, status in rows:
            self.assertTrue(target.startswith("archive/"), target)
            self.assertTrue((PLANS / target).exists(), "INDEX points at a missing file: %s" % target)
            self.assertIn(status, STATES[1:], "%s: archived status must be done/superseded/abandoned" % target)
        listed = {t for t, _ in rows}
        for p in (PLANS / "archive").rglob("*.md"):
            if p.name == "README.md":
                continue
            rel = p.relative_to(PLANS).as_posix()
            self.assertIn(rel, listed, "%s is archived but has no INDEX row" % rel)

    def test_every_active_plan_states_its_direction_fit(self):
        # align/D: judged against docs/CONCEPT.md; a new plan states its fit under its title, and INDEX shows it
        grades = {"핵심", "기반", "개발 기반", "개발판 전용", "정렬"}
        index = (PLANS / "INDEX.md").read_text(encoding="utf-8")
        for target, _ in section_rows("## Active"):
            head = "\n".join((PLANS / target).read_text(encoding="utf-8").splitlines()[:6])
            m = re.search(r"^> 방향 \([^)]*\): \*\*(.+?)\*\* — \S", head, re.M)
            self.assertTrue(m, "%s: add `> 방향 (…): **등급** — 이유` under the title (grades: %s)" % (target, sorted(grades)))
            for g in m.group(1).split(" + "):
                self.assertIn(g, grades, "%s: unknown direction grade %r" % (target, g))
            row = next(l for l in index.splitlines() if "](%s)" % target in l)
            self.assertIn("방향 **%s**" % m.group(1), row, "%s: INDEX row must show 방향 **%s**" % (target, m.group(1)))

    def test_a_plan_states_the_same_status_as_its_row(self):
        for target, status in section_rows("## Active"):
            head = (PLANS / target).read_text(encoding="utf-8")[:1500]
            m = re.search(r"상태\s*[:：]\s*\**`?([a-z]+)", head)
            if m and m.group(1) in STATES:
                self.assertEqual(m.group(1), status, "%s says %s, INDEX says %s" % (target, m.group(1), status))


if __name__ == "__main__":
    unittest.main()
