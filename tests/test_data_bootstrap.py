"""data_bootstrap.py (user-data-separation uds/D): an empty data folder gets the workspace template once; an existing
workspace is never touched, and files the user deleted do not come back.
Run: engine/run-tests.sh test_data_bootstrap
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import data_bootstrap as B  # noqa: E402
import host_config  # noqa: E402
import mcp_core  # noqa: E402


class CharterRoot(unittest.TestCase):
    def test_the_memory_adapter_uses_the_same_root(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(tmp), True)
        flat, legacy, link = tmp / "flat", tmp / "legacy", tmp / "link"
        flat.mkdir(); (flat / "AGENTS.md").write_text("x", encoding="utf-8"); (flat / "workspace").mkdir()
        (legacy / "workspace" / "roles").mkdir(parents=True)
        link.mkdir(); (link / "workspace").symlink_to(".", target_is_directory=True)
        for data in (tmp / "absent", flat, legacy, link):
            self.assertEqual(mcp_core._charter_root(data), host_config.charter_root(data), str(data))


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
            self.assertEqual((self.data / rel).read_bytes(), (B.TEMPLATE / rel).read_bytes(), rel)
        self.assertFalse((self.data / "workspace").exists())
        if os.name == "posix":   # mode bits are POSIX; Windows guards the folder with the profile's ACL (#411)
            self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)
        for d in B.SKELETON:
            self.assertTrue((self.data / d).is_dir(), d)
        marker = json.loads((self.data / B.MARKER).read_text(encoding="utf-8"))
        self.assertEqual(set(marker["files"]), set(want))
        self.assertEqual(marker["files"]["AGENTS.md"], B._sha(B.TEMPLATE / "AGENTS.md"))
        self.assertFalse(any(p.name.startswith(".workspace.bootstrap-") for p in self.data.iterdir()))

    def test_an_empty_workspace_dir_counts_as_new(self):
        (self.data / "workspace").mkdir(parents=True)   # what `mkdir -p` in ctl would leave
        os.chmod(self.data, 0o755)                        # made by someone else with the default umask
        self.assertTrue(B.bootstrap(self.data)["created"])
        self.assertTrue((self.data / "AGENTS.md").is_file())
        self.assertFalse((self.data / "workspace").exists())
        if os.name == "posix":   # mode bits are POSIX; Windows guards the folder with the profile's ACL (#411)
            self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)

    def test_an_existing_workspace_is_left_alone_and_deleted_files_stay_deleted(self):
        B.bootstrap(self.data)
        (self.data / "AGENTS.md").write_text("mine", encoding="utf-8")
        (self.data / "roles" / "art" / "ROLE.md").unlink()
        before = (self.data / B.MARKER).read_bytes()
        self.assertEqual(B.bootstrap(self.data), {"created": False, "files": []})
        self.assertEqual((self.data / "AGENTS.md").read_text(encoding="utf-8"), "mine")
        self.assertFalse((self.data / "roles" / "art" / "ROLE.md").exists())
        self.assertEqual((self.data / B.MARKER).read_bytes(), before)

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
        self.assertFalse((self.data / "AGENTS.md").exists())
        self.assertFalse((self.data / B.MARKER).exists())
        self.assertEqual(list(self.data.iterdir()), [])
        self.assertTrue(B.bootstrap(self.data)["created"])   # and the next start completes it

    def test_the_cli_uses_the_given_folder(self):
        env = {k: v for k, v in os.environ.items() if k not in ("CHATBOT_DATA", "PE_HOME", "PRIVATEENGINE_HOME")}
        r = subprocess.run([sys.executable, str(ENGINE / "data_bootstrap.py"), "--data", str(self.data), "--quiet"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("new workspace", r.stdout)
        r = subprocess.run([sys.executable, str(ENGINE / "data_bootstrap.py"), "--data", str(self.data), "--quiet"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
