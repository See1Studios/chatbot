"""Python modules stay small enough for an agent to read whole (AGENT_FIRST_v1, monolith-split Phase 5). A module over
the cap is split by what it does; the few already over it may not grow past the ceiling pinned here -- lower a ceiling
when you shrink one, never raise it.
Run: python3 -m unittest tests.test_file_sizes  (from services/chatbot)
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_LINES = 1500
CEILINGS = {"session.py": 2335, "server.py": 1538}   # over the cap already: no growth


def modules():
    return sorted(list(ROOT.glob("*.py")) + list((ROOT / "tools").glob("*.py")) + list((ROOT / "providers").glob("*.py")))


class FileSizes(unittest.TestCase):
    def test_every_module_stays_under_its_cap(self):
        for p in modules():
            n = len(p.read_text(encoding="utf-8").splitlines())
            limit = CEILINGS.get(p.name, MAX_LINES)
            self.assertLessEqual(n, limit, "%s has %d lines (cap %d): split it by what it does" % (p.name, n, limit))

    def test_ceilings_are_only_for_modules_really_over_the_cap(self):
        for name, ceiling in CEILINGS.items():
            n = len((ROOT / name).read_text(encoding="utf-8").splitlines())
            self.assertGreater(n, MAX_LINES, "%s is under the cap now: drop its ceiling" % name)
            self.assertLessEqual(ceiling - n, 50, "%s shrank to %d: lower its ceiling" % (name, n))


if __name__ == "__main__":
    unittest.main()
