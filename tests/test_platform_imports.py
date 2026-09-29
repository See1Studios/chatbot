"""Engine modules import on every OS (platform-portability pp/D, #395): no module-level import of a POSIX-only module
outside a try. One top-level `import pty` in providers/account_login.py kept server.py from importing on Windows
(FIREBAT 2026-09-29: 16 of 50 failures). Import such a module inside the function that needs it, or in a try.
Run: python3 -m unittest tests.test_platform_imports  (from services/chatbot)
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSIX_ONLY = {"pty", "termios", "tty", "fcntl", "pwd", "grp", "resource", "posix"}
LINUX_BY_DESIGN = {"nas_mcp_host.py", "ctl_proc.py", "platform_compat.py"}   # the NAS plugin, the NAS ctl helper


def top_level_posix_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:                      # module level only; a try/except around it is a guard
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        found += ["%s:%d %s" % (path.relative_to(ROOT).as_posix(), node.lineno, n) for n in names if n in POSIX_ONLY]
    return found


class PlatformImports(unittest.TestCase):
    def test_no_unguarded_posix_only_import_at_module_level(self):
        files = list(ROOT.glob("*.py")) + list(ROOT.glob("providers/*.py")) + list(ROOT.glob("tools/*.py"))
        bad = [x for p in sorted(files) if p.name not in LINUX_BY_DESIGN for x in top_level_posix_imports(p)]
        self.assertEqual(bad, [], "import these inside the function that needs them, or in a try (pp/D)")


if __name__ == "__main__":
    unittest.main()
