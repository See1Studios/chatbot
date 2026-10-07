"""evolution.py: the protected-path registry (core, standalone).
Run: python3 -m unittest tests.test_evolution  (from services/chatbot)
"""
import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
sys.path.insert(0, str(ENGINE))
import evolution  # noqa: E402
from tests._platform import home_env  # noqa: E402

STDLIB_OK = {  # and platform_compat, the core sibling that holds OS-specific calls (PP5)
             "__future__", "fnmatch", "hashlib", "platform_compat", "repo_layout", "json", "os", "pathlib", "re", "signal", "subprocess",
             "sys", "threading", "time", "typing"}


def make_root(protect, except_=(), home=None):
    root = Path(tempfile.mkdtemp()).resolve()
    (root / evolution.REGISTRY_NAME).write_text(
        json.dumps({"protect": protect, "except": list(except_)}), encoding="utf-8")
    return root


class MatchingTest(unittest.TestCase):
    def test_exact_file_and_top_level_glob(self):
        root = make_root(["chatbot-ctl.sh", "*.py"])
        self.assertTrue(evolution.is_protected(root, root / "chatbot-ctl.sh"))
        self.assertTrue(evolution.is_protected(root, root / "server.py"))
        self.assertTrue(evolution.is_protected(root, root / "brand_new.py"))
        self.assertFalse(evolution.is_protected(root, root / "sub" / "helper.py"))  # '*' stays in one segment
        self.assertFalse(evolution.is_protected(root, root / "server.pyc"))
        self.assertFalse(evolution.is_protected(root, root / "sub" / "chatbot-ctl.sh"))

    def test_trailing_slash_protects_a_subtree(self):
        root = make_root(["tests/"])
        for p in ("tests", "tests/a.txt", "tests/deep/er/b.py"):
            self.assertTrue(evolution.is_protected(root, root / p), p)
        self.assertFalse(evolution.is_protected(root, root / "tests2" / "a.txt"))
        self.assertFalse(evolution.is_protected(root, root / "other" / "tests" / "a.txt"))

    def test_returns_the_matching_pattern(self):
        root = make_root(["*.py", "tests/"])
        self.assertEqual(evolution.match_protected(root, root / "tests" / "x"), "tests/")
        self.assertIsNone(evolution.match_protected(root, root / "notes.md"))

    def test_a_data_pattern_also_holds_the_live_data_dir(self):
        # uds/F: user data lives outside the repo (~/.pe); data/workspace/AGENTS.md there is still the charter
        root = make_root(["data/workspace/AGENTS.md", "data/workspace/skill-observations/tickets/", "*.py"])
        live = Path(tempfile.mkdtemp()).resolve()
        with mock.patch.dict(os.environ, {"CHATBOT_DATA": str(live)}):
            self.assertTrue(evolution.is_protected(root, live / "workspace" / "AGENTS.md"))
            self.assertTrue(evolution.is_protected(root, live / "workspace" / "skill-observations" / "tickets" / "0001.json"))
            self.assertTrue(evolution.is_protected(root, root / "data" / "workspace" / "AGENTS.md"))
            self.assertFalse(evolution.is_protected(root, live / "workspace" / "PROJECT.md"))
            self.assertFalse(evolution.is_protected(root, live / "AGENTS.md"))

    def test_relative_path_means_relative_to_root(self):
        root = make_root(["*.py"])
        self.assertTrue(evolution.is_protected(root, "server.py"))
        self.assertFalse(evolution.is_protected(root, "notes.md"))

    def test_dotdot_and_symlink_routes_are_resolved(self):
        root = make_root(["server.py", "tests/"])
        (root / "data").mkdir()
        (root / "server.py").write_text("x", encoding="utf-8")
        (root / "tests").mkdir()
        self.assertTrue(evolution.is_protected(root, root / "data" / ".." / "server.py"))
        (root / "data" / "alias.py").symlink_to(root / "server.py")
        self.assertTrue(evolution.is_protected(root, root / "data" / "alias.py"))
        (root / "data" / "tdir").symlink_to(root / "tests")
        self.assertTrue(evolution.is_protected(root, root / "data" / "tdir" / "new.txt"))

    def test_a_symlink_inside_a_protected_dir_is_protected_even_if_it_points_away(self):
        root = make_root(["tests/"])
        (root / "tests").mkdir()
        away = Path(tempfile.mkdtemp()).resolve() / "elsewhere.txt"
        away.write_text("x", encoding="utf-8")
        (root / "tests" / "link").symlink_to(away)
        self.assertTrue(evolution.is_protected(root, root / "tests" / "link"))

    def test_home_pattern_follows_home_and_a_symlinked_directory(self):
        home = Path(tempfile.mkdtemp()).resolve()
        real = Path(tempfile.mkdtemp()).resolve()
        try:
            (home / ".agents").symlink_to(real, target_is_directory=True)
        except OSError:   # Windows allows symlinks only with Developer Mode or admin rights
            self.skipTest("this account may not create symlinks")
        root = make_root(["~/.agents/"])
        with mock.patch.dict(os.environ, home_env(home)):
            self.assertTrue(evolution.is_protected(root, home / ".agents" / "skills" / "x" / "SKILL.md"))
            self.assertTrue(evolution.is_protected(root, real / "skills" / "y.md"))
            self.assertFalse(evolution.is_protected(root, home / "other" / "a.md"))

    def test_absolute_pattern(self):
        target = Path(tempfile.mkdtemp()).resolve()
        root = make_root([str(target) + "/"])
        self.assertTrue(evolution.is_protected(root, target / "a"))

    def test_exception_lifts_protection_only_where_it_matches(self):
        root = make_root(["static/", "*.py"], except_=[{"path": "static/", "reason": "tier 0 here"}])
        self.assertFalse(evolution.is_protected(root, root / "static" / "app.js"))
        self.assertTrue(evolution.is_protected(root, root / "server.py"))

    def test_glob_chars_in_the_root_path_are_not_patterns(self):
        base = Path(tempfile.mkdtemp()).resolve() / "a[1]"
        base.mkdir()
        root = make_root(["*.py"])
        moved = base / evolution.REGISTRY_NAME
        moved.write_text((root / evolution.REGISTRY_NAME).read_text(encoding="utf-8"), encoding="utf-8")
        self.assertTrue(evolution.is_protected(base, base / "x.py"))


