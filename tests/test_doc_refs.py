"""Documents agents act on do not rot (plan-execution-workflow §0): in active plans, decisions and root AGENTS.md,
relative links resolve, code is cited as `path` or `path::symbol` (the symbol must still be in that file), and never
by line number -- line numbers are wrong after the next edit.
Run: python3 -m unittest tests.test_doc_refs  (from services/chatbot)
"""
import re
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

ROOT = REPO
EXT = r"(?:py|js|sh|css|json|md|html)"
LINE_REF = re.compile(r"[\w./-]+\." + EXT + r"`?(?::L?\d+|\s+L\d+)\b")
SYMBOL_REF = re.compile(r"`([\w./-]+\.(?:py|js|sh|css))::([\w.]+)`")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def docs():
    plans = [p for p in (ROOT / "docs" / "plans").glob("*.md")]
    return plans + sorted((ROOT / "docs" / "decisions").glob("*.md")) + [ROOT / "AGENTS.md", ROOT / "CODEMAP.md", ROOT / "RULES.md"]


class DocRefs(unittest.TestCase):
    def test_relative_links_resolve(self):
        for doc in docs():
            for target in LINK.findall(doc.read_text(encoding="utf-8")):
                if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                    continue
                path = target.split("#", 1)[0]
                self.assertTrue((doc.parent / path).exists(), "%s links to missing %s" % (doc.name, target))

    def test_no_line_number_references(self):
        for doc in docs():
            for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                m = LINE_REF.search(line)
                self.assertIsNone(m, "%s:%d cites %r by line number: use `path::symbol`" % (doc.name, n, m and m.group(0)))

    def test_symbol_references_still_exist(self):
        for doc in docs():
            for path, symbol in SYMBOL_REF.findall(doc.read_text(encoding="utf-8")):
                f = ROOT / path
                self.assertTrue(f.exists(), "%s cites missing file %s" % (doc.name, path))
                name = symbol.split(".")[-1]
                self.assertRegex(f.read_text(encoding="utf-8"), r"\b%s\b" % re.escape(name),
                                 "%s cites %s::%s, which is gone" % (doc.name, path, symbol))


if __name__ == "__main__":
    unittest.main()
