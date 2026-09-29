"""Engine modules import on every OS (platform-portability pp/D, #395): no module-level import of a POSIX-only module
outside a try. One top-level `import pty` in providers/account_login.py kept server.py from importing on Windows
(FIREBAT 2026-09-29: 16 of 50 failures). Import such a module inside the function that needs it, or in a try.
Run: python3 -m unittest tests.test_platform_imports  (from services/chatbot)
"""
import ast
import importlib.util
import re
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


# import name -> distribution name in requirements.txt (pp/J, #396: PIL was used and never declared; FIREBAT's fresh
# virtualenv could not import it, the NAS had it installed by hand)
DISTRIBUTION = {"PIL": "Pillow", "yaml": "PyYAML"}


def engine_files():
    return sorted(list(ROOT.glob("*.py")) + list(ROOT.glob("providers/*.py")) + list(ROOT.glob("tools/*.py")))


def third_party_imports():
    local = {p.stem for p in engine_files()} | {"providers", "tools", "tests"}
    out = {}
    for p in engine_files():
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            for n in names:
                if n in local or n in POSIX_ONLY:
                    continue
                try:
                    spec = importlib.util.find_spec(n)
                except (ImportError, ValueError):
                    spec = None
                origin = (spec.origin or "") if spec else ""
                if spec is None or "site-packages" in origin or "dist-packages" in origin:
                    out.setdefault(n, set()).add(p.relative_to(ROOT).as_posix())
    return out


class DeclaredDependencies(unittest.TestCase):
    def test_every_third_party_import_is_in_requirements(self):
        declared = {re.split(r"[<>=!~\[; ]", ln.strip(), 1)[0].lower()
                    for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.startswith("#")}
        missing = {n: sorted(files) for n, files in third_party_imports().items()
                   if DISTRIBUTION.get(n, n).lower() not in declared}
        self.assertEqual(missing, {}, "declare these in requirements.txt (map the import name in DISTRIBUTION)")


if __name__ == "__main__":
    unittest.main()
