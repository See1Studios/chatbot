"""/api/file/preview + /api/file/raw share _resolve_safe_preview_file. It is an
allow-list: project trees only, never dotfiles/dotdirs, never key/history/secret names.
Run: python3 -m unittest tests.test_file_preview_guard  (from services/chatbot)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


class PreviewGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name).resolve()
        for d in ("services/app", "projects", "wiki", ".agents/skills", ".ssh", "other", "services/app/.git"):
            (home / d).mkdir(parents=True, exist_ok=True)
        self.files = {
            "ok_service": home / "services/app/main.py",
            "ok_home_doc": home / "AGENTS.md",
            "ok_agents": home / ".agents/skills/x.md",
            "ssh_key": home / ".ssh/id_ed25519",
            "history": home / ".bash_history",
            "outside": home / "other/notes.txt",
            "dot_in_tree": home / "services/app/.git/config",
            "env": home / "services/app/.env",
            "secret_name": home / "services/app/secrets.env",
            "pem": home / "services/app/server.pem",
            "hidden_home_doc": home / ".notes.md",
        }
        for f in self.files.values():
            f.write_text("x")
        # a symlink inside an allowed tree pointing at a private key must not bypass the guard
        self.link = home / "services/app/innocent.txt"
        os.symlink(self.files["ssh_key"], self.link)
        self.orig = (server.HOME, server._HOME_R, server._PREVIEW_ALLOWED_ROOTS, server.WEB_ROOT)
        server.HOME = home
        server._HOME_R = home
        server._PREVIEW_ALLOWED_ROOTS = [home / "services", home / "projects", home / "wiki", home / ".agents"]

    def tearDown(self):
        server.HOME, server._HOME_R, server._PREVIEW_ALLOWED_ROOTS, server.WEB_ROOT = self.orig
        self.tmp.cleanup()

    def allowed(self, key_or_path):
        p = self.files.get(key_or_path, key_or_path)
        rp, _ = server._resolve_safe_preview_file(str(p))
        return rp is not None

    def test_allowed(self):
        for k in ("ok_service", "ok_home_doc", "ok_agents"):
            self.assertTrue(self.allowed(k), k)

    def test_denied(self):
        for k in ("ssh_key", "history", "outside", "dot_in_tree", "env", "secret_name", "pem", "hidden_home_doc"):
            self.assertFalse(self.allowed(k), k)

    def test_symlink_to_private_key_denied(self):
        self.assertFalse(self.allowed(self.link))

    def test_tilde_and_traversal(self):
        self.assertFalse(self.allowed("~/.ssh/id_ed25519"))
        self.assertFalse(self.allowed(str(self.files["ok_service"].parent / ".." / ".." / ".ssh" / "id_ed25519")))


if __name__ == "__main__":
    unittest.main()
