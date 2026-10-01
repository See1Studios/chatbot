"""A delegated CODE change is reviewed against a checklist of the bug kinds the review of #505-#525 found (they had
passed a cross-provider review that only asked "correctly and safely?"); a documentation change keeps its own.
Run: python3 -m unittest tests.test_review_checklist  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import review_checklist as R  # noqa: E402


class ReviewChecklist(unittest.TestCase):
    def test_the_checklist_sits_before_the_verdict_question(self):
        base = "Diff ...\nAs the producer, confirm the work: does it?\nVERDICT: PASS or VERDICT: FAIL"
        out = R.with_code_checklist(base)
        self.assertLess(out.index("This changes code."), out.index("As the producer, confirm the work:"))
        self.assertEqual(out.count("This changes code."), 1)
        self.assertTrue(R.with_code_checklist("no marker").endswith(R.CODE_CHECKLIST))

    def test_each_kind_the_review_found_is_asked(self):
        for ticket in ("#516", "#506", "#522", "#515", "#518", "#505", "#534"):
            self.assertIn(ticket, R.CODE_CHECKLIST)
        self.assertIn("test", R.CODE_CHECKLIST.splitlines()[-1])

    def test_the_runner_uses_it_for_code_and_the_doc_list_for_docs(self):
        src = (ROOT / "tools" / "worktree_runner.py").read_text(encoding="utf-8")
        self.assertIn("(doc_review_prompt if doc_lane else (lambda b, d: with_code_checklist(b)))(", src)


if __name__ == "__main__":
    unittest.main()
