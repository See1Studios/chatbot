"""_clean_str strips ONE matching quote pair only; commands ending in a quote stay intact.
Run: python3 -m unittest tests.test_tool_format_clean  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tool_format import _clean_str  # noqa: E402


class CleanStrTest(unittest.TestCase):
    def test_matching_pair_stripped(self):
        self.assertEqual(_clean_str('"abc"'), "abc")
        self.assertEqual(_clean_str("'abc'"), "abc")

    def test_command_ending_in_quote_untouched(self):
        for s in ("echo 'hi'", 'grep "a" "b"', "python -c 'print(1)'", 'say "hi"'):
            self.assertEqual(_clean_str(s), s)

    def test_none_and_plain(self):
        self.assertEqual(_clean_str(None), "")
        self.assertEqual(_clean_str("  it's  "), "it's")


if __name__ == "__main__":
    unittest.main()
