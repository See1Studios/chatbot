"""docs/plans/INDEX.md is the plan-status SSOT (INDEX "아카이브 절차", plan-execution-workflow pew/D): every plan file has
exactly one row, active rows point at docs/plans/*.md, archived rows at archive/YYYY/*.md, every status cell starts with
one of the four values, and a plan's own "상태" line agrees with its row.
Run: engine/run-tests.sh test_plans_index
"""
import re
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

PLANS = REPO / "docs" / "plans"
# Active plans written before the prior-art line (#862, 2026-10-09). It only shrinks: a new plan carries the line.
BEFORE_PRIOR_ART = {
    "api-adapter-parity.md", "character-creation-landing.md", "character-events-and-rooms.md", "character-resource-pipeline.md", "direction-alignment.md", "director-handoff.md",
    "edition-boundary.md", "group-room-header.md", "improvement-layers.md", "localization.md",
    "market-direction-review.md", "multi-agent-worktree-delegation.md",
    "personalization-ladder.md", "plan-execution-workflow.md",
    "platform-portability.md", "plugin-architecture.md", "private-engine-brand.md", "private-mode.md",
    "private-security.md", "quota-failure-resilience.md", "regenerate-swipe.md", "release-pipeline.md",
    "setting-pack.md", "steam-collab-dlc.md", "telemetry.md", "token-economy.md", "ux-shell-roadmap.md", "voice-and-audio-interaction.md",
}
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
        # align/D: judged against VISION.md; a new plan states its fit under its title, and INDEX shows it
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


    def test_a_new_plan_names_its_prior_art_hermes_first(self):
        # #862 (operator 2026-10-09): before building, look at the host's Hermes Agent first; a plan records it
        for target, _ in section_rows("## Active"):
            if target in BEFORE_PRIOR_ART:
                continue
            head = "\n".join((PLANS / target).read_text(encoding="utf-8").splitlines()[:12])
            m = re.search(r"^> 선행 사례: (.+)$", head, re.M)
            self.assertTrue(m, "%s: add `> 선행 사례: Hermes <how it does it, follow/adapt/differ> · <others>` under the "
                               "title, or `> 선행 사례: Hermes 해당 없음 — <why>` (~/.hermes/hermes-agent/)" % target)
            self.assertIn("Hermes", m.group(1), "%s: the prior-art line looks at Hermes first" % target)

    def test_the_grandfathered_list_only_shrinks(self):
        active = {t for t, _ in section_rows("## Active")}
        self.assertEqual(sorted(BEFORE_PRIOR_ART - active), [], "archived or renamed: drop it from BEFORE_PRIOR_ART")

if __name__ == "__main__":
    unittest.main()
