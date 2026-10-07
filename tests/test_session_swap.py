"""Names a module reads through `session` (`_s().name`, so tests and server.py can swap them there) must exist on
`session`. 398eace (2026-10-06) removed `from instructions import build_instruction_bundle` from session.py as an
unused import; session_turn reads it as `_s().build_instruction_bundle`, so every turn would have failed after the next
restart. A guard test (run-tests.sh FAST): the commit hook catches the next such cleanup.
Run: python3 -m unittest tests.test_session_swap  (from services/chatbot)
"""
import re
import sys
import unittest
from pathlib import Path
from tests._paths import ENGINE, REPO  # noqa: E402

ROOT = REPO
sys.path.insert(0, str(ENGINE))


class SwapPoints(unittest.TestCase):
    def test_every_name_read_through_session_is_on_session(self):
        import session
        read = set()
        for f in sorted(ENGINE.glob("*.py")):
            text = f.read_text(encoding="utf-8")
            if "def _s():" in text:
                code = re.sub(r'(?s)""".*?"""', "", text)   # docstrings name the pattern, not a name
                read |= {(f.name, n) for n in re.findall(r"_s\(\)\.([A-Za-z_]\w*)", code)}
        self.assertTrue(read, "no module reads through session any more: drop this test")
        missing = sorted("%s: _s().%s" % (f, n) for f, n in read if not hasattr(session, n))
        self.assertEqual(missing, [], "session.py must keep (import) these names: modules read them through it")


if __name__ == "__main__":
    unittest.main()
