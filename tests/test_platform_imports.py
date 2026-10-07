"""Engine modules import on every OS (platform-portability pp/D, #395): no module-level import of a POSIX-only module
outside a try. One top-level `import pty` in providers/account_login.py kept server.py from importing on Windows
(FIREBAT 2026-09-29: 16 of 50 failures). Import such a module inside the function that needs it, or in a try.
Run: engine/run-tests.sh test_platform_imports
"""
import ast
import importlib.util
import re
import unittest
from pathlib import Path
from tests._paths import ENGINE, REPO, rel  # noqa: E402

ROOT = REPO
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
        found += ["%s:%d %s" % (rel(path), node.lineno, n) for n in names if n in POSIX_ONLY]
    return found


class PlatformImports(unittest.TestCase):
    def test_no_unguarded_posix_only_import_at_module_level(self):
        files = list(ENGINE.glob("*.py")) + list(ENGINE.glob("providers/*.py")) + list(ENGINE.glob("tools/*.py"))
        bad = [x for p in sorted(files) if p.name not in LINUX_BY_DESIGN for x in top_level_posix_imports(p)]
        self.assertEqual(bad, [], "import these inside the function that needs them, or in a try (pp/D)")


# import name -> distribution name in requirements.txt (pp/J, #396: PIL was used and never declared; FIREBAT's fresh
# virtualenv could not import it, the NAS had it installed by hand)
DISTRIBUTION = {"PIL": "Pillow", "yaml": "PyYAML"}
WINDOWS_STDLIB = {"msvcrt", "winreg", "_winapi", "winsound"}   # standard library there, absent here


def engine_files():
    return sorted(list(ENGINE.glob("*.py")) + list(ENGINE.glob("providers/*.py")) + list(ENGINE.glob("tools/*.py")))


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
                if n in local or n in POSIX_ONLY or n in WINDOWS_STDLIB:
                    continue
                try:
                    spec = importlib.util.find_spec(n)
                except (ImportError, ValueError):
                    spec = None
                origin = (spec.origin or "") if spec else ""
                if spec is None or "site-packages" in origin or "dist-packages" in origin:
                    out.setdefault(n, set()).add(rel(p))
    return out


def text_io_without_encoding(path):
    """open()/read_text()/write_text() in text mode with no encoding=: on a Korean Windows that is cp949, not UTF-8."""
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
        kws = {k.arg for k in n.keywords}
        if "encoding" in kws:
            continue
        if name in ("read_text", "write_text"):
            out.append(n.lineno)
        elif name == "open" and isinstance(f, ast.Name):
            mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else ""
            mode = next((k.value.value for k in n.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)), mode)
            if "b" not in str(mode):
                out.append(n.lineno)
    return ["%s:%d" % (rel(path), ln) for ln in out]


def str_of_relative_to(path):
    """str(x.relative_to(...)): a \\-path on Windows where the page or an agent expects / -- use .as_posix() (#403)."""
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "str" and n.args
                and isinstance(n.args[0], ast.Call) and isinstance(n.args[0].func, ast.Attribute)
                and n.args[0].func.attr == "relative_to"):
            out.append("%s:%d" % (rel(path), n.lineno))
    return out


class PathSeparators(unittest.TestCase):
    def test_relative_paths_are_spelled_with_slashes(self):
        bad = [x for p in engine_files() for x in str_of_relative_to(p)]
        self.assertEqual(bad, [], "use .relative_to(...).as_posix()")


LF_EXEMPT = {"platform_compat.py", "worktree_runner.py", "run_modules.py"}   # the helper itself; dev-only tools


def crlf_writes(path):
    """Text written so that Windows turns \n into \r\n: Path.write_text (3.8 has no newline=) or open() for
    writing/appending text without newline=. Use platform_compat.write_text / newline="\n" (#405)."""
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr == "write_text" and not (
                isinstance(f.value, ast.Name) and f.value.id == "platform_compat"):
            out.append(n.lineno)
        elif isinstance(f, ast.Name) and f.id == "open":
            mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else ""
            mode = next((k.value.value for k in n.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)), mode)
            if any(c in str(mode) for c in "wa") and "b" not in str(mode) and "newline" not in {k.arg for k in n.keywords}:
                out.append(n.lineno)
    return ["%s:%d" % (rel(path), ln) for ln in out]


class LineEndings(unittest.TestCase):
    def test_engine_writes_text_with_lf(self):
        bad = [x for p in engine_files() if p.name not in LF_EXEMPT for x in crlf_writes(p)]
        self.assertEqual(bad, [], 'use platform_compat.write_text(...) or open(..., newline="\\n")')


class TextEncoding(unittest.TestCase):
    def test_engine_text_io_names_its_encoding(self):
        # FIREBAT 2026-09-29 (#401): without UTF-8 mode a Korean Windows reads and writes text as cp949
        bad = [x for p in engine_files() for x in text_io_without_encoding(p)]
        self.assertEqual(bad, [], 'pass encoding="utf-8"')


class DeclaredDependencies(unittest.TestCase):
    def test_every_third_party_import_is_in_requirements(self):
        declared = {re.split(r"[<>=!~\[; ]", ln.strip(), 1)[0].lower()
                    for ln in (ENGINE / "requirements.txt").read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.startswith("#")}
        missing = {n: sorted(files) for n, files in third_party_imports().items()
                   if DISTRIBUTION.get(n, n).lower() not in declared}
        self.assertEqual(missing, {}, "declare these in requirements.txt (map the import name in DISTRIBUTION)")


if __name__ == "__main__":
    unittest.main()
