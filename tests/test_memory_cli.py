"""data/workspace/tools/memory.py: the long-term memory command line the CLI providers use.

It is a thin shell over the core `memory_store.py`; these tests pin what a provider sees (output, exit codes).
The script derives its directory from its own location, so each test copies it into a temp tree
(<tmp>/tools/memory.py -> <tmp>/memory/MEMORY.md) and runs it there against the real core code.
Nothing touches the real memory file.
Run: python3 -m unittest tests.test_memory_cli  (from services/chatbot)
"""
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("MEMORY_CLI_SCRIPT") or CODE / "data" / "workspace" / "tools" / "memory.py")
TODAY = datetime.date.today().isoformat()
TEMPLATE_SECTIONS = ["## 실장님", "## 운영 결정", "## 진행 중"]


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        (self.root / "tools").mkdir()
        shutil.copy(str(SCRIPT), str(self.root / "tools" / "memory.py"))
        self.file = self.root / "memory" / "MEMORY.md"

    def run_cli(self, *args, code_root=None):
        env = dict(os.environ, AGY_CHAT_ROOT=str(code_root or CODE))  # the host exports this to every provider
        p = subprocess.run([sys.executable, str(self.root / "tools" / "memory.py")] + list(args), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
        return p.returncode, p.stdout, p.stderr

    def body(self):
        return self.file.read_text(encoding="utf-8")

    def lines(self):
        return [l for l in self.body().splitlines() if l.startswith("- ")]


class ShowAndTemplateTest(Base):
    def test_a_fresh_memory_is_created_from_the_template(self):
        rc, out, _ = self.run_cli("show")
        self.assertEqual(rc, 0)
        for header in TEMPLATE_SECTIONS:
            self.assertIn(header, out)
        self.assertEqual(out, self.body())
        self.assertFalse((self.root / "memory" / ".MEMORY.lock").exists(), "reading takes no lock")

    def test_writing_takes_the_lock_file(self):
        self.run_cli("add", "x")
        self.assertTrue((self.root / "memory" / ".MEMORY.lock").exists())


class AddTest(Base):
    def test_add_puts_a_dated_line_under_the_default_section(self):
        rc, out, _ = self.run_cli("add", "실장님은 상대경로를 선호한다")
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["기록함 → ## 실장님", "- [%s] 실장님은 상대경로를 선호한다" % TODAY])
        self.assertEqual(self.lines(), ["- [%s] 실장님은 상대경로를 선호한다" % TODAY])

    def test_add_to_another_section_goes_before_the_next_header(self):
        self.run_cli("add", "first")
        self.run_cli("add", "포트 3014", "--section", "운영 결정")
        self.run_cli("add", "second")
        body = self.body()
        self.assertLess(body.index("first"), body.index("## 운영 결정"))
        self.assertLess(body.index("second"), body.index("## 운영 결정"))
        self.assertLess(body.index("## 운영 결정"), body.index("포트 3014"))
        self.assertLess(body.index("포트 3014"), body.index("## 진행 중"))

    def test_words_are_joined_whitespace_collapsed_and_a_dash_prefix_dropped(self):
        self.run_cli("add", "- a", "  b\t c ")
        self.assertEqual(self.lines(), ["- [%s] a b c" % TODAY])

    def test_a_near_duplicate_is_not_added(self):
        self.run_cli("add", "커피는 아메리카노")
        rc, out, _ = self.run_cli("add", "COFFEE는 아메리카노".replace("COFFEE", "커피"))  # same text
        self.assertEqual(rc, 0)
        self.assertIn("이미 있는 사실에 가깝습니다. 추가하지 않았습니다.", out)
        self.assertEqual(len(self.lines()), 1)
        rc, out, _ = self.run_cli("add", "아메리카노")  # a substring of an existing fact counts too
        self.assertIn("이미 있는 사실", out)

    def test_unknown_section_and_empty_text_are_refused(self):
        rc, _, err = self.run_cli("add", "x", "--section", "없는 섹션")
        self.assertEqual(rc, 2)
        self.assertIn("--section 은 실장님, 운영 결정, 진행 중 중 하나.", err)
        rc, _, err = self.run_cli("add", "   ")
        self.assertEqual(rc, 2)
        self.assertIn("추가할 사실이 없습니다.", err)
        self.assertEqual(self.lines(), [])  # sections are read from the file, so it may have been opened; no fact was added

    def test_the_size_cap_refuses_and_leaves_the_file_alone(self):
        for n in range(1, 40):  # bounded; each fact is ~250 hangul = 750 bytes, so the cap is hit within a few
            before = self.body() if self.file.exists() else None
            rc, _, err = self.run_cli("add", "%02d %s" % (n, "가" * 250), "--section", "운영 결정")
            if rc != 0:
                break
        self.assertEqual(rc, 3)
        self.assertIn("4096바이트를 넘습니다", err)
        self.assertEqual(self.body(), before)

    def test_a_single_overlong_fact_is_refused_as_a_bad_request(self):
        rc, _, err = self.run_cli("add", "가" * 400)
        self.assertEqual(rc, 2)
        self.assertIn("너무 깁니다", err)

    def test_no_temp_files_are_left_behind(self):
        self.run_cli("add", "one")
        self.run_cli("forget", "one")
        self.assertEqual(sorted(p.name for p in (self.root / "memory").iterdir()), [".MEMORY.lock", "MEMORY.md", "MEMORY.md.bak"])

    def test_a_date_already_in_the_fact_is_not_doubled(self):  # was: "- [today] [2026-09-20] ..."
        self.run_cli("add", "[2026-09-20] 실장님 따님 이름은 시원이다.")
        self.assertEqual(self.lines(), ["- [%s] 실장님 따님 이름은 시원이다." % TODAY])

    def test_the_previous_version_is_kept_as_a_backup(self):  # new: there used to be none
        self.run_cli("add", "first")
        after_first = self.body()
        self.run_cli("add", "second")
        self.assertEqual((self.root / "memory" / "MEMORY.md.bak").read_text(encoding="utf-8"), after_first)


