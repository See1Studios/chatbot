"""A merged delegation leaves its line in the work diary (tools/history_entry.py, written by the runner in the ticket
record's commit): the title, the commits and the files of the landed change -- not the ticket records -- above the
newest entry, and the oldest day rotated out when the diary passes its budget. Review of #505-#525: 29 delegated
changes had landed with no line in the diary.
Run: engine/run-tests.sh test_history_entry
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE / "tools"))
import history_entry as D  # noqa: E402

HEAD = "# chatbot 개발로그\n\n2026-09-28 기록은 회전했습니다.\n\n"   # l10n-ok


class DevlogEntry(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@t")
        self.git("config", "core.hooksPath", "/dev/null")
        (self.repo / "docs").mkdir()
        (self.repo / "HISTORY.md").write_text(HEAD + "## 2026-09-30 — old (#1)\n\n- x\n", encoding="utf-8")
        self.base = self.commit("a.py", "1", "chore: start")
        self.commit("static/b.js", "2", "feat(ui): b")
        self.commit("data/dev/tickets/0009.json", "{}", "chore(tickets): #9 awaiting_merge")
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
        self.assertEqual(wrote, ["HISTORY.md"])
        text = (self.repo / "HISTORY.md").read_text(encoding="utf-8")
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
        self.assertEqual(wrote, ["HISTORY.md", "docs/history/2026-09-30.md"])
        text = (self.repo / "HISTORY.md").read_text(encoding="utf-8")
        self.assertNotIn("## 2026-09-30", text)
        self.assertIn("docs/history/2026-09-30.md", text)
        moved = (self.repo / "docs" / "history" / "2026-09-30.md").read_text(encoding="utf-8")
        self.assertTrue(moved.startswith("# chatbot 개발로그 — 2026-09-30"))   # l10n-ok (test_docs_budget's shape)
        self.assertIn("## 2026-09-30 — old (#1)", moved)

    def busy_day(self):
        day = "".join("## 2026-10-08 — e%d (#%d)\n\n- %s\n\n" % (i, i, "x" * 60) for i in range(9, 0, -1))
        (self.repo / "HISTORY.md").write_text(HEAD + day, encoding="utf-8")
        with mock.patch.object(D, "BUDGET", len(HEAD) + 400):
            return D.rotate(self.repo, HEAD + day)

    def test_a_day_over_the_budget_alone_moves_its_earliest_entries(self):
        # BUSY_DAY_v1 (#830): 2026-10-08 one day alone passed the budget; nothing older was left to move
        text, wrote = self.busy_day()
        self.assertEqual(wrote, ["docs/history/2026-10-08.md"])
        self.assertLessEqual(len(text.encode("utf-8")), len(HEAD) + 400 + 200)   # + the note line
        self.assertIn("e9 (#9)", text)                                            # the newest stay
        moved = (self.repo / "docs" / "history" / "2026-10-08.md").read_text(encoding="utf-8")
        self.assertTrue(moved.startswith("# chatbot 개발로그 — 2026-10-08\n\n## 2026-10-08"))   # l10n-ok
        self.assertLess(moved.index("e2 (#2)"), moved.index("e1 (#1)"), "newest first there too")
        self.assertEqual(sum(t.count("## 2026-10-08 — e") for t in (text, moved)), 9, "nothing lost")

    def test_a_split_day_moves_whole_once_the_next_day_begins(self):
        text = self.busy_day()[0]
        text = text.replace("## 2026-10-08 — e9", "## 2026-10-09 — n1 (#10)\n\n- y\n\n## 2026-10-08 — e9", 1)
        text, wrote = D.rotate(self.repo, text)                                 # under the budget, still moved
        self.assertEqual(wrote, ["docs/history/2026-10-08.md"])
        self.assertNotIn("## 2026-10-08", text)
        moved = (self.repo / "docs" / "history" / "2026-10-08.md").read_text(encoding="utf-8")
        self.assertEqual(moved.count("## 2026-10-08 — e"), 9)
        self.assertLess(moved.index("e9 (#9)"), moved.index("e1 (#1)"))

    def test_no_diary_no_head_nothing_written(self):
        self.assertEqual(D.record_merge(self.repo, 9, "t", "claude", self.base, ""), [])
        (self.repo / "HISTORY.md").unlink()
        self.assertEqual(D.record_merge(self.repo, 9, "t", "claude", self.base, self.head), [])

    def test_the_runner_writes_it_with_the_ticket_record(self):
        src = (ENGINE / "tools" / "worktree_runner.py").read_text(encoding="utf-8")
        report = src[src.index("def record_and_report("):src.index("# ---------------------------------------------------------------------- run")]
        self.assertIn("history_entry.record_merge(", report)
        self.assertIn('if result.get("merged"):', report)
        self.assertIn("extra)", report)

    def test_the_diary_line_is_committed_without_a_ticket_record_in_the_repo(self):
        # #626: the records live in ~/.pe; the runner used to commit nothing, and #620's line stayed on main uncommitted
        import worktree_runner as wr
        wrote = D.record_merge(self.repo, 30, "t", "claude", self.base, self.head, day="2026-10-01")
        with mock.patch.dict(wr.PROVIDERS, {"claude": dict(wr.PROVIDERS["claude"], author=("w", "w@w"))}):
            sha = wr.commit_ticket_record(self.repo, 30, "claude", "chore(tickets): close #30 -- t", tuple(wrote))
        self.assertTrue(sha)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("log", "-1", "--format=%s|%an"), "docs(history): close #30 -- t|w")

    def test_the_range_starts_after_the_rebase_so_main_commits_are_not_the_branchs(self):
        # #535 (2026-10-01): main moved during the run, the branch was rebased, and the diary listed the other
        # agents' commits as the worker's -- the merge result kept the base from before the rebase.
        src = (ENGINE / "tools" / "worktree_runner.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("result.update(merged=True, head=head, base=base)"), 2, "both landing paths")
        self.assertNotIn("_, head = land(", src)
        self.assertIn('record_merge(repo, tid, title, provider, result["base"], ', src)
        rebased_base = self.git("rev-parse", "HEAD~1")          # main as the branch was rebased onto it
        D.record_merge(self.repo, 12, "t", "agy", rebased_base, self.git("rev-parse", "HEAD"), day="2026-10-01")
        top = (self.repo / "HISTORY.md").read_text(encoding="utf-8").split("## 2026-09-30")[0]
        self.assertIn("fix(core): a", top)
        self.assertNotIn("feat(ui): b", top)


if __name__ == "__main__":
    unittest.main()
