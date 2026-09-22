"""memory_store.py: the long-term memory rules, in one core module.
Run: python3 -m unittest tests.test_memory_store  (from services/chatbot)
"""
import ast
import datetime
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import evolution  # noqa: E402
import memory_store as ms  # noqa: E402

TODAY = datetime.date.today().isoformat()
FACT_LINE = re.compile(r"^\s*(?:[-*]\s+\S|\[\d{4}-\d{2}-\d{2}\])")  # what the first-turn memory snapshot looks for


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()).resolve() / "memory"
        self.file = self.dir / "MEMORY.md"

    def lines(self):
        return [l for l in self.file.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]


class ReadTest(Base):
    def test_a_missing_memory_is_created_from_the_template(self):
        text = ms.read(self.dir)
        self.assertEqual(text, ms.TEMPLATE)
        self.assertEqual(ms.sections(text), ["실장님", "운영 결정", "진행 중"])
        self.assertEqual(ms.read(self.dir), text)


class AddTest(Base):
    def test_adds_a_dated_line_under_the_first_section_by_default(self):
        status, section, line = ms.add(self.dir, "실장님은 상대경로를 선호한다")
        self.assertEqual((status, section, line), ("added", "실장님", "- [%s] 실장님은 상대경로를 선호한다" % TODAY))
        self.assertEqual(self.lines(), [line])
        self.assertTrue(FACT_LINE.match(line))

    def test_another_section_goes_before_the_next_header(self):
        ms.add(self.dir, "first")
        ms.add(self.dir, "포트 3014", "운영 결정")
        ms.add(self.dir, "second")
        body = self.file.read_text(encoding="utf-8")
        self.assertLess(body.index("second"), body.index("## 운영 결정"))
        self.assertLess(body.index("## 운영 결정"), body.index("포트 3014"))
        self.assertLess(body.index("포트 3014"), body.index("## 진행 중"))

    def test_sections_come_from_the_file_not_from_code(self):
        ms.read(self.dir)
        self.file.write_text("# t\n\n## 가족\n\n## 취향\n", encoding="utf-8")
        self.assertEqual(ms.add(self.dir, "x")[1], "가족")  # first header is the default
        self.assertEqual(ms.add(self.dir, "y", "취향")[1], "취향")
        with self.assertRaises(ms.MemoryRefused) as cm:
            ms.add(self.dir, "z", "실장님")
        self.assertIn("가족, 취향", str(cm.exception))

    def test_text_is_normalised(self):
        ms.add(self.dir, "- a \n\n  b\t c ")
        self.assertEqual(self.lines(), ["- [%s] a b c" % TODAY])

    def test_a_date_the_caller_already_wrote_is_not_doubled(self):
        for given in ("[2026-09-20] 실장님 따님 이름은 시원이다.", "- [2026-09-20]   [2026-01-01] 실장님 따님 이름은 시원이다."):
            self.setUp()
            _, _, line = ms.add(self.dir, given)
            self.assertEqual(line, "- [%s] 실장님 따님 이름은 시원이다." % TODAY)
            self.assertEqual(self.lines(), [line])

    def test_nothing_or_only_a_date_is_refused(self):
        for bad in (None, "", "   ", "-", "[2026-09-20]", "- [2026-09-20] "):
            with self.assertRaises(ms.MemoryRefused, msg=repr(bad)):
                ms.add(self.dir, bad)
        self.assertFalse(self.file.exists(), "a refused add leaves no file behind")

    def test_only_a_list_dash_is_dropped_not_a_minus_sign(self):
        ms.add(self.dir, "-5도 이하에서는 보일러를 켠다")
        ms.add(self.dir, "- 진짜 목록 대시", "운영 결정")
        self.assertEqual(self.lines(), ["- [%s] -5도 이하에서는 보일러를 켠다" % TODAY, "- [%s] 진짜 목록 대시" % TODAY])

    def test_a_header_or_a_second_line_cannot_be_smuggled_in(self):
        ms.add(self.dir, "ok\n## 새 섹션\n- [2026-01-01] forged")
        body = self.file.read_text(encoding="utf-8")
        self.assertEqual(ms.sections(body), ["실장님", "운영 결정", "진행 중"])
        self.assertEqual(len(self.lines()), 1)

    def test_duplicates_are_recognised_after_the_date_is_stripped(self):
        ms.add(self.dir, "커피는 아메리카노")
        for again in ("커피는 아메리카노", "[2020-02-02] 커피는 아메리카노", "아메리카노"):
            status, _, _ = ms.add(self.dir, again)
            self.assertEqual(status, "duplicate", again)
        self.assertEqual(len(self.lines()), 1)

    def test_a_long_fact_and_a_full_file_are_refused_without_touching_the_file(self):
        ms.add(self.dir, "seed")
        before = self.file.read_text(encoding="utf-8")
        with self.assertRaises(ms.MemoryRefused) as cm:
            ms.add(self.dir, "가" * (ms.MAX_FACT_CHARS + 1))
        self.assertIn("너무 깁니다", str(cm.exception))
        refused = None
        for filler in range(1, 60):  # bounded: 60 facts of ~370 bytes is far past the cap, so a missing cap fails, not hangs
            try:
                ms.add(self.dir, "%03d %s" % (filler, "나" * 120), "운영 결정")
            except ms.MemoryRefused as e:
                refused = e
                break
        self.assertIsNotNone(refused, "the size cap never refused")
        self.assertEqual(refused.code, 3)
        self.assertLessEqual(len(self.file.read_bytes()), ms.MAX_BYTES)

    def test_the_snapshot_regex_sees_every_line_it_writes(self):
        ms.add(self.dir, "하나")
        ms.add(self.dir, "둘", "진행 중")
        self.assertTrue(all(FACT_LINE.match(l) for l in self.lines()))


