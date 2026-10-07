"""Convention checks (CONVENTION_v1, prop/B; trimmed prop/F). Conventions in RULES.md that code can show:
(a) every blocking subprocess call (run, check_output, check_call, call) names an explicit timeout (legacy allowlist);
(b) the size numbers RULES.md states are the ones tests/test_file_sizes.py enforces.
Test pairing is the commit-msg hook's (test_githooks); a check that a document contains a phrase guards nothing and is
not kept here.

Run: python3 -m unittest tests.test_conventions  (from services/chatbot)
"""
import ast
import re
import unittest
from pathlib import Path
from typing import Dict, List, Tuple
from tests._paths import ENGINE, REPO  # noqa: E402

BLOCKING = ("run", "check_output", "check_call", "call")

ROOT = REPO
DOCS = ROOT / "docs"

# Legitimate legacy exemptions for subprocess.run without explicit timeout.
# This table is the backlog (RULES.md, Timeouts): it only shrinks.
LEGACY_SUBPROCESS_EXEMPTIONS: Dict[str, str] = {}   # emptied 2026-10-07 (prop/I); keep it empty


def target_modules() -> List[Path]:
    """Target python modules in root, tools/, and providers/."""
    return sorted(list(ENGINE.glob("*.py")) + list((ENGINE / "tools").glob("*.py")) + list((ENGINE / "providers").glob("*.py")))


def find_subprocess_run_calls(path: Path) -> List[Tuple[str, int, bool]]:
    """AST-based inspection for subprocess.run calls.
    Returns list of (qualname, lineno, has_timeout).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    calls: List[Tuple[str, int, bool]] = []
    imported = {(a.asname or a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "subprocess"
                for a in n.names if a.name in BLOCKING}

    def check_call(node: ast.AST, qualname: str) -> None:
        if not isinstance(node, ast.Call):
            return
        func = node.func
        is_sub = False
        if isinstance(func, ast.Attribute) and func.attr in BLOCKING:
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                is_sub = True
        elif isinstance(func, ast.Name) and func.id in imported:
            is_sub = True
        if is_sub:
            has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
            calls.append((qualname, node.lineno, has_timeout))

    def walk(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                sub_scope = f"{scope}.{child.name}" if scope else child.name
                walk(child, sub_scope)
            else:
                if isinstance(child, ast.Call):
                    check_call(child, scope or "<module>")
                walk(child, scope)

    walk(tree, "")
    return calls


class TestConventions(unittest.TestCase):
    def test_subprocess_run_calls_specify_timeout(self):
        """All subprocess.run calls in core, tools, and provider modules must specify timeout unless exempt."""
        violations = []
        for path in target_modules():
            rel = path.relative_to(ROOT).as_posix()
            for qualname, lineno, has_timeout in find_subprocess_run_calls(path):
                if not has_timeout:
                    key = f"{rel}::{qualname}"
                    if key not in LEGACY_SUBPROCESS_EXEMPTIONS:
                        violations.append(f"{rel}:{lineno} in {qualname} makes a blocking subprocess call without timeout")
        self.assertEqual(
            violations,
            [],
            "blocking subprocess calls without timeout (RULES.md, Timeouts):\n" + "\n".join(violations),
        )

    def test_legacy_exemptions_are_active(self):
        """Exemptions in LEGACY_SUBPROCESS_EXEMPTIONS must correspond to actual calls without timeout."""
        active_missing = set()
        for path in target_modules():
            rel = path.relative_to(ROOT).as_posix()
            for qualname, _, has_timeout in find_subprocess_run_calls(path):
                if not has_timeout:
                    active_missing.add(f"{rel}::{qualname}")

        for key, reason in LEGACY_SUBPROCESS_EXEMPTIONS.items():
            self.assertIn(
                key,
                active_missing,
                f"Exemption {key} is obsolete (no subprocess.run without timeout found); remove from allowlist.",
            )
            self.assertTrue(reason.strip(), f"Exemption {key} must have a documented reason.")

    def test_the_size_numbers_in_convention_are_the_enforced_ones(self):
        from tests.test_file_sizes import FUNC_MAX_LINES, MAX_BYTES
        text = (ROOT / "RULES.md").read_text(encoding="utf-8")
        m_lines = re.search(r"FUNC_MAX_LINES\s*=\s*(\d+)", text)
        m_bytes = re.search(r"MAX_BYTES\s*=\s*([0-9_]+)", text)
        self.assertIsNotNone(m_lines, "RULES.md must state FUNC_MAX_LINES")
        self.assertIsNotNone(m_bytes, "RULES.md must state MAX_BYTES")
        self.assertEqual(int(m_lines.group(1)), FUNC_MAX_LINES, "RULES.md and test_file_sizes disagree")
        self.assertEqual(int(m_bytes.group(1).replace("_", "")), MAX_BYTES, "RULES.md and test_file_sizes disagree")

if __name__ == "__main__":
    unittest.main()