class SearchTest(Base):
    def test_search_lists_matching_facts_with_their_section(self):
        self.run_cli("add", "포트 3014", "--section", "운영 결정")
        self.run_cli("add", "커피는 아메리카노")
        rc, out, _ = self.run_cli("search", "포트")
        self.assertEqual((rc, out), (0, "[운영 결정] - [%s] 포트 3014\n" % TODAY))
        rc, out, _ = self.run_cli("search", "PORT".lower())
        self.assertEqual((rc, out), (0, "'port' 없음.\n"))

    def test_search_is_case_insensitive_and_needs_a_query(self):
        self.run_cli("add", "Higgsfield port")
        self.assertIn("Higgsfield", self.run_cli("search", "HIGGS")[1])
        rc, _, err = self.run_cli("search", "  ")
        self.assertEqual(rc, 2)
        self.assertIn("검색어가 없습니다.", err)


class ForgetTest(Base):
    def test_forget_removes_the_matching_line_and_says_which(self):
        self.run_cli("add", "keep this")
        self.run_cli("add", "drop me please")
        rc, out, _ = self.run_cli("forget", "drop me")
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["지움 1줄:", "- [%s] drop me please" % TODAY])
        self.assertEqual(self.lines(), ["- [%s] keep this" % TODAY])

    def test_nothing_to_forget_and_too_short_a_query(self):
        self.run_cli("add", "keep this")
        rc, out, _ = self.run_cli("forget", "absent")
        self.assertEqual((rc, out), (0, "일치하는 줄이 없습니다.\n"))
        rc, _, err = self.run_cli("forget", "k")
        self.assertEqual(rc, 2)
        self.assertIn("두 글자 이상", err)
        self.assertEqual(len(self.lines()), 1)

    def test_a_broad_query_is_refused_and_all_is_explicit(self):  # was: silently deleted every matching line, no backup
        for fact in ("실장님은 A", "실장님은 B", "실장님은 C"):
            self.run_cli("add", fact)
        rc, out, err = self.run_cli("forget", "실장님")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("3줄이 일치합니다", err)
        self.assertEqual(len(self.lines()), 3)
        rc, out, _ = self.run_cli("forget", "실장님", "--all")
        self.assertEqual(rc, 0)
        self.assertIn("지움 3줄:", out)
        self.assertEqual(self.lines(), [])
        self.assertIn("실장님은 A", (self.root / "memory" / "MEMORY.md.bak").read_text(encoding="utf-8"))


class ThinShellTest(Base):
    """The old implementation was discarded: the rules live in the core, in one place."""

    def test_the_script_no_longer_carries_the_rules(self):
        src = SCRIPT.read_text(encoding="utf-8")
        for old in ("fcntl", "tempfile", "MAX_BYTES", "_insert_line", "os.replace", "mkstemp"):
            self.assertNotIn(old, src)
        self.assertLess(len(src.splitlines()), 100)

    def test_without_the_core_it_says_so_and_writes_nothing(self):
        empty = Path(tempfile.mkdtemp()).resolve()
        rc, out, err = self.run_cli("add", "x", code_root=empty)
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("memory_store.py", err)
        self.assertFalse(self.file.exists())

    def test_the_core_is_found_from_the_workspace_location_when_the_host_did_not_say(self):
        real = CODE / "data" / "workspace" / "tools" / "memory.py"
        src = real.read_text(encoding="utf-8")
        self.assertIn('os.environ.get("AGY_CHAT_ROOT") or str(WORKSPACE.parent.parent)', src)


if __name__ == "__main__":
    unittest.main()