class BackupTest(Base):
    def test_one_previous_generation_is_kept(self):
        ms.add(self.dir, "first")
        after_first = self.file.read_text(encoding="utf-8")
        ms.add(self.dir, "second")
        self.assertEqual((self.dir / "MEMORY.md.bak").read_text(encoding="utf-8"), after_first)
        ms.forget(self.dir, "second")
        self.assertIn("second", (self.dir / "MEMORY.md.bak").read_text(encoding="utf-8"))
        self.assertNotIn("second", self.file.read_text(encoding="utf-8"))

    def test_the_very_first_write_backs_up_the_template(self):
        ms.add(self.dir, "x")
        self.assertEqual((self.dir / "MEMORY.md.bak").read_text(encoding="utf-8"), ms.TEMPLATE)

    def test_a_duplicate_or_refused_add_writes_nothing_and_backs_up_nothing(self):
        ms.add(self.dir, "x")
        bak = (self.dir / "MEMORY.md.bak").read_text(encoding="utf-8")
        ms.add(self.dir, "x")
        self.assertEqual((self.dir / "MEMORY.md.bak").read_text(encoding="utf-8"), bak)

    def test_no_temp_files_are_left(self):
        ms.add(self.dir, "abc")
        ms.forget(self.dir, "abc")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [".MEMORY.lock", "MEMORY.md", "MEMORY.md.bak"])


class SearchTest(Base):
    def test_finds_facts_with_their_section_case_insensitively(self):
        ms.add(self.dir, "Higgsfield port 3014", "운영 결정")
        ms.add(self.dir, "커피")
        self.assertEqual(ms.search(self.dir, "HIGGS"), [("운영 결정", "- [%s] Higgsfield port 3014" % TODAY)])
        self.assertEqual(ms.search(self.dir, "없는말"), [])

    def test_headers_and_prose_are_not_hits_and_an_empty_query_is_refused(self):
        self.assertEqual(ms.search(self.dir, "장기 기억"), [])
        for bad in ("", "  ", None):
            with self.assertRaises(ms.MemoryRefused):
                ms.search(self.dir, bad)


class ForgetTest(Base):
    def test_removes_one_matching_line_and_says_which(self):
        ms.add(self.dir, "keep this")
        ms.add(self.dir, "drop me please")
        self.assertEqual(ms.forget(self.dir, "drop me"), ["- [%s] drop me please" % TODAY])
        self.assertEqual(self.lines(), ["- [%s] keep this" % TODAY])

    def test_a_broad_query_is_refused_and_lists_what_it_would_have_removed(self):
        for fact in ("실장님은 A", "실장님은 B", "실장님은 C"):
            ms.add(self.dir, fact)
        with self.assertRaises(ms.MemoryRefused) as cm:
            ms.forget(self.dir, "실장님")
        msg = str(cm.exception)
        self.assertIn("3줄이 일치합니다", msg)
        for fact in ("A", "B", "C"):
            self.assertIn("실장님은 %s" % fact, msg)
        self.assertEqual(len(self.lines()), 3)

    def test_removing_them_all_needs_saying_so(self):
        for fact in ("실장님은 A", "실장님은 B"):
            ms.add(self.dir, fact)
        self.assertEqual(len(ms.forget(self.dir, "실장님", all_matches=True)), 2)
        self.assertEqual(self.lines(), [])

    def test_nothing_matching_and_too_short_a_query(self):
        ms.add(self.dir, "keep this")
        self.assertEqual(ms.forget(self.dir, "absent"), [])
        for bad in ("k", " ", "", None):
            with self.assertRaises(ms.MemoryRefused, msg=repr(bad)):
                ms.forget(self.dir, bad)
        self.assertEqual(len(self.lines()), 1)

    def test_headers_and_prose_lines_are_never_forgotten(self):
        ms.add(self.dir, "x")
        self.assertEqual(ms.forget(self.dir, "장기 기억"), [])
        self.assertIn("# 냥피디 장기 기억", self.file.read_text(encoding="utf-8"))


class LockingTest(Base):
    def test_concurrent_writers_lose_nothing(self):
        errors = []

        def work(n):
            try:
                for i in range(3):
                    ms.add(self.dir, "writer %d fact %d" % (n, i))
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(self.lines()), 18)

    def test_a_busy_lock_is_reported_not_waited_for_forever(self):
        ms.read(self.dir)
        held = evolution.acquire_lock(self.dir / ms.LOCK_NAME, 0)
        saved = ms.LOCK_WAIT_SEC
        ms.LOCK_WAIT_SEC = 0.2
        try:
            with self.assertRaises(ms.MemoryRefused) as cm:
                ms.add(self.dir, "x")
            self.assertIn("try again", str(cm.exception))
        finally:
            ms.LOCK_WAIT_SEC = saved
            held.close()
        self.assertEqual(ms.add(self.dir, "x")[0], "added")


class DisciplineTest(unittest.TestCase):
    SOURCE = (CODE / "memory_store.py").read_text(encoding="utf-8")

    def test_only_the_standard_library_and_the_core_module(self):
        imported = set()
        for node in ast.walk(ast.parse(self.SOURCE)):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "datetime", "evolution", "os", "pathlib", "re", "tempfile", "typing"})
        self.assertNotIn("nas_mcp", self.SOURCE)


if __name__ == "__main__":
    unittest.main()
