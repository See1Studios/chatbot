"""A merged delegation leaves its line in the work diary (tools/devlog_entry.py, written by the runner in the ticket
record's commit): the title, the commits and the files of the landed change -- not the ticket records -- above the
newest entry, and the oldest day rotated out when the diary passes its budget. Review of #505-#525: 29 delegated
changes had landed with no line in the diary.
Run: python3 -m unittest tests.test_devlog_entry  (from services/chatbot)
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import devlog_entry as D  # noqa: E402

HEAD = "# chatbot 개발로그\n\n2026-09-28 기록은 회전했습니다.\n\n"   # l10n-ok


class DevlogEntry(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@t")
        self.git("config", "core.hooksPath", "/dev/null")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "DEVLOG.md").write_text(HEAD + "## 2026-09-30 — old (#1)\n\n- x\n", encoding="utf-8")
        self.base = self.commit("a.py", "1", "chore: start")
        self.commit("static/b.js", "2", "feat(ui): b")
        self.commit("data/workspace/skill-observations/tickets/0009.json", "{}", "chore(tickets): #9 awaiting_merge")
        self.head = self.commit("a.py", "3", "fix(core): a")

    def tearDown(self):
        shutil.rmtree(str(self.repo), ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.repo), capture_output=True, text=True).stdout.strip()

    def commit(self, rel, text, msg):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self.git("add", rel)
        self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD")

    def test_the_entry_goes_above_the_newest_and_names_the_change(self):
        wrote = D.record_merge(self.repo, 9, "목록 머리 아이콘", "claude", self.base, self.head, day="2026-10-01")   # l10n-ok
        self.assertEqual(wrote, ["docs/DEVLOG.md"])
        text = (self.repo / "docs" / "DEVLOG.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(HEAD + "## 2026-10-01 — 목록 머리 아이콘 (#9, 위임 claude)"))   # l10n-ok
        self.assertLess(text.index("#9"), text.index("## 2026-09-30"))
        block = text[len(HEAD):text.index("## 2026-09-30")]
        self.assertIn("feat(ui): b", block)
        self.assertIn("fix(core): a", block)
        self.assertNotIn("chore: start", block)                          # before the base
        self.assertIn("`static/b.js`", block)
        self.assertNotIn("tickets/0009.json", block)                      # the record is not the change

    def test_an_over_budget_diary_rotates_its_oldest_day(self):
        with mock.patch.object(D, "BUDGET", 200):
            wrote = D.record_merge(self.repo, 9, "t", "claude", self.base, self.head, day="2026-10-01")
        self.assertEqual(wrote, ["docs/DEVLOG.md", "docs/devlog/2026-09-30.md"])
        text = (self.repo / "docs" / "DEVLOG.md").read_text(encoding="utf-8")
        self.assertNotIn("## 2026-09-30", text)
        self.assertIn("devlog/2026-09-30.md", text)
        moved = (self.repo / "docs" / "devlog" / "2026-09-30.md").read_text(encoding="utf-8")
        self.assertTrue(moved.startswith("# chatbot 개발로그 — 2026-09-30"))   # l10n-ok (test_docs_budget's shape)
        self.assertIn("## 2026-09-30 — old (#1)", moved)

    def test_no_diary_no_head_nothing_written(self):
        self.assertEqual(D.record_merge(self.repo, 9, "t", "claude", self.base, ""), [])
        (self.repo / "docs" / "DEVLOG.md").unlink()
        self.assertEqual(D.record_merge(self.repo, 9, "t", "claude", self.base, self.head), [])

    def test_the_runner_writes_it_with_the_ticket_record(self):
        src = (ROOT / "tools" / "worktree_runner.py").read_text(encoding="utf-8")
        report = src[src.index("def record_and_report("):src.index("# ---------------------------------------------------------------------- run")]
        self.assertIn("devlog_entry.record_merge(", report)
        self.assertIn('if result.get("merged"):', report)
        self.assertIn("extra)", report)


if __name__ == "__main__":
    unittest.main()
