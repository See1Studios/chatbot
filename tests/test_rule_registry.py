"""Every rule in root AGENTS.md's registry names its audience and its enforcer (plan-execution-workflow §0: a rule that
lives only in a document is no rule). An enforcer outside parentheses must exist: a test module, or a repo file;
otherwise the row says `manual` (a planned enforcer may follow in parentheses). An enforcer is itself guarded (prop/F,
2026-10-07: two tests were red on main and no commit ran them): it is Tier 3 (`protected_paths.json` governance, so
only the operator weakens it) and it runs on every commit (`run-tests.sh` FAST) unless SLOW below names why not.
Run: python3 -m unittest tests.test_rule_registry  (from services/chatbot)
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIENCES = {"all", "PE chat agent only"}
SLOW = {   # enforcers too slow for every commit: where they run instead
    "test_worktree_runner": "about 90 s; the delegation runner's own changes and the full suite before release",
    "test_ticket_quick": "about 45 s; the full suite before release",
}


def enforcers():
    """(rule, test module names, repo file paths) of each row, planned ones (in parentheses) left out."""
    out = []
    for rule, _audience, enforcer in registry_rows():
        now = re.sub(r"\([^)]*\)", "", enforcer)
        out.append((rule, re.findall(r"\btest_\w+", now), re.findall(r"`([\w./-]+\.(?:py|md|json|sh))`", now)))
    return out


def governed(path, tier3):
    return any(path == g or (g.endswith("/") and path.startswith(g)) for g in tier3)


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


    def test_every_enforcer_is_tier_3_and_runs_on_commit(self):
        tier3 = [g["path"] for g in json.loads((ROOT / "protected_paths.json").read_text(encoding="utf-8"))["governance"]]
        fast = re.search(r"FAST=\((.*?)\)", (ROOT / "run-tests.sh").read_text(encoding="utf-8"), re.S).group(1).split()
        for rule, tests, paths in enforcers():
            for t in tests:
                self.assertTrue(governed("tests/%s.py" % t, tier3),
                                "%s: enforcer %s is not Tier 3 -- add it to protected_paths.json governance" % (rule, t))
                self.assertTrue(t in fast or t in SLOW,
                                "%s: enforcer %s runs on no commit -- add it to run-tests.sh FAST (or SLOW here, "
                                "with why)" % (rule, t))
            for p in paths:
                self.assertTrue(governed(p, tier3), "%s: enforcer file %s is not Tier 3" % (rule, p))

    def test_slow_enforcers_are_still_enforcers(self):
        named = {t for _r, tests, _p in enforcers() for t in tests}
        self.assertEqual(sorted(set(SLOW) - named), [], "SLOW names a test no rule uses: remove it")


if __name__ == "__main__":
    unittest.main()
