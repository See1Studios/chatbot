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
from tests._platform import dev_only_bash  # noqa: E402

CTL = Path(__file__).resolve().parent.parent / "chatbot-ctl.sh"


@dev_only_bash
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


@dev_only_bash
class StartWaitsForHealth(unittest.TestCase):
    """A start is judged when the server answers, not by one check after 1 s (a healthy ~2 s boot was logged as
    ctl.start_failed, 2026-10-01)."""

    def run_wait(self, answers_on, alive=True):
        src = CTL.read_text(encoding="utf-8")
        fn = src[src.index("wait_health_chat() {"):]
        fn = fn[:fn.index("\n}\n") + 3]
        script = ("n=0; sleep() { :; }; health_chat() { n=$((n+1)); [ $n -ge %d ]; }; is_up() { %s; }\n%s\n"
                  "START_WAIT_SEC=15; wait_health_chat; echo \"$? $n\"") % (answers_on, "true" if alive else "false", fn)
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.split()

    def test_a_slow_boot_is_waited_for(self):
        self.assertEqual(self.run_wait(3), ["0", "3"])

    def test_a_dead_process_fails_at_once_and_a_silent_one_in_time(self):
        self.assertEqual(self.run_wait(99, alive=False), ["1", "1"])
        self.assertEqual(self.run_wait(99), ["1", "15"])

    def test_start_uses_it(self):
        src = CTL.read_text(encoding="utf-8")
        start = src[src.index("cmd_start() {"):]
        self.assertIn("if wait_health_chat; then", start[:start.index("\n}\n")])


if __name__ == "__main__":
    unittest.main()
