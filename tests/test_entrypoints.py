"""One entry for every agent that changes this repo (plan-execution-workflow pew/C-D, pew/S): root AGENTS.md is the
dev-build entry -- short, read first, never the chat agent's runtime rules. CLAUDE.md and GEMINI.md exist only because
tools auto-load those names, and point to it. The standing documents agents read (the guidance and the project
documents: readme, concept, product, design, history) sit beside it at the root; docs/ holds folders only -- plans,
provider notes, older history (operator 2026-10-08).
Run: engine/run-tests.sh test_entrypoints
"""
import subprocess
import unittest
from pathlib import Path
from tests._paths import ENGINE, REPO  # noqa: E402

ROOT = REPO
POINTERS = ("CLAUDE.md", "GEMINI.md")
GUIDANCE = {"RULES.md", "CODEMAP.md", "ARCHITECTURE.md", "OPERATIONS.md"}
PROJECT_DOCS = {"README.md", "CONCEPT.md", "PRODUCT.md", "DESIGN.md", "HISTORY.md"}
STANDING_DOCS = {"AGENTS.md"} | GUIDANCE | PROJECT_DOCS
KO_MIRRORS = {f"{p.rsplit('.md', 1)[0]}.ko.md" for p in STANDING_DOCS}
ENTRY_FILES = {"AGENTS.md"} | set(POINTERS) | GUIDANCE | PROJECT_DOCS | KO_MIRRORS
MAX_POINTER_LINES = 5
MAX_ENTRY_BYTES = 6_000   # every agent reads it first, whole: more goes to RULES.md, CODEMAP.md
DOC_SUFFIXES = (".md", ".markdown", ".rst", ".txt", ".adoc")
NOT_DOCS = {"requirements.txt"}   # read by a tool, not a person


class EntryPoints(unittest.TestCase):
    def test_root_agents_md_is_the_short_dev_entry(self):
        raw = (ROOT / "AGENTS.md").read_bytes()
        text = raw.decode("utf-8")
        self.assertLessEqual(len(raw), MAX_ENTRY_BYTES, "AGENTS.md is %d bytes: move detail to docs/" % len(raw))
        self.assertIn("dev build only", text.splitlines()[0])
        for section in ("## Your role", "## Start here", "## How to make a change", "## Rules you must not break",
                        "## Where facts live"):
            self.assertIn(section, text, "AGENTS.md lost its %r section" % section)
        for target in ("CODEMAP.md", "RULES.md"):
            self.assertIn(target, text)
            self.assertTrue((ROOT / target).is_file(), target)
        self.assertNotIn("<!--choices", text, "chat-runtime conventions belong to the shipped charter")
        self.assertNotIn("## Code map", text, "the code map is CODEMAP.md")

    def test_the_root_holds_no_other_document(self):
        out = subprocess.check_output(["git", "ls-files"], cwd=str(ROOT), text=True, timeout=20)
        root_docs = sorted(n for n in out.splitlines() if "/" not in n and n.lower().endswith(DOC_SUFFIXES)
                           and n not in NOT_DOCS)
        self.assertEqual([n for n in root_docs if n not in ENTRY_FILES], [],
                         "only the entry files and the standing documents at the repo root; others go in a docs/ folder")

    def test_docs_holds_folders_only(self):
        out = subprocess.check_output(["git", "ls-files", "docs"], cwd=str(ROOT), text=True, timeout=20)
        loose = sorted(n for n in out.splitlines() if n.count("/") == 1)
        self.assertEqual(loose, [], "docs/ holds folders only: a standing document goes at the repo root, others in "
                                    "docs/plans/, docs/providers/ or docs/history/")

    def test_tool_named_files_only_point_to_it(self):
        for name in POINTERS:
            lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
            self.assertLessEqual(len(lines), MAX_POINTER_LINES,
                                 "%s is a pointer: keep rules in AGENTS.md, not here" % name)
            self.assertIn("](./AGENTS.md)", "\n".join(lines), "%s must link ./AGENTS.md" % name)

    def test_the_chat_charter_does_not_carry_the_engine_code_map(self):
        paths = [ROOT / "templates" / "workspace" / "AGENTS.md"]
        live = ENGINE / "data" / "workspace" / "AGENTS.md"
        if live.is_file():
            paths.append(live)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("## Code map", text, "the code map lives in CODEMAP.md only (%s)" % path.name)


if __name__ == "__main__":
    unittest.main()
