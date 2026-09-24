"""chatbot-ctl.sh finds its own folder through the ~/services symlink (CTL_SYMLINK_v1). Without that, CODE became
~/services: the scheduled doctor looked for ~/services/server.py and failed every run for 18 hours, writing to a
stray ~/services/logs.
Run: python3 -m unittest tests.test_ctl_paths  (from services/chatbot)
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

CTL = Path(__file__).resolve().parent.parent / "chatbot-ctl.sh"


class CtlPaths(unittest.TestCase):
    def test_the_script_dir_follows_a_symlink(self):
        head = []
        for line in CTL.read_text(encoding="utf-8").splitlines():
            head.append(line)
            if line.startswith("SCRIPT_DIR="):
                break
        self.assertTrue(head[-1].startswith("SCRIPT_DIR="), "SCRIPT_DIR line missing")
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "code" / "ctl.sh"
            real.parent.mkdir()
            real.write_text("\n".join(head) + '\necho "$SCRIPT_DIR"\n', encoding="utf-8")
            link = Path(d) / "ctl-link.sh"
            os.symlink(real, link)
            out = subprocess.run(["bash", str(link)], capture_output=True, text=True, timeout=10).stdout.strip()
        self.assertEqual(Path(out).resolve(), real.parent.resolve())


if __name__ == "__main__":
    unittest.main()
