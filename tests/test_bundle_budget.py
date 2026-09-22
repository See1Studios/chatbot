"""The instruction layers injected on every first turn stay within their byte budget (bundle_budget.json).

The token tax of always-injected text is the quiet cost of self-improvement: every rule added "just in case" is paid
by every session. The budget makes growth a decision: raising bundle_budget.json is the human operator's call, and the
guidance that has moved into the core (tool descriptions, refusals, tests) is what should be deleted here first.
Run: python3 -m unittest tests.test_bundle_budget  (from services/chatbot)
"""
import json
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import evolution  # noqa: E402
import instructions as I  # noqa: E402

BUDGET = json.loads((CODE / "bundle_budget.json").read_text(encoding="utf-8"))


def static_bytes():
    static = "\n\n".join(t for t in (I._rules_text(), I._skills_text()) if t)
    return len(static.encode("utf-8"))


class BundleBudgetTest(unittest.TestCase):
    def test_the_static_layers_fit_the_budget(self):
        size, limit = static_bytes(), BUDGET["static_max_bytes"]
        self.assertLessEqual(
            size, limit,
            "charter + persona + skill index are %d bytes, budget %d. Delete guidance the core already carries "
            "(tool descriptions, refusals) before asking the operator to raise bundle_budget.json." % (size, limit))

    def test_the_budget_is_a_real_bound_not_a_formality(self):
        self.assertLess(BUDGET["static_max_bytes"], 8000)
        self.assertGreater(BUDGET["static_max_bytes"], 0)

    def test_every_skill_index_line_stays_short(self):
        for line in I._skills_text().splitlines()[1:]:
            self.assertLessEqual(len(line), 120, line)

    def test_the_budget_and_its_reading_are_not_writable_by_the_agent(self):
        self.assertTrue(evolution.is_protected(CODE, CODE / "bundle_budget.json"))

    def test_the_dynamic_layers_are_bounded_by_the_memory_cap(self):
        import memory_store
        bundle = I.build_instruction_bundle()["text"]
        dynamic = len(bundle.encode("utf-8")) - static_bytes()
        self.assertLessEqual(dynamic, memory_store.MAX_BYTES + 600)  # memory snapshot + the one-line status badge

    def test_charter_does_not_point_at_the_shell_memory_fallback(self):
        text = (I.WORKSPACE / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("tools/memory.py", text)
        self.assertNotIn("셸이 있으면", text)

    def test_persona_defers_appearance_to_the_visual_readme(self):
        text = (I.WORKSPACE / "PERSONA.md").read_text(encoding="utf-8")
        self.assertNotIn("풀 수인", text)
        self.assertIn("data/persona/README.md", text)


if __name__ == "__main__":
    unittest.main()
