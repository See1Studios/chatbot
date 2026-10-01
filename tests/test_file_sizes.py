"""Python modules stay small enough for an agent to read whole, and functions small enough to change in one go
(AGENT_FIRST_v1, monolith-split Phase 5; measured in bytes since split/0 -- what an agent pays to read is tokens, and
bytes track tokens where line counts do not). A module over the cap is split by what it does; a function over the cap
is split by its steps. The few already over a cap may not grow past the ceiling pinned here -- lower a ceiling when
you shrink one, never raise it.
Run: python3 -m unittest tests.test_file_sizes  (from services/chatbot)
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 80_000
CEILINGS = {                       # over the cap already: no growth
    "tools/worktree_runner.py": 82_775,
}
BYTES_SLACK = 2_000                # a ceiling more than this above the file must come down

FUNC_MAX_LINES = 80
FUNC_CEILINGS = {                  # "path::Class.func": lines -- over the cap already: no growth
    "artifact_manager.py::_safe_artifact_rel": 91,
    "instructions.py::match_lorebook_entries": 108,
    "logdigest.py::digest": 243,
    "mcp_core.py::call": 100,
    "mcp_server.py::call_tool": 149,
    "mcp_server.py::tool_defs": 95,
    "nas_mcp_host.py::call_tool": 88,
    "providers/adapter_agy.py::AgyAdapter.normalize_line": 130,
    "providers/adapter_base.py::AgentAdapter.finalize_turn": 104,
    "providers/adapter_claude.py::ClaudeAdapter.normalize_line": 123,
    "providers/adapter_codex.py::CodexAdapter.normalize_line": 105,
    "providers/adapter_openai.py::OpenAIDialectAdapter._stream_once": 109,
    "providers/adapter_openai.py::OpenAIDialectAdapter.rate_limit_report": 115,
    "providers/adapter_openai.py::OpenAIDialectAdapter.stream_turn": 105,
    "session_turn.py::SessionTurn._start_turn": 185,
    "session_view.py::SessionView._tool_summary": 180,
    "session_view.py::SessionView.get_artifacts": 101,
    "tool_format.py::_format_tool_call": 121,
    "tools/st_import.py::convert_st_card": 94,
    "tools/worktree_runner.py::cmd_run": 319,
}
FUNC_SLACK = 10                    # a function ceiling more than this above the function must come down


def modules():
    return sorted(list(ROOT.glob("*.py")) + list((ROOT / "tools").glob("*.py")) + list((ROOT / "providers").glob("*.py")))


def rel(p):
    return p.relative_to(ROOT).as_posix()


def functions():
    """{"path::Qual.name": lines} for every function and method (nested ones by their full path; same name -> longest)."""
    out = {}

    def walk(node, prefix, path):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + n.name
                if not isinstance(n, ast.ClassDef):
                    key = "%s::%s" % (path, q)
                    out[key] = max(out.get(key, 0), n.end_lineno - n.lineno + 1)
                walk(n, q + ".", path)
            else:
                walk(n, prefix, path)

    for p in modules():
        walk(ast.parse(p.read_text(encoding="utf-8")), "", rel(p))
    return out


class FileSizes(unittest.TestCase):
    def test_every_module_stays_under_its_cap(self):
        for p in modules():
            n, limit = p.stat().st_size, CEILINGS.get(rel(p), MAX_BYTES)
            self.assertLessEqual(n, limit, "%s is %d bytes (cap %d): split it by what it does" % (rel(p), n, limit))

    def test_ceilings_are_only_for_modules_really_over_the_cap(self):
        for name, ceiling in CEILINGS.items():
            n = (ROOT / name).stat().st_size
            self.assertGreater(n, MAX_BYTES, "%s is under the cap now: drop its ceiling" % name)
            self.assertLessEqual(ceiling - n, BYTES_SLACK, "%s shrank to %d bytes: lower its ceiling" % (name, n))

    def test_every_function_stays_under_its_cap(self):
        for key, n in functions().items():
            limit = FUNC_CEILINGS.get(key, FUNC_MAX_LINES)
            self.assertLessEqual(n, limit, "%s has %d lines (cap %d): split it by its steps" % (key, n, limit))

    def test_function_ceilings_are_only_for_functions_really_over_the_cap(self):
        found = functions()
        for key, ceiling in FUNC_CEILINGS.items():
            self.assertIn(key, found, "%s is gone (split or renamed): drop its ceiling" % key)
            self.assertGreater(found[key], FUNC_MAX_LINES, "%s is under the cap now: drop its ceiling" % key)
            self.assertLessEqual(ceiling - found[key], FUNC_SLACK, "%s shrank to %d lines: lower its ceiling" % (key, found[key]))


if __name__ == "__main__":
    unittest.main()
