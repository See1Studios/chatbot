"""Moving code into a folder must not move it out of protection (FOLDERS_PROVIDERS_v1): protected_paths.json's `*.py`
covers only the root, so every code folder needs its own entry. A module an agent could change without a ticket is
a hole in the self-modification rules.
Run: python3 -m unittest tests.test_code_layout  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import evolution  # noqa: E402

CODE_DIRS = ["", "providers"]   # folders of host code; add one here when you make it


class CodeLayout(unittest.TestCase):
    def test_every_host_module_is_protected(self):
        for d in CODE_DIRS:
            for p in sorted((ROOT / d).glob("*.py")):
                self.assertTrue(evolution.is_protected(ROOT, p), "%s is not protected: add its folder to "
                                "protected_paths.json" % p.relative_to(ROOT))

    def test_every_code_folder_is_listed(self):
        for p in ROOT.iterdir():
            if p.is_dir() and (p / "__init__.py").exists():
                self.assertIn(p.name, CODE_DIRS, "%s/ is a code package: list it in CODE_DIRS and protect it" % p.name)


if __name__ == "__main__":
    unittest.main()
