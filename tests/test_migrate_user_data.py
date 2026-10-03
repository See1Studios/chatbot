"""Dry-run and safe copy for tools/migrate_user_data.py (user-data-separation).

Run: python3 -m unittest tests.test_migrate_user_data
"""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import migrate_user_data as mig  # noqa: E402


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class MigrateUserData(unittest.TestCase):
    def test_dry_run_is_the_default_and_writes_nothing(self):
        tmp = Path(tempfile.mkdtemp())
        source = tmp / "src"
        dest = tmp / "dst"
        _write(source, "memory/MEMORY.md", "remember")
        _write(source, "secrets.env", "TOKEN=example")
        os.chmod(source / "secrets.env", 0o600)
        code = mig.migrate(source, dest, apply=False, force=False, remove_source=False, keep_tracked=False)
        self.assertEqual(code, 0)
        self.assertFalse(dest.exists())
        self.assertEqual((source / "memory/MEMORY.md").read_text(encoding="utf-8"), "remember")
        self.assertTrue((source / "secrets.env").is_file())

    def test_apply_copies_and_keeps_the_source(self):
        tmp = Path(tempfile.mkdtemp())
        source = tmp / "src"
        dest = tmp / "dst"
        _write(source, "nested/note.txt", "alpha")
        code = mig.migrate(source, dest, apply=True, force=False, remove_source=False, keep_tracked=False)
        self.assertEqual(code, 0)
        self.assertEqual((dest / "nested/note.txt").read_text(encoding="utf-8"), "alpha")
        self.assertEqual((source / "nested/note.txt").read_text(encoding="utf-8"), "alpha")
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o700)

    def test_nonempty_dest_is_refused_without_force(self):
        tmp = Path(tempfile.mkdtemp())
        source = tmp / "src"
        dest = tmp / "dst"
        _write(source, "a.txt", "one")
        _write(dest, "b.txt", "two")
        before = (dest / "b.txt").read_text(encoding="utf-8")
        code = mig.migrate(source, dest, apply=True, force=False, remove_source=False, keep_tracked=False)
        self.assertEqual(code, 2)
        self.assertFalse((dest / "a.txt").exists())
        self.assertEqual((dest / "b.txt").read_text(encoding="utf-8"), before)
        self.assertTrue((source / "a.txt").is_file())

    def test_force_does_not_overwrite_a_different_file(self):
        tmp = Path(tempfile.mkdtemp())
        source = tmp / "src"
        dest = tmp / "dst"
        _write(source, "a.txt", "new")
        _write(dest, "a.txt", "old")
        code = mig.migrate(source, dest, apply=True, force=True, remove_source=False, keep_tracked=False)
        self.assertEqual(code, 3)
        self.assertEqual((dest / "a.txt").read_text(encoding="utf-8"), "old")
        self.assertEqual((source / "a.txt").read_text(encoding="utf-8"), "new")

    def test_remove_source_deletes_only_matching_copies(self):
        tmp = Path(tempfile.mkdtemp())
        source = tmp / "src"
        dest = tmp / "dst"
        secret = _write(source, "secrets.env", "TOKEN=example")
        os.chmod(secret, 0o600)
        _write(source, "keep/note.txt", "beta")
        code = mig.migrate(source, dest, apply=True, force=False, remove_source=True, keep_tracked=False)
        self.assertEqual(code, 0)
        self.assertFalse((source / "secrets.env").exists())
        self.assertFalse((source / "keep/note.txt").exists())
        self.assertEqual((dest / "secrets.env").read_text(encoding="utf-8"), "TOKEN=example")
        self.assertEqual(stat.S_IMODE((dest / "secrets.env").stat().st_mode) & 0o777, 0o600)
        self.assertEqual((dest / "keep/note.txt").read_text(encoding="utf-8"), "beta")

    def test_remove_source_refuses_when_a_copy_differs_and_deletes_nothing(self):
        tmp = Path(tempfile.mkdtemp())
        source = tmp / "src"
        dest = tmp / "dst"
        _write(source, "secrets.env", "TOKEN=real")
        _write(source, "other.txt", "ok")
        code = mig.migrate(source, dest, apply=True, force=False, remove_source=False, keep_tracked=False)
        self.assertEqual(code, 0)
        (dest / "secrets.env").write_text("TOKEN=tampered", encoding="utf-8")
        code = mig.migrate(source, dest, apply=True, force=True, remove_source=True, keep_tracked=False)
        self.assertEqual(code, 3)
        self.assertEqual((source / "secrets.env").read_text(encoding="utf-8"), "TOKEN=real")
        self.assertTrue((source / "other.txt").is_file())
        self.assertEqual((dest / "other.txt").read_text(encoding="utf-8"), "ok")

    def test_keep_tracked_leaves_indexed_files_on_disk(self):
        tmp = Path(tempfile.mkdtemp())
        git = "/usr/local/bin/git" if Path("/usr/local/bin/git").is_file() else "git"
        env = dict(os.environ)
        env["PATH"] = "/usr/local/bin:" + env.get("PATH", "")
        env.update({
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        })
        subprocess.run([git, "init", "-q"], cwd=str(tmp), env=env, check=True)
        data = tmp / "data"
        _write(data, "keep.txt", "tracked")
        _write(data, "secrets.env", "TOKEN=example")
        subprocess.run([git, "add", "data/keep.txt"], cwd=str(tmp), env=env, check=True)
        subprocess.run([git, "commit", "-q", "-m", "keep"], cwd=str(tmp), env=env, check=True)
        dest = tmp / "out"
        code = mig.migrate(data, dest, apply=True, force=False, remove_source=True, keep_tracked=True)
        self.assertEqual(code, 0)
        self.assertEqual((data / "keep.txt").read_text(encoding="utf-8"), "tracked")
        self.assertFalse((data / "secrets.env").exists())
        self.assertEqual((dest / "secrets.env").read_text(encoding="utf-8"), "TOKEN=example")
        self.assertEqual((dest / "keep.txt").read_text(encoding="utf-8"), "tracked")

    def test_cli_dry_run_does_not_create_the_default_home(self):
        tmp = Path(tempfile.mkdtemp())
        source = tmp / "src"
        _write(source, "a.txt", "x")
        home = tmp / "home"
        home.mkdir()
        env = dict(os.environ)
        env["HOME"] = str(home)
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "migrate_user_data.py"), "--source", str(source)],
            cwd=str(tmp), env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mode: dry-run", r.stdout)
        self.assertFalse((home / ".pe").exists())

    def test_user_data_including_ticket_history_is_ignored(self):
        def ignored(rel):
            git = "/usr/local/bin/git" if Path("/usr/local/bin/git").is_file() else "git"
            r = subprocess.run(
                [git, "check-ignore", "-q", "--no-index", rel],
                cwd=str(ROOT), capture_output=True, timeout=30,
            )
            return r.returncode == 0
        self.assertTrue(ignored("data/secrets.env"))
        self.assertTrue(ignored("data/chat.db"))
        self.assertTrue(ignored("data/workspace/memory/MEMORY.md"))
        self.assertTrue(ignored("data/workspace/characters/char_x/state.json"))
        self.assertTrue(ignored("data/workspace/skill-observations/tickets/0001.json"))
        self.assertTrue(ignored("data/persona/avatar.webp"))
        self.assertTrue(ignored("data/workspace/skill-observations/candidates.jsonl"))


if __name__ == "__main__":
    unittest.main()
