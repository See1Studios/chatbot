"""P2 no-trace check (docs/plans/recursive-self-evolution.md §4.6): the deployable core, its injected rules, the status API
and the user-facing docs carry no name, path or link of the external tool the observation core was modelled on,
and the workspace holds no link into shared global skills.

Plans, logs (DEVLOG, observation log, sessions) and generated prompt dumps are not deployable and are not scanned.
Run: python3 -m unittest tests.test_no_trace  (from services/chatbot)
"""
import re
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
# built from parts so this file does not contain what it forbids
FORBIDDEN = re.compile("|".join(["task" + sep + "observer" for sep in ("-", "_", "")]), re.IGNORECASE)
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".json", ".sh", ".txt", ".yml", ".yaml"}


def deployable_files():
    out = [p for p in CODE.glob("*.py")]
    out += [CODE / n for n in ("README.md", "PROJECT.md", "PRODUCT.md", "DESIGN.md", "chatbot-ctl.sh",
                               "protected_paths.json", "observation_signals.json")]
    for sub in ("static", "templates"):
        out += [p for p in (CODE / sub).rglob("*") if p.is_file() and "vendor" not in p.parts]
    ws = CODE / "data" / "workspace"
    out += [p for p in ws.glob("*.md")]
    out += [p for p in (ws / ".agents").rglob("*") if p.is_file()]
    return sorted(p for p in out if p.is_file() and p.suffix in TEXT_SUFFIXES)


class NoTraceTest(unittest.TestCase):
    def test_the_scan_actually_covers_the_core(self):
        names = {p.name for p in deployable_files()}
        for must in ("observations.py", "evolution.py", "session.py", "app.js", "AGENTS.md", "SKILL.md", "README.md"):
            self.assertIn(must, names)

    def test_no_deployable_file_names_the_external_tool(self):
        hits = []
        for p in deployable_files():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append("%s:%d" % (p.relative_to(CODE), n))
        self.assertEqual(hits, [], "trace of the external tool in deployable files")

    def test_the_workspace_has_no_link_out_and_no_provider_hook_config(self):
        ws = CODE / "data" / "workspace"
        skills = ws / ".agents" / "skills"
        if skills.is_dir():
            for entry in skills.iterdir():
                self.assertFalse(entry.is_symlink(), "%s is a link; skills are owned by this workspace" % entry.name)
        self.assertFalse((ws / ".agents" / "hooks.json").exists(), "observation is collected by the host, not by a provider hook")
        self.assertFalse((ws / ".agents" / "scripts").exists())


if __name__ == "__main__":
    unittest.main()
