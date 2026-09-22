"""evolution.py observation side: which finished turns become candidates, and observation-log entries.
Run: python3 -m unittest tests.test_observation  (from services/chatbot)
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import evolution  # noqa: E402

CFG = evolution.load_signal_config(CODE)


def tmpdir():
    return Path(tempfile.mkdtemp()).resolve()


def signals(outcome="result", marks=(), text="안녕"):
    return [s for s, _ in evolution.turn_signals(CFG, outcome, list(marks), text)]


class ShippedSignalsTest(unittest.TestCase):
    def test_the_shipped_data_file_loads_and_protects_the_probe(self):
        self.assertTrue(CFG["correction"])
        self.assertEqual(CFG["ignore_user_prefixes"], ["[doctor-probe]"])
        self.assertTrue(evolution.is_protected(CODE, CODE / evolution.SIGNALS_NAME))

    def test_corrections_the_design_names(self):
        for text in ("아니 그게 아니야", "아니, 다시", "왜 안 돼?", "이거 망가졌어", "안돼", "이건 틀렸어", "버그 같아"):
            self.assertEqual(signals(text=text), ["correction"], text)

    def test_ordinary_talk_is_not_a_candidate(self):
        for text in ("안녕", "오늘 날씨 알려줘", "아니요 괜찮아요", "이거 해줘", "", "고마워"):
            self.assertEqual(signals(text=text), [], text)

    def test_host_self_test_turns_are_never_candidates(self):
        self.assertEqual(signals("stopped", ["stopped"], "[doctor-probe] ping"), [])
        self.assertEqual(signals("result", [], "[doctor-probe] 아니 왜 안 돼"), [])


class TurnSignalsTest(unittest.TestCase):
    def test_how_a_turn_ended_becomes_a_signal(self):
        self.assertEqual(signals("stopped", ["stopped"]), ["stopped"])
        self.assertEqual(signals("interrupted", ["interrupted"]), ["interrupted"])
        self.assertEqual(signals("auto_stop", ["stopped"]), ["auto_stop"])
        self.assertEqual(signals("auto_stop", ["error"]), ["auto_stop"])
        self.assertEqual(signals("result", ["error"]), ["error"])

    def test_a_dead_child_is_one_signal_not_two(self):
        self.assertEqual(signals("process_died", ["error"]), ["process_died"])

    def test_steering_is_normal_use(self):
        self.assertEqual(signals("steer", ["interrupted"]), [])
        self.assertEqual(signals("steer", [], "이것도 추가해줘"), [])

    def test_a_clean_turn_records_nothing(self):
        self.assertEqual(signals("result", []), [])

    def test_signal_and_correction_can_come_together(self):
        self.assertEqual(signals("stopped", ["stopped"], "왜 안 돼"), ["stopped", "correction"])

    def test_unknown_marks_are_ignored(self):
        self.assertEqual(signals("result", ["tool", "assistant"]), [])

    def test_bad_patterns_are_skipped_not_fatal(self):
        cfg = {"correction": ["(", "망가"], "ignore_user_prefixes": []}
        self.assertEqual([s for s, _ in evolution.turn_signals(cfg, "result", [], "망가졌다")], ["correction"])


class ConfigTest(unittest.TestCase):
    def test_missing_or_broken_config_means_no_candidates_not_an_error(self):
        empty = {"correction": [], "ignore_user_prefixes": []}
        root = tmpdir()
        self.assertEqual(evolution.load_signal_config(root), empty)
        for text in ("{nope", "[]", '{"correction": "x"}', '{"correction": [1, null]}'):
            (root / evolution.SIGNALS_NAME).write_text(text, encoding="utf-8")
            self.assertEqual(evolution.load_signal_config(root), empty, text)


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.obs = tmpdir()
        self.file = self.obs / evolution.CANDIDATES_NAME

    def lines(self):
        return [json.loads(l) for l in self.file.read_text(encoding="utf-8").splitlines()]

    def test_appends_one_json_line_with_evidence_fields(self):
        self.assertTrue(evolution.record_candidate(self.obs, "correction", "s1", "agy", {"user": "왜 안 돼", "n": 3}))
        self.assertTrue(evolution.record_candidate(self.obs, "stopped", "s1", "agy"))
        rows = self.lines()
        self.assertEqual([r["signal"] for r in rows], ["correction", "stopped"])
        self.assertEqual((rows[0]["sid"], rows[0]["provider"], rows[0]["detail"]), ("s1", "agy", {"user": "왜 안 돼", "n": 3}))
        self.assertTrue(rows[0]["ts"] and rows[0]["epoch"] > 0)

    def test_nothing_is_created_where_no_observation_directory_exists(self):
        missing = self.obs / "nope"
        self.assertFalse(evolution.record_candidate(missing, "stopped", "s", "agy"))
        self.assertFalse(missing.exists())

    def test_never_raises(self):
        (self.obs / evolution.CANDIDATES_NAME).mkdir()  # a directory where the file should be
        self.assertFalse(evolution.record_candidate(self.obs, "stopped", "s", "agy"))
        self.assertFalse(evolution.record_candidate(None, "stopped", "s", "agy"))

    def test_long_values_are_cut(self):
        evolution.record_candidate(self.obs, "x" * 500, "s" * 500, "p" * 500, {"user": "u" * 5000})
        row = self.lines()[0]
        self.assertLessEqual(len(row["signal"]), 40)
        self.assertLessEqual(len(row["sid"]), 80)
        self.assertLessEqual(len(row["detail"]["user"]), 210)

    def test_file_is_trimmed_to_the_newest_lines_when_it_grows(self):
        old = "\n".join(json.dumps({"i": i, "pad": "x" * 400}) for i in range(1000)) + "\n"
        self.file.write_text(old, encoding="utf-8")
        self.assertGreater(self.file.stat().st_size, 256 * 1024)
        evolution.record_candidate(self.obs, "stopped", "s", "agy")
        rows = self.lines()
        self.assertEqual(len(rows), 501)
        self.assertEqual(rows[0]["i"], 500)
        self.assertEqual(rows[-1]["signal"], "stopped")

    def test_concurrent_writers_never_tear_a_line(self):
        def work(n):
            for i in range(20):
                evolution.record_candidate(self.obs, "stopped", "s%d" % n, "agy", {"i": i})
        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(self.lines()), 160)


class OnTurnEndTest(unittest.TestCase):
    def setUp(self):
        self.obs = tmpdir()

    def rows(self):
        p = self.obs / evolution.CANDIDATES_NAME
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def test_records_only_what_a_turn_signals(self):
        self.assertEqual(evolution.on_turn_end(CODE, self.obs, "s", "claude", "result", [], "안녕"), [])
        self.assertEqual(self.rows(), [])
        got = evolution.on_turn_end(CODE, self.obs, "s", "claude", "stopped", ["stopped"], "왜 안 돼   " + "긴" * 400)
        self.assertEqual(got, ["stopped", "correction"])
        detail = self.rows()[0]["detail"]
        self.assertEqual((detail["outcome"], detail["note"]), ("stopped", "stopped"))
        self.assertLessEqual(len(detail["user"]), 200)

    def test_broken_config_or_directory_records_nothing_and_does_not_raise(self):
        self.assertEqual(evolution.on_turn_end(tmpdir(), self.obs, "s", "claude", "stopped", ["stopped"], "x"), ["stopped"])
        self.assertEqual(evolution.on_turn_end(CODE, tmpdir() / "gone", "s", "claude", "stopped", ["stopped"], "x"), [])


class AddObservationTest(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir() / "observation-log"

    def test_creates_the_next_numbered_open_entry_in_the_existing_format(self):
        self.d.mkdir()
        (self.d / "0028-a.md").write_text("x", encoding="utf-8")
        (self.d / "0029-b.md").write_text("x", encoding="utf-8")
        p = evolution.add_observation(self.d, "Provider hair: per-vendor", "Body text.", area="portraits")
        self.assertEqual(p.name, "0030-provider-hair-per-vendor.md")
        text = p.read_text(encoding="utf-8")
        head = text[:400]
        self.assertRegex(head, r"status:\s*open")  # what the badge and the status tab count
        self.assertIn("id: 30\n", text)
        self.assertIn('title: "Provider hair: per-vendor"', text)
        self.assertIn('area: "portraits"', text)
        self.assertTrue(text.rstrip().endswith("Body text."))

    def test_numbers_continue_past_the_archive(self):
        (self.d / "archive").mkdir(parents=True)
        (self.d / "archive" / "0100-old.md").write_text("x", encoding="utf-8")
        (self.d / "archive" / ".id-floor").write_text("105\n", encoding="utf-8")
        self.assertEqual(evolution.add_observation(self.d, "t", "b").name, "0106-t.md")

    def test_first_entry_in_an_empty_or_missing_directory(self):
        self.assertEqual(evolution.add_observation(self.d, "t", "b").name, "0001-t.md")

    def test_two_writers_never_share_a_number(self):
        names = []
        lock = threading.Lock()

        def work():
            p = evolution.add_observation(self.d, "same title", "b")
            with lock:
                names.append(p.name)
        threads = [threading.Thread(target=work) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(set(names)), 8)

    def test_title_and_body_are_bounded_and_single_line_titles(self):
        p = evolution.add_observation(self.d, "line one\nline two " + "x" * 300, "b" * 9000, area="a\nb")
        text = p.read_text(encoding="utf-8")
        title_line = [l for l in text.splitlines() if l.startswith("title:")][0]
        self.assertNotIn("\n", title_line[len("title: "):])
        self.assertLessEqual(len(json.loads(title_line[len("title: "):])), 120)
        self.assertLessEqual(len(text.split("---\n\n", 1)[1].strip()), 4000)

    def test_a_recent_limit_stops_a_runaway_but_not_old_entries(self):
        import os
        import time
        for i in range(3):
            evolution.add_observation(self.d, "note %d" % i, "b")
        with self.assertRaises(evolution.TooManyObservations):
            evolution.add_observation(self.d, "one more", "b", recent_limit=3)
        for f in self.d.iterdir():
            old = time.time() - 7200
            os.utime(str(f), (old, old))
        evolution.add_observation(self.d, "fresh start", "b", recent_limit=3)  # the old ones no longer count
        self.assertEqual(len(list(self.d.iterdir())), 4)

    def test_no_limit_means_no_check(self):
        for i in range(15):
            evolution.add_observation(self.d, "n%d" % i, "b")
        self.assertEqual(len(list(self.d.iterdir())), 15)

    def test_hostile_titles_stay_valid_and_cannot_escape_the_directory(self):
        p = evolution.add_observation(self.d, "../../etc/passwd\n---\nstatus: closed", "b")
        self.assertEqual(p.parent, self.d)
        self.assertRegex(p.name, r"^0001-[a-z0-9-]+\.md$")
        text = p.read_text(encoding="utf-8")
        self.assertEqual(text.count("\n---\n"), 1)


if __name__ == "__main__":
    unittest.main()
