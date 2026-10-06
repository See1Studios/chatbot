"""Convention verification test suite (CONVENTION_v1, prop/B).
Enforces static verification of rules declared in docs/CONVENTION.md:
(a) Subprocess calls specify an explicit timeout (with legitimate legacy allowlist).
(b) Governance numeric consistency between docs/CONVENTION.md and tests/test_file_sizes.py (80 lines, 80KB, 30s).
(c) Mandatory Test Pairing and Work Banter Limit conventions registered in CONVENTION.md and STATE.md.

Run: python3 -m unittest tests.test_conventions  (from services/chatbot)
"""
import ast
import re
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# Legitimate legacy exemptions for subprocess.run without explicit timeout.
# Tracked under [DRIFT-002] in docs/STATE.md pending subsequent batch remediation.
LEGACY_SUBPROCESS_EXEMPTIONS: Dict[str, str] = {
    "tickets.py::_guard_failure": "Fast local git cat-file and worktree operations for guard runner",
    "tools/devlog_entry.py::_git": "Local git query helper for devlog formatting",
    "tools/handoff_drill.py::build": "Sandbox bootstrap execution in handoff drill",
    "tools/handoff_drill.py::stop": "Local process reap in handoff drill teardown",
    "tools/migrate_user_data.py::_tracked": "Local git rev-parse and ls-files check for user data migration",
}


def target_modules() -> List[Path]:
    """Target python modules in root, tools/, and providers/."""
    return sorted(list(ROOT.glob("*.py")) + list((ROOT / "tools").glob("*.py")) + list((ROOT / "providers").glob("*.py")))


def find_subprocess_run_calls(path: Path) -> List[Tuple[str, int, bool]]:
    """AST-based inspection for subprocess.run calls.
    Returns list of (qualname, lineno, has_timeout).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    calls: List[Tuple[str, int, bool]] = []
    imported_run = any(
        isinstance(n, ast.ImportFrom) and n.module == "subprocess"
        and any((a.asname or a.name) == "run" for a in n.names)
        for n in ast.walk(tree)
    )

    def check_call(node: ast.AST, qualname: str) -> None:
        if not isinstance(node, ast.Call):
            return
        func = node.func
        is_sub = False
        if isinstance(func, ast.Attribute) and func.attr == "run":
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                is_sub = True
        elif isinstance(func, ast.Name) and func.id == "run" and imported_run:
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
                        violations.append(f"{rel}:{lineno} in {qualname} calls subprocess.run without timeout")
        self.assertEqual(
            violations,
            [],
            "subprocess.run calls without timeout found (violates CONVENTION.md §2.3):\n" + "\n".join(violations),
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

    def test_governance_numeric_consistency(self):
        """Numeric limits in CONVENTION.md must match test_file_sizes.py and governance specifications."""
        from tests.test_file_sizes import FUNC_MAX_LINES, MAX_BYTES

        convention_path = DOCS / "CONVENTION.md"
        self.assertTrue(convention_path.is_file(), "docs/CONVENTION.md must exist")
        text = convention_path.read_text(encoding="utf-8")

        m_lines = re.search(r"FUNC_MAX_LINES\s*=\s*(\d+)", text)
        self.assertIsNotNone(m_lines, "CONVENTION.md must specify FUNC_MAX_LINES")
        self.assertEqual(int(m_lines.group(1)), FUNC_MAX_LINES)
        self.assertEqual(FUNC_MAX_LINES, 80, "Standard function limit is 80 lines")
        self.assertIn("80줄", text, "CONVENTION.md must describe 80줄 limit")

        m_bytes = re.search(r"MAX_BYTES\s*=\s*([0-9_]+)", text)
        self.assertIsNotNone(m_bytes, "CONVENTION.md must specify MAX_BYTES")
        self.assertEqual(int(m_bytes.group(1).replace("_", "")), MAX_BYTES)
        self.assertEqual(MAX_BYTES, 80_000, "Standard module limit is 80,000 bytes")
        self.assertIn("80,000 바이트", text, "CONVENTION.md must describe 80,000 바이트 limit")

        m_timeout = re.search(r"(\d+)초\s*타임아웃", text)
        self.assertIsNotNone(m_timeout, "CONVENTION.md must specify timeout convention")
        self.assertEqual(int(m_timeout.group(1)), 30, "Default convention timeout is 30 seconds")

    def test_mandatory_test_pairing_and_banter_limit_registered(self):
        """Mandatory Test Pairing and banter limit rules must be registered in CONVENTION.md and STATE.md."""
        convention_text = (DOCS / "CONVENTION.md").read_text(encoding="utf-8")
        state_text = (DOCS / "STATE.md").read_text(encoding="utf-8")

        self.assertIn("Mandatory Test Pairing", convention_text, "CONVENTION.md must define Mandatory Test Pairing")
        self.assertIn("Mandatory Test Pairing", state_text, "STATE.md must track Mandatory Test Pairing")

        self.assertIn("사담 상한", convention_text, "CONVENTION.md must define 사담 상한 (Work Banter Limit)")
        self.assertRegex(convention_text, r"1\s*~\s*2\s*문장", "CONVENTION.md must state 1~2 sentence banter limit")
        self.assertIn("사담 상한", state_text, "STATE.md must record 사담 상한 convention")

    def test_state_ledger_dev_prop_001_tracked(self):
        """STATE.md must track [DEV-PROP-001] with test_conventions.py checklist marked complete."""
        state_text = (DOCS / "STATE.md").read_text(encoding="utf-8")
        self.assertIn("[DEV-PROP-001]", state_text, "STATE.md must have [DEV-PROP-001] entry")

        pattern = r"-\s*\[x\]\s*`tests/test_conventions\.py`.*티켓\s*#724"
        self.assertRegex(state_text, pattern, "STATE.md checklist for test_conventions.py must be [x] with ticket #724")

    def test_convention_checker_itself_within_budget(self):
        """test_conventions.py must respect function line and file size limits."""
        self_path = Path(__file__).resolve()
        self.assertLessEqual(self_path.stat().st_size, 80_000, "Module exceeds 80KB cap")

        tree = ast.parse(self_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = node.end_lineno - node.lineno + 1
                self.assertLessEqual(lines, 80, f"Function {node.name} has {lines} lines (cap 80)")


if __name__ == "__main__":
    unittest.main()