class FailClosedTest(unittest.TestCase):
    def assertClosed(self, root):
        why = evolution.match_protected(root, Path(root) / "anything.txt")
        self.assertTrue(why and why.startswith("registry unavailable"), why)
        self.assertTrue(evolution.is_protected(root, "/etc/hostname"))
        with self.assertRaises(evolution.RegistryError):
            evolution.load_registry(root)

    def write(self, text):
        root = Path(tempfile.mkdtemp()).resolve()
        (root / evolution.REGISTRY_NAME).write_text(text, encoding="utf-8")
        return root

    def test_missing_registry(self):
        self.assertClosed(Path(tempfile.mkdtemp()).resolve())

    def test_broken_registries(self):
        for text in ("{not json", "[]", "{}", '{"protect": []}', '{"protect": "x"}',
                     '{"protect": [1]}', '{"protect": [""]}', '{"protect": [{"reason": "x"}]}',
                     '{"protect": ["a"], "except": "static/"}'):
            self.assertClosed(self.write(text))


class ShippedRegistryTest(unittest.TestCase):
    """The registry that ships with the code protects what docs/plans/recursive-self-evolution.md §3 0-4 lists."""

    def prot(self, rel):
        return evolution.is_protected(CODE, CODE / rel)

    def test_registry_loads(self):
        protect, exceptions = evolution.load_registry(CODE)
        self.assertTrue(protect)
        self.assertEqual(exceptions, ["static/"])

    def test_every_host_module_is_protected(self):
        modules = sorted(p.name for p in ENGINE.glob("*.py"))
        self.assertIn("server.py", modules)
        self.assertIn("evolution.py", modules)
        for name in modules:
            self.assertTrue(self.prot(name), name)
        self.assertTrue(self.prot("a_module_that_does_not_exist_yet.py"))

    def test_guard_ticket_and_rules_are_protected(self):
        for rel in ("chatbot-ctl.sh", "protected_paths.json", "data/lifecycle.lock",
                    "data/maintenance.flag", "tests/test_evolution.py", "tests/new/x.py",
                    "data/workspace/SELF-MODIFY.md", "data/workspace/AGENTS.md", "docs/SELF-MODIFY.md",
                    "docs/EMERGENCY.md", "data/host-force.ticket", "__pycache__/server.cpython-38.pyc"):
            self.assertTrue(self.prot(rel), rel)

    def test_global_shared_skills_directory_is_protected(self):
        self.assertTrue(evolution.is_protected(CODE, Path("~/.agents/skills/x/SKILL.md").expanduser()))

    def test_static_ui_is_the_explicit_exception(self):
        self.assertFalse(self.prot("static/app.js"))
        self.assertFalse(self.prot("static/vendor/mermaid.min.js"))

    def test_instance_layer_stays_writable(self):
        for rel in ("data/workspace/PERSONA.md", "data/workspace/PROJECT.md", "data/workspace/memory/MEMORY.md",
                    "data/workspace/.agents/skills/nas-sphere/SKILL.md",
                    "data/workspace/skill-observations/observation-log/0001-x.md",
                    "docs/plans/recursive-self-evolution.md", "docs/DEVLOG.md", "data/sessions/x.json"):
            self.assertFalse(self.prot(rel), rel)


