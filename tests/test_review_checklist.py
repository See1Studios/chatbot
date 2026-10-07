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
        self.assertIn("Mandatory Test Pairing", R.CODE_CHECKLIST)
        self.assertIn("Async timeout", R.CODE_CHECKLIST)
        self.assertIn("Banter limit", R.CODE_CHECKLIST)
        self.assertIn("test", R.CODE_CHECKLIST)

    def test_the_runner_uses_it_for_code_and_the_doc_list_for_docs(self):
        src = (ROOT / "tools" / "worktree_runner.py").read_text(encoding="utf-8")
        self.assertIn("(doc_review_prompt if doc_lane else (lambda b, d: with_code_checklist(b)))(", src)

    def test_diff_files_extracts_paths(self):
        diff = (
            "diff --git a/session.py b/session.py\n--- a/session.py\n+++ b/session.py\n"
            "diff --git a/docs/CONCEPT.md b/docs/CONCEPT.md\n"
            "diff --git a/old.py b/dev/null\n"
        )
        files = R.diff_files(diff)
        self.assertEqual(files, ["session.py", "docs/CONCEPT.md", "old.py"])

    def test_check_test_pairing_rules(self):
        # 1. Non-code changes pass
        ok, msg = R.check_test_pairing(paths=["docs/plans/foo.md", "data/workspace/card.json"])
        self.assertTrue(ok)
        self.assertIn("No product code", msg)

        # 2. Code changes paired with test pass
        ok, msg = R.check_test_pairing(paths=["session.py", "tests/test_session.py"])
        self.assertTrue(ok)
        self.assertIn("Tests paired", msg)

        # 3. Code changes without test fail
        ok, msg = R.check_test_pairing(paths=["session.py", "tools/foo.py"])
        self.assertFalse(ok)
        self.assertIn("Mandatory Test Pairing violation", msg)
        self.assertIn("session.py", msg)

        # 4. Test-only changes pass
        ok, msg = R.check_test_pairing(paths=["tests/test_foo.py"])
        self.assertTrue(ok)

    def test_review_prompt_and_checklist_warn_on_unpaired_code(self):
        unpaired_diff = "diff --git a/session.py b/session.py\n--- a/session.py\n+++ b/session.py\n@@ -1 +1 @@\n+x = 1\n"
        paired_diff = unpaired_diff + "diff --git a/tests/test_session.py b/tests/test_session.py\n+++ b/tests/test_session.py\n"

        prompt_unpaired = R.review_prompt(100, "title", "instruction", "", unpaired_diff, None, "character")
        self.assertIn("WARNING: Mandatory Test Pairing violation", prompt_unpaired)

        prompt_paired = R.review_prompt(100, "title", "instruction", "", paired_diff, None, "character")
        self.assertNotIn("WARNING: Mandatory Test Pairing violation", prompt_paired)

        checklist_warn = R.with_code_checklist("As the producer, confirm the work:", diff=unpaired_diff)
        self.assertIn("WARNING: Mandatory Test Pairing violation", checklist_warn)


if __name__ == "__main__":
    unittest.main()
