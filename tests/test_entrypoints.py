"""One entry for every agent that changes this repo (plan-execution-workflow pew/C-D): root AGENTS.md holds the engine
rules; CLAUDE.md and GEMINI.md exist only because tools auto-load those names, and point to it without copying rules.
Run: python3 -m unittest tests.test_entrypoints  (from services/chatbot)
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POINTERS = ("CLAUDE.md", "GEMINI.md")
MAX_POINTER_LINES = 5


class EntryPoints(unittest.TestCase):
    def test_root_agents_md_is_the_entry(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for section in ("## Start order", "## SSOT map", "## Code map", "## Rule registry"):
            self.assertIn(section, text, "AGENTS.md lost its %r section" % section)

    def test_tool_named_files_only_point_to_it(self):
        for name in POINTERS:
            lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
            self.assertLessEqual(len(lines), MAX_POINTER_LINES,
                                 "%s is a pointer: keep rules in AGENTS.md, not here" % name)
            self.assertIn("](./AGENTS.md)", "\n".join(lines), "%s must link ./AGENTS.md" % name)

    def test_the_chat_charter_does_not_carry_the_engine_code_map(self):
        paths = [ROOT / "templates" / "workspace" / "AGENTS.md"]
        live = ROOT / "data" / "workspace" / "AGENTS.md"
        if live.is_file():
            paths.append(live)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("## Code map", text, "the code map lives in root AGENTS.md only (%s)" % path.name)


if __name__ == "__main__":
    unittest.main()