class ImportDisciplineTest(unittest.TestCase):
    """The core module stays standalone: stdlib only, no host imports, no mention of the tool server."""

    def test_only_stdlib_imports(self):
        tree = ast.parse((ENGINE / "evolution.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, STDLIB_OK)

    def test_no_tool_server_name_in_core_files(self):
        for name in ("evolution.py", evolution.REGISTRY_NAME):
            for server_name in ("nas_mcp", "mcp_server"):
                self.assertNotIn(server_name, (CODE / name).read_text(encoding="utf-8"), name)

    def test_no_python39_syntax(self):
        src = (ENGINE / "evolution.py").read_text(encoding="utf-8")
        compile(src, "evolution.py", "exec")  # the suite runs on 3.8
        self.assertNotIn("removeprefix", src)


class DelegationTierTest(unittest.TestCase):
    """DELEGATION_TIERS_v1: governance (Tier 3) > protected (Tier 2) > the rest (Tier 0)."""

    def root(self, governance):
        root = make_root(["*.py", "tests/"])
        raw = json.loads((root / evolution.REGISTRY_NAME).read_text(encoding="utf-8"))
        raw["governance"] = governance
        (root / evolution.REGISTRY_NAME).write_text(json.dumps(raw), encoding="utf-8")
        return root

    def test_tiers(self):
        root = self.root(["tickets.py", {"path": "tests/smoke.py", "reason": "a gate"}, "rules/"])
        self.assertEqual(evolution.delegation_tier(root, "tickets.py"), (3, "tickets.py"))
        self.assertEqual(evolution.delegation_tier(root, "tests/smoke.py"), (3, "tests/smoke.py"))
        self.assertEqual(evolution.delegation_tier(root, "rules/deep/x.md"), (3, "rules/"))
        self.assertEqual(evolution.delegation_tier(root, "session.py"), (2, "*.py"))
        self.assertEqual(evolution.delegation_tier(root, "tests/test_x.py"), (2, "tests/"))
        self.assertEqual(evolution.delegation_tier(root, "data/workspace/x.md"), (0, ""))

    def test_no_governance_list_means_none(self):
        root = make_root(["*.py"])
        self.assertIsNone(evolution.match_governance(root, "tickets.py"))
        self.assertEqual(evolution.delegation_tier(root, "tickets.py")[0], 2)

    def test_a_broken_registry_counts_as_governance(self):
        root = Path(tempfile.mkdtemp()).resolve()
        for text in ("{not json", '{"protect": ["a"], "governance": "x"}', '{"protect": ["a"], "governance": [1]}'):
            (root / evolution.REGISTRY_NAME).write_text(text, encoding="utf-8")
            self.assertEqual(evolution.delegation_tier(root, "anything.txt")[0], 3, text)

    def test_the_shipped_registry_guards_the_guards(self):
        root = REPO
        for rel in ("tickets.py", "evolution.py", evolution.REGISTRY_NAME, "tests/smoke.py", "data/workspace/AGENTS.md"):
            self.assertEqual(evolution.delegation_tier(root, rel)[0], 3, rel)
        self.assertEqual(evolution.delegation_tier(root, "session.py")[0], 2)


if __name__ == "__main__":
    unittest.main()
