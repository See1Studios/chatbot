"""The instruction layers injected on every first turn stay within their byte budget (bundle_budget.json).

The token tax of always-injected text is the quiet cost of self-improvement: every rule added "just in case" is paid
by every session. The budget makes growth a decision: raising bundle_budget.json is the human operator's call, and the
guidance that has moved into the core (tool descriptions, refusals, tests) is what should be deleted here first.
Run: engine/run-tests.sh test_bundle_budget
"""
import json
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
sys.path.insert(0, str(ENGINE))
import evolution  # noqa: E402
import instructions as I  # noqa: E402

BUDGET = json.loads((ENGINE / "bundle_budget.json").read_text(encoding="utf-8"))


def static_bytes():
    static = "\n\n".join(t for t in (I._rules_text(), I._skills_text()) if t)
    return len(static.encode("utf-8"))


def _charter_text():
    live = I.WORKSPACE / "AGENTS.md"
    if live.is_file():
        return live.read_text(encoding="utf-8")
    return (CODE / "templates" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")


class BundleBudgetTest(unittest.TestCase):
    def test_the_static_layers_fit_the_budget(self):
        size, limit = static_bytes(), BUDGET["static_max_bytes"]
        self.assertLessEqual(
            size, limit,
            "charter + persona + skill index are %d bytes, budget %d. Delete guidance the core already carries "
            "(tool descriptions, refusals) before asking the operator to raise bundle_budget.json." % (size, limit))

    def test_a_private_session_fits_the_same_budget_without_work_procedure(self):
        # PRIVATE_BUDGET_v1: charter preamble + safety sections, the card, the host note and the private rules
        text = I.build_instruction_bundle(mode="private")["text"]
        static = text.split("\n\n[Private memory]")[0].split("\n\n[Name changes]")[0]   # both dynamic (NAME_CHANGE_v1)
        self.assertLessEqual(len(static.encode("utf-8")), BUDGET["static_max_bytes"])
        for work in ("## Self-modification", "## Memory", "## Approval first", "## Progress"):
            self.assertNotIn(work, text)

    def test_the_private_charter_sections_still_exist(self):
        # a renamed charter heading would silently drop a safety rule from private sessions
        charter = _charter_text()
        for name in I.PRIVATE_CHARTER_SECTIONS:
            self.assertIn("\n## %s\n" % name, charter)

    def test_the_budget_is_a_real_bound_not_a_formality(self):
        self.assertLess(BUDGET["static_max_bytes"], 8000)
        self.assertGreater(BUDGET["static_max_bytes"], 0)

    def test_every_skill_index_line_stays_short(self):
        for line in I._skills_text().splitlines()[1:]:
            self.assertLessEqual(len(line), 120, line)

    def test_the_budget_and_its_reading_are_not_writable_by_the_agent(self):
        self.assertTrue(evolution.is_protected(CODE, ENGINE / "bundle_budget.json"))

    def test_the_dynamic_layers_are_bounded_by_the_memory_cap(self):
        import memory_store
        bundle = I.build_instruction_bundle()["text"]
        dynamic = len(bundle.encode("utf-8")) - static_bytes()
        self.assertLessEqual(dynamic, memory_store.MAX_BYTES + 600)  # memory snapshot + the one-line status badge

    def test_charter_does_not_point_at_the_shell_memory_fallback(self):
        text = _charter_text()
        self.assertNotIn("tools/memory.py", text)
        self.assertNotIn("셸이 있으면", text)

    def test_persona_defers_appearance_to_the_visual_sheet(self):
        import identity
        text = identity.persona_body()                  # the chatbot's card, when this tree has one
        if not text.strip():
            self.skipTest("no persona card in this tree")
        self.assertNotIn("풀 수인", text)
        self.assertIn("visual.md", text)
        self.assertIn("character-art", text)


if __name__ == "__main__":
    unittest.main()
