"""tools/run_modules.py: the suite without bash (platform-portability pp/C, #401). Its guard list is run-tests.sh's.
Run: engine/run-tests.sh test_run_modules
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE / "tools"))
import run_modules  # noqa: E402


class RunModules(unittest.TestCase):
    def test_the_fast_list_is_the_one_in_run_tests_sh(self):
        fast = run_modules.fast_modules()
        self.assertGreater(len(fast), 5)
        body = re.search(r"^FAST=\((.*?)^\)", (ENGINE / "run-tests.sh").read_text(encoding="utf-8"), re.S | re.M).group(1)
        self.assertEqual(fast, re.findall(r"\b(test_\w+)\b", body))
        for m in fast:
            self.assertTrue((ROOT / "tests" / (m + ".py")).is_file(), m)

    def test_it_runs_a_module_and_reports_like_run_tests_sh(self):
        p = subprocess.run([sys.executable, str(ENGINE / "tools" / "run_modules.py"), "test_file_sizes"], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"ok +\d+ms test_file_sizes")
        self.assertIn("1/1 modules passed", p.stdout)

    def test_a_missing_module_fails(self):
        p = subprocess.run([sys.executable, str(ENGINE / "tools" / "run_modules.py"), "test_no_such_thing"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 1)
        self.assertIn("MISSING test_no_such_thing", p.stdout)


if __name__ == "__main__":
    unittest.main()
