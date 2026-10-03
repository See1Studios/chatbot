"""Every code file has a row in AGENTS.md's code map (CODE_MAP_v1, split/H): "Fix the row before adding a file" held
only by habit, and 11 modules, 7 tools and 30 page files were missing when it was measured (2026-10-04). An agent
that cannot find a file in the map edits the wrong one or makes a second.
A name counts when the "## Code map" section holds it in backticks: `x.py`, `tools/x.py`, or a brace list such as
`app-{api,device}.js`.
Run: python3 -m unittest tests.test_code_map  (from services/chatbot)
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOBS = ["*.py", "providers/*.py", "tools/*.py", "static/*.js", "static/*.css"]
DIRS = {".", "providers", "tools", "static"}
SKIP = {"__init__.py"}


def code_map() -> str:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    m = re.search(r"^## Code map\b(.*?)^## ", text, re.S | re.M)
    return m.group(1) if m else ""


def named(section: str) -> set:
    out = set()
    for tok in re.findall(r"`([^`\s]+)`", section):
        b = re.match(r"^(.*)\{([^}]*)\}(.*)$", tok)
        for t in (b.group(1) + x + b.group(3) for x in b.group(2).split(",")) if b else [tok]:
            out.add(t.split("::")[0].split(" ")[0])
    return out


def code_files() -> list:
    try:   # tracked files only: an untracked file in a shared tree is someone's work in progress
        out = subprocess.check_output(["git", "ls-files", "--"] + GLOBS, cwd=str(ROOT), text=True, timeout=20)
        files = [ln for ln in out.splitlines() if str(Path(ln).parent) in DIRS]
    except (OSError, subprocess.SubprocessError):
        files = [str(p.relative_to(ROOT)) for g in GLOBS for p in ROOT.glob(g)]
    return sorted(f for f in files if Path(f).name not in SKIP)


class CodeMap(unittest.TestCase):
    def test_section_found(self):
        self.assertTrue(code_map(), "AGENTS.md has no '## Code map' section")

    def test_every_code_file_has_a_row(self):
        names = named(code_map())
        missing = [f for f in code_files()
                   if f not in names and Path(f).name not in names and f.split("/", 1)[-1] not in names]
        self.assertEqual(missing, [], "not in AGENTS.md's code map: add each to its row (or a new row) in backticks")

    def test_brace_lists_expand(self):
        self.assertEqual(named("`app-{a,b}.js` `x.py::f`"), {"app-a.js", "app-b.js", "x.py"})


if __name__ == "__main__":
    unittest.main()
