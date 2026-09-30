"""data_bootstrap.py (user-data-separation uds/D): an empty data folder gets the workspace template once; an existing
workspace is never touched, and files the user deleted do not come back.
Run: python3 -m unittest tests.test_data_bootstrap  (from services/chatbot)
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import data_bootstrap as B  # noqa: E402


class Bootstrap(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "pe"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_new_folder_gets_the_whole_template_privately(self):
        res = B.bootstrap(self.data)
        self.assertTrue(res["created"])
        want = sorted(p.relative_to(B.TEMPLATE).as_posix() for p in B._files(B.TEMPLATE))
        self.assertEqual(sorted(res["files"]), want)
        for rel in want:
            self.assertEqual((self.data / "workspace" / rel).read_bytes(), (B.TEMPLATE / rel).read_bytes(), rel)
        if os.name == "posix":   # mode bits are POSIX; Windows guards the folder with the profile's ACL (#411)
            self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)
        for d in B.SKELETON:
            self.assertTrue((self.data / d).is_dir(), d)
        marker = json.loads((self.data / B.MARKER).read_text(encoding="utf-8"))
        self.assertEqual(set(marker["files"]), set(want))
        self.assertEqual(marker["files"]["AGENTS.md"], B._sha(B.TEMPLATE / "AGENTS.md"))
        self.assertEqual([p.name for p in self.data.iterdir() if p.name.startswith(".")], [])   # no stage left

    def test_an_empty_workspace_dir_counts_as_new(self):
        (self.data / "workspace").mkdir(parents=True)   # what `mkdir -p` in ctl would leave
        os.chmod(self.data, 0o755)                        # made by someone else with the default umask
        self.assertTrue(B.bootstrap(self.data)["created"])
        self.assertTrue((self.data / "workspace" / "AGENTS.md").is_file())
        if os.name == "posix":   # mode bits are POSIX; Windows guards the folder with the profile's ACL (#411)
            self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)

    def test_an_existing_workspace_is_left_alone_and_deleted_files_stay_deleted(self):
        B.bootstrap(self.data)
        ws = self.data / "workspace"
        (ws / "AGENTS.md").write_text("mine", encoding="utf-8")
        (ws / "roles" / "art" / "ROLE.md").unlink()
        before = (self.data / B.MARKER).read_bytes()
        self.assertEqual(B.bootstrap(self.data), {"created": False, "files": []})
        self.assertEqual((ws / "AGENTS.md").read_text(encoding="utf-8"), "mine")
        self.assertFalse((ws / "roles" / "art" / "ROLE.md").exists())
        self.assertEqual((self.data / B.MARKER).read_bytes(), before)

    def test_this_repo_s_own_data_folder_is_a_no_op(self):
        self.assertFalse(B.bootstrap(ROOT / "data", dry_run=True).get("files"))

    def test_dry_run_writes_nothing(self):
        res = B.bootstrap(self.data, dry_run=True)
        self.assertTrue(res["files"])
        self.assertFalse(self.data.exists())

    def test_a_failed_copy_leaves_no_half_workspace(self):
        real = B.shutil.copy2
        calls = []

        def boom(src, dst):
            calls.append(src)
            if len(calls) == 3:
                raise OSError("disk full")
            return real(src, dst)
        B.shutil.copy2 = boom
        try:
            with self.assertRaises(OSError):
                B.bootstrap(self.data)
        finally:
            B.shutil.copy2 = real
        self.assertFalse((self.data / "workspace").exists())
        self.assertFalse((self.data / B.MARKER).exists())
        self.assertEqual(list(self.data.iterdir()), [])
        self.assertTrue(B.bootstrap(self.data)["created"])   # and the next start completes it

    def test_the_cli_uses_the_given_folder(self):
        env = {k: v for k, v in os.environ.items() if k not in ("CHATBOT_DATA", "PE_HOME", "PRIVATEENGINE_HOME", "AGY_CHAT_DATA")}
        r = subprocess.run([sys.executable, str(ROOT / "data_bootstrap.py"), "--data", str(self.data), "--quiet"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("new workspace", r.stdout)
        r = subprocess.run([sys.executable, str(ROOT / "data_bootstrap.py"), "--data", str(self.data), "--quiet"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
