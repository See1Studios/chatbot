"""Every rule in root AGENTS.md's registry names its audience and its enforcer (plan-execution-workflow §0: a rule that
lives only in a document is no rule). An enforcer outside parentheses must exist: a test module, or a repo file;
otherwise the row says `manual` (a planned enforcer may follow in parentheses).
Run: python3 -m unittest tests.test_rule_registry  (from services/chatbot)
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIENCES = {"all", "PE chat agent only"}


def registry_rows():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    block = text[text.index("## Rule registry"):]
    block = block[:block.find("\n## ", 5)] if block.find("\n## ", 5) > 0 else block
    rows = []
    for line in block.splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| Rule "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        rows.append(cells)
    return rows


class RuleRegistry(unittest.TestCase):
    def test_there_is_a_registry(self):
        self.assertGreater(len(registry_rows()), 10)

    def test_each_row_has_an_audience_and_a_real_enforcer(self):
        for cells in registry_rows():
            self.assertEqual(len(cells), 3, "registry row needs rule | audience | enforcer: %r" % cells)
            rule, audience, enforcer = cells
            self.assertIn(audience, AUDIENCES, "%s: audience must be one of %s" % (rule, sorted(AUDIENCES)))
            now = re.sub(r"\([^)]*\)", "", enforcer)          # parenthesised = planned, not checked
            tests = re.findall(r"\btest_\w+", now)
            for t in tests:
                self.assertTrue((ROOT / "tests" / (t + ".py")).exists(), "%s: enforcer %s does not exist" % (rule, t))
            paths = [p for p in re.findall(r"`([\w./-]+\.(?:py|md|json|sh))`", now)]
            for p in paths:
                self.assertTrue((ROOT / p).exists(), "%s: enforcer file %s does not exist" % (rule, p))
            self.assertTrue("manual" in now or tests or paths,
                            "%s: name an existing enforcer or say manual" % rule)


if __name__ == "__main__":
    unittest.main()
