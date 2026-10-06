"""tests/smoke.py is a gate of every delegated run (worktree_runner DEFAULT_GATES) but not a test_*.py module, so the
suite never ran it: 398eace (2026-10-06) moved names it imported and every delegation's smoke gate failed (#715).
Smoke itself cannot run from the commit hook (its guard check fails on any staged change), so this guard (run-tests.sh
FAST) checks what broke: every name smoke.py and the runner's other gates import exists where they import it from.
Run: python3 -m unittest tests.test_smoke  (from services/chatbot)
"""
import ast
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
GATES = ("tests/smoke.py", "tests/test_identity_wiring.py")   # worktree_runner.DEFAULT_GATES besides the FAST guards


class GateImports(unittest.TestCase):
    def test_every_name_a_gate_imports_is_there(self):
        missing = []
        for gate in GATES:
            for node in ast.walk(ast.parse((ROOT / gate).read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    try:
                        mod = importlib.import_module(node.module)
                    except ImportError:
                        continue   # a third-party or optional module: the gate's own business
                    missing += ["%s: from %s import %s" % (gate, node.module, a.name)
                                for a in node.names if a.name != "*" and not hasattr(mod, a.name)]
        self.assertEqual(missing, [], "a gate imports a name its module no longer has (moved or removed)")

    def test_the_gates_are_the_runners(self):
        src = (ROOT / "tools" / "worktree_runner.py").read_text(encoding="utf-8")
        for gate in GATES:
            self.assertIn("python3 %s" % gate, src)


if __name__ == "__main__":
    unittest.main()
