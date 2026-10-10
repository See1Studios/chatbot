"""workspace/ moves onto the data root, then workspace points at `.` (flat/D).

Run: engine/run-tests.sh test_flatten_workspace
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402

sys.path.insert(0, str(ENGINE / "tools"))
import flatten_workspace as flat  # noqa: E402


def _legacy(root: Path) -> Path:
    data = root / "pe"
    ws = data / "workspace"
    (ws / "characters" / "c").mkdir(parents=True)
    (ws / "characters" / "c" / "card.json").write_text("{}", encoding="utf-8")
    (ws / "memory").mkdir()
    (ws / "memory" / "MEMORY.md").write_text("fact\n", encoding="utf-8")
    (ws / "artifacts" / "persona").mkdir(parents=True)
    (ws / "artifacts" / "persona" / "pic.png").write_bytes(b"png")
    (ws / "AGENTS.md").symlink_to("/tmp/charter-target")
    (data / "artifacts").mkdir(parents=True)
    (data / "sessions").mkdir()
    (data / "sessions" / "s.json").write_text("{}", encoding="utf-8")
    (data / "secrets.env").write_text("x\n", encoding="utf-8")
    (data / "logs").mkdir()
    return data


class FlattenWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_dry_run_moves_nothing(self):
        data = _legacy(self.tmp)
        steps = flat.plan(data)
        self.assertIn(("symlink", data / "workspace"), steps)
        self.assertTrue((data / "workspace" / "characters").is_dir())
        self.assertFalse((data / "characters").exists())

    def test_apply_lifts_the_charter_and_keeps_sessions(self):
        data = _legacy(self.tmp)
        flat.apply(data)
        link = data / "workspace"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), ".")
        self.assertEqual((data / "characters" / "c" / "card.json").read_text(), "{}")
        self.assertEqual((data / "workspace" / "memory" / "MEMORY.md").read_text(), "fact\n")
        self.assertEqual((data / "artifacts" / "persona" / "pic.png").read_bytes(), b"png")
        self.assertTrue((data / "AGENTS.md").is_symlink())
        self.assertEqual((data / "sessions" / "s.json").read_text(), "{}")
        self.assertEqual((data / "secrets.env").read_text(), "x\n")
        self.assertEqual(flat.plan(data), [])

    def test_a_name_collision_moves_nothing(self):
        data = _legacy(self.tmp)
        (data / "memory").write_text("root\n", encoding="utf-8")
        with self.assertRaises(flat.FlattenError):
            flat.apply(data)
        self.assertEqual((data / "memory").read_text(), "root\n")
        self.assertTrue((data / "workspace" / "characters").is_dir())
        self.assertFalse((data / "workspace").is_symlink())

    def test_a_failed_move_puts_the_tree_back(self):
        data = _legacy(self.tmp)
        real = flat.rename
        calls = {"n": 0}

        def boom(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk")
            real(src, dst)

        flat.rename = boom
        try:
            with self.assertRaises(OSError):
                flat.apply(data)
        finally:
            flat.rename = real
        self.assertTrue((data / "workspace" / "characters").is_dir())
        self.assertFalse((data / "characters").exists())
        self.assertFalse((data / "workspace").is_symlink())
        self.assertTrue((data / "artifacts").is_dir())
        self.assertFalse(any((data / "artifacts").iterdir()))


if __name__ == "__main__":
    unittest.main()
