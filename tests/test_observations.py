"""observations.py: what happens to an observation after it is recorded (scan, resolve, archive, review).
Run: python3 -m unittest tests.test_observations  (from services/chatbot)
"""
import ast
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import evolution  # noqa: E402
import observations as ob  # noqa: E402
import tickets  # noqa: E402

DAY = 86400.0
NOW = time.mktime(time.strptime("2026-09-20 12:00:00", "%Y-%m-%d %H:%M:%S"))


def day(offset=0):
    return time.strftime("%Y-%m-%d", time.localtime(NOW + offset * DAY))


def entry(oid, title="A finding", status="open", resolved="", extra=""):
    return ("---\nid: %d\ntitle: %s\nstatus: %s\ntype: internal\nskill:\n  - chatbot-self-improve\nproposes_skill: []\n"
            "area: ui\ndate: 2026-09-01\nparked_until:\nresolved: %s\nresolution:\nreference:\n%s---\n\n**Issue:** body of %d.\n"
            % (oid, title, status, resolved, extra, oid))


class Base(unittest.TestCase):
    def setUp(self):
        self.obs = Path(tempfile.mkdtemp()).resolve()
        self.log = self.obs / "observation-log"
        self.log.mkdir()

    def put(self, oid, slug="x", archive=False, **kw):
        d = self.log / "archive" if archive else self.log
        d.mkdir(exist_ok=True)
        p = d / ("%04d-%s.md" % (oid, slug))
        p.write_text(entry(oid, **kw), encoding="utf-8")
        return p

    def candidates(self, rows):
        (self.obs / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class HeaderTest(unittest.TestCase):
    def test_plain_quoted_and_colon_values(self):
        meta = ob.parse_header('---\nid: 7\ntitle: Hello: world\narea: "a b: c"\nresolution: "line \\"q\\""\n---\nbody')
        self.assertEqual((meta["id"], meta["title"], meta["area"], meta["resolution"]), ("7", "Hello: world", "a b: c", 'line "q"'))

    def test_lists_and_empty_fields_do_not_leak_in(self):
        meta = ob.parse_header("---\nskill:\n  - a\n  - b\nproposes_skill: []\nparked_until:\nstatus: open\n---\n")
        self.assertEqual((meta["status"], meta["parked_until"], meta["proposes_skill"], meta["skill"]), ("open", "", "[]", ""))
        self.assertNotIn("- a", json.dumps(meta))

    def test_no_or_unclosed_header_is_none(self):
        for text in ("", "no header", "---\nid: 1\nnever closed", "\n---\nid: 1\n---\n"):
            self.assertIsNone(ob.parse_header(text), text)


class ScanTest(Base):
    def test_lists_headers_only_oldest_first(self):
        self.put(3, status="open")
        self.put(1, status="parked")
        rows = ob.scan(self.obs)
        self.assertEqual([(r["id"], r["status"]) for r in rows], [(1, "parked"), (3, "open")])
        self.assertEqual(rows[0]["area"], "ui")

    def test_archive_only_when_asked(self):
        self.put(1)
        self.put(2, archive=True, status="actioned", resolved="2026-01-01")
        self.assertEqual([r["id"] for r in ob.scan(self.obs)], [1])
        self.assertEqual([r["id"] for r in ob.scan(self.obs, include_archive=True)], [1, 2])

    def test_empty_or_missing_log_is_simply_empty(self):
        self.assertEqual(ob.scan(self.obs), [])
        shutil.rmtree(str(self.log))
        self.assertEqual(ob.scan(self.obs), [])

    def test_files_that_parse_to_nothing_are_a_broken_scan_not_an_empty_log(self):
        (self.log / "0001-x.md").write_text("no header here\n", encoding="utf-8")
        (self.log / "0002-y.md").write_text("also none\n", encoding="utf-8")
        with self.assertRaises(ob.ScanBroken):
            ob.scan(self.obs)

    def test_one_bad_file_among_good_ones_is_skipped(self):
        self.put(1)
        (self.log / "0002-y.md").write_text("no header\n", encoding="utf-8")
        self.assertEqual([r["id"] for r in ob.scan(self.obs)], [1])

    def test_the_id_falls_back_to_the_file_name(self):
        (self.log / "0042-z.md").write_text("---\ntitle: t\nstatus: open\n---\n", encoding="utf-8")
        self.assertEqual(ob.scan(self.obs)[0]["id"], 42)

    def test_status_filter(self):
        self.put(1, status="open")
        self.put(2, status="parked")
        self.assertEqual([r["id"] for r in ob.list_observations(self.obs, "parked")], [2])
        self.assertEqual(len(ob.list_observations(self.obs)), 2)


class GetTest(Base):
    def test_finds_in_the_log_then_the_archive_and_returns_the_body(self):
        self.put(1)
        self.put(2, archive=True, status="actioned", resolved="2026-01-01")
        self.assertIn("body of 1", ob.get(self.obs, 1)["body"])
        g = ob.get(self.obs, "2")
        self.assertTrue(g["archived"])
        self.assertEqual(g["status"], "actioned")

    def test_unknown_or_malformed_ids(self):
        self.put(1)
        for bad in (99, "x", None, ""):
            with self.assertRaises(ob.ObservationError):
                ob.get(self.obs, bad)


class ResolveTest(Base):
    def test_actioning_sets_status_date_and_resolution_and_touches_nothing_else(self):
        p = self.put(1)
        before = p.read_text(encoding="utf-8").split("\n")
        r = ob.resolve(self.obs, 1, "actioned", 'Fixed: "steer" queue, see DEVLOG', now=NOW)
        self.assertEqual((r["status"], r["resolved"]), ("actioned", day()))
        after = p.read_text(encoding="utf-8").split("\n")
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(sorted(k.split(":")[0] for k, _ in changed), ["resolution", "resolved", "status"])
        self.assertEqual(len(before), len(after))
        self.assertEqual(ob.parse_header("\n".join(after))["resolution"], 'Fixed: "steer" queue, see DEVLOG')
        self.assertIn("body of 1", p.read_text(encoding="utf-8"))

    def test_a_resolution_is_required(self):
        self.put(1)
        for text in ("", "   ", None):
            with self.assertRaises(ob.ObservationError):
                ob.resolve(self.obs, 1, "declined", text)
        self.assertEqual(ob.scan(self.obs)[0]["status"], "open")

    def test_only_known_targets_and_only_from_an_unresolved_state(self):
        self.put(1)
        for bad in ("open", "closed", "", "wontfix"):
            with self.assertRaises(ob.ObservationError):
                ob.resolve(self.obs, 1, bad, "x")
        ob.resolve(self.obs, 1, "superseded", "replaced by 5", now=NOW)
        with self.assertRaises(ob.ObservationError):
            ob.resolve(self.obs, 1, "actioned", "again")

    def test_parking_needs_a_date_and_can_be_resolved_later(self):
        self.put(1)
        for until in ("", "soon", "2026-9-1"):
            with self.assertRaises(ob.ObservationError):
                ob.resolve(self.obs, 1, "parked", "wait for data", until=until)
        r = ob.resolve(self.obs, 1, "parked", "wait for data", until="2026-10-01", now=NOW)
        self.assertEqual((r["status"], r["parked_until"], r["resolved"]), ("parked", "2026-10-01", ""))
        r = ob.resolve(self.obs, 1, "actioned", "done after all", now=NOW)
        self.assertEqual((r["status"], r["parked_until"]), ("actioned", ""))

    def test_a_header_missing_the_fields_gets_them_added(self):
        (self.log / "0001-a.md").write_text("---\nid: 1\ntitle: t\nstatus: open\n---\n\nbody\n", encoding="utf-8")
        ob.resolve(self.obs, 1, "declined", "not a bug", now=NOW)
        meta = ob.parse_header((self.log / "0001-a.md").read_text(encoding="utf-8"))
        self.assertEqual((meta["status"], meta["resolved"], meta["resolution"]), ("declined", day(), "not a bug"))


class ArchiveTest(Base):
    def test_resolved_before_today_moves_but_resolved_today_stays(self):
        self.put(1, status="actioned", resolved=day(-1))
        self.put(2, status="declined", resolved=day())
        self.put(3, status="superseded", resolved=day(-30))
        moved = ob.archive_resolved(self.obs, NOW)
        self.assertEqual(sorted(moved), ["0001-x.md", "0003-x.md"])
        self.assertTrue((self.log / "archive" / "0001-x.md").exists())
        self.assertTrue((self.log / "0002-x.md").exists())

    def test_open_and_parked_never_move(self):
        self.put(1, status="open", resolved=day(-9))
        self.put(2, status="parked", resolved=day(-9))
        self.assertEqual(ob.archive_resolved(self.obs, NOW), [])

    def test_a_resolved_file_without_a_date_gets_today_and_waits(self):
        p = self.put(1, status="actioned", resolved="")
        self.assertEqual(ob.archive_resolved(self.obs, NOW), [])
        self.assertEqual(ob.parse_header(p.read_text(encoding="utf-8"))["resolved"], day())
        self.assertEqual(ob.archive_resolved(self.obs, NOW + 2 * DAY), ["0001-x.md"])

    def test_idempotent_and_safe_on_a_missing_log(self):
        self.put(1, status="actioned", resolved=day(-1))
        ob.archive_resolved(self.obs, NOW)
        self.assertEqual(ob.archive_resolved(self.obs, NOW), [])
        self.assertEqual(ob.archive_resolved(self.obs / "nope", NOW), [])

    def test_adding_sweeps_first_and_numbers_continue_past_the_archive(self):
        self.put(5, status="actioned", resolved=day(-1))
        (self.log / "archive").mkdir(exist_ok=True)
        (self.log / "archive" / ".id-floor").write_text("9\n", encoding="utf-8")
        new = ob.add(self.obs, "Fresh", "body")
        self.assertEqual(new.name[:4], "0010")
        self.assertTrue((self.log / "archive" / "0005-x.md").exists())
        self.assertFalse((self.log / "0005-x.md").exists())

    def test_the_flood_limit_passes_through(self):
        for i in range(3):
            ob.add(self.obs, "n%d" % i, "b", recent_limit=3)
        with self.assertRaises(evolution.TooManyObservations):
            ob.add(self.obs, "one more", "b", recent_limit=3)


class ReviewTest(Base):
    def rows(self, *specs):
        return [{"ts": "t", "epoch": e, "sid": "s", "provider": "agy", "signal": sig,
                 "detail": {"user": u}} for e, sig, u in specs]

    def test_last_review_defaults_to_never(self):
        self.assertEqual(ob.last_review(self.obs), "never")
        (self.obs / "last-review-date.txt").write_text("2026-09-16\n", encoding="utf-8")
        self.assertEqual(ob.last_review(self.obs), "2026-09-16")
        (self.obs / "last-review-date.txt").write_text("", encoding="utf-8")
        self.assertEqual(ob.last_review(self.obs), "never")

    def test_only_candidates_since_the_last_review_day_count(self):
        (self.obs / "last-review-date.txt").write_text(day(-1) + "\n", encoding="utf-8")
        old = NOW - 3 * DAY
        self.candidates(self.rows((old, "stopped", "old"), (NOW - 0.5 * DAY, "correction", "mid"), (NOW, "stopped", "new")))
        self.assertEqual([c["detail"]["user"] for c in ob.unreviewed_candidates(self.obs)], ["mid", "new"])

    def test_with_no_review_yet_every_candidate_counts(self):
        self.candidates(self.rows((1.0, "stopped", "a"), (2.0, "correction", "b")))
        self.assertEqual(len(ob.unreviewed_candidates(self.obs)), 2)

    def test_broken_candidate_lines_are_skipped(self):
        (self.obs / "candidates.jsonl").write_text('not json\n{"epoch": "x"}\n[]\n{"epoch": 5, "signal": "stopped"}\n', encoding="utf-8")
        self.assertEqual(len(ob.unreviewed_candidates(self.obs)), 1)

    def test_digest_lists_what_a_review_looks_at(self):
        self.put(1, title="Open one", status="open")
        self.put(2, title="Parked one", status="parked")
        self.put(3, title="Done", status="actioned", resolved=day(-2))
        self.candidates(self.rows(*[(100.0 + i, "correction" if i % 2 else "stopped", "u%d" % i) for i in range(14)]))
        d = ob.digest(self.obs, NOW)
        self.assertEqual([o["id"] for o in d["open"]], [1])
        self.assertEqual([o["id"] for o in d["parked"]], [2])
        self.assertEqual((d["unreviewed_candidates"], d["candidates_by_signal"]), (14, {"stopped": 7, "correction": 7}))
        self.assertEqual(len(d["recent_candidates"]), 10)
        self.assertEqual(d["recent_candidates"][-1]["user"], "u13")
        self.assertEqual(d["last_review"], "never")
        self.assertTrue((self.log / "archive" / "0003-x.md").exists(), "a review sweeps the resolved ones away")

    def test_a_digest_reference_is_usable_as_ticket_evidence(self):
        data = Path(tempfile.mkdtemp()).resolve()
        obs = data / "workspace" / "skill-observations"
        obs.mkdir(parents=True)
        (obs / "candidates.jsonl").write_text(json.dumps({"epoch": 1789908287.39, "signal": "correction", "detail": {"user": "왜 안돼?"}}) + "\n",
                                              encoding="utf-8")
        ref = ob.digest(obs, NOW)["recent_candidates"][0]["ref"]
        tickets.verify_evidence(data, ref)  # the digest hands out exactly what a ticket accepts

    def test_marking_a_review_needs_a_summary_and_leaves_a_history_line(self):
        for bad in ("", "  ", None):
            with self.assertRaises(ob.ObservationError):
                ob.mark_reviewed(self.obs, bad, now=NOW)
        self.assertEqual(ob.last_review(self.obs), "never")
        self.assertEqual(ob.mark_reviewed(self.obs, "went through 3 open, declined 1, ticketed 1", now=NOW), day())
        self.assertEqual(ob.last_review(self.obs), day())
        self.assertEqual((self.obs / "review-history.log").read_text(encoding="utf-8"),
                         "%s went through 3 open, declined 1, ticketed 1\n" % day())

    def test_after_a_review_older_candidates_no_longer_count(self):
        self.candidates(self.rows((NOW - 5 * DAY, "stopped", "old")))
        ob.mark_reviewed(self.obs, "reviewed", now=NOW)
        self.assertEqual(ob.digest(self.obs, NOW)["unreviewed_candidates"], 0)

    def test_a_review_covers_the_candidates_before_it_even_on_the_same_day(self):
        before, after = NOW - 3600, NOW + 3600
        self.candidates(self.rows((before, "stopped", "earlier today"), (after, "correction", "later today")))
        ob.mark_reviewed(self.obs, "reviewed", now=NOW)
        self.assertEqual([c["detail"]["user"] for c in ob.unreviewed_candidates(self.obs)], ["later today"])

    def test_a_person_editing_the_date_wins_over_a_stale_review_time(self):
        self.candidates(self.rows((NOW - 5 * DAY, "stopped", "old"), (NOW - 1.5 * DAY, "correction", "mid")))
        ob.mark_reviewed(self.obs, "reviewed", now=NOW)
        (self.obs / "last-review-date.txt").write_text(day(-2) + "\n", encoding="utf-8")  # reset to an earlier day
        self.assertEqual([c["detail"]["user"] for c in ob.unreviewed_candidates(self.obs)], ["mid"])

    def test_a_garbled_review_time_falls_back_to_the_day(self):
        self.candidates(self.rows((NOW - 3600, "stopped", "same day")))
        ob.mark_reviewed(self.obs, "reviewed", now=NOW)
        (self.obs / "last-review-epoch.txt").write_text("garbage\n", encoding="utf-8")
        self.assertEqual(len(ob.unreviewed_candidates(self.obs)), 1)  # the start of that day

    def test_marking_needs_an_observation_directory(self):
        with self.assertRaises(ob.ObservationError):
            ob.mark_reviewed(self.obs / "nope", "x", now=NOW)


class RealDataShapeTest(unittest.TestCase):
    """The observation files this instance already has (copied, never touched)."""

    def test_every_real_file_parses(self):
        src = CODE / "data" / "workspace" / "skill-observations"
        if not (src / "observation-log").is_dir():
            self.skipTest("no observation data in this tree")
        tmp = Path(tempfile.mkdtemp()) / "skill-observations"
        shutil.copytree(str(src), str(tmp))
        files = [f for f in (tmp / "observation-log").rglob("*.md")]
        rows = ob.scan(tmp, include_archive=True)
        self.assertEqual(len(rows), len(files))
        self.assertTrue(all(r["status"] in ob.STATES for r in rows))
        self.assertTrue(all(r["title"] for r in rows))
        self.assertEqual(len({r["id"] for r in rows}), len(rows), "ids are unique")


class DisciplineTest(unittest.TestCase):
    SOURCE = (CODE / "observations.py").read_text(encoding="utf-8")

    def test_only_the_standard_library_and_the_core_module(self):
        imported = set()
        for node in ast.walk(ast.parse(self.SOURCE)):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "evolution", "json", "os", "pathlib", "re", "time", "typing"})

    def test_no_trace_of_the_tool_this_replaces_and_no_tool_server_name(self):
        low = self.SOURCE.lower()
        for word in ("task-observer", "task_observer", "taskobserver", "nas_mcp", "hermes"):
            self.assertNotIn(word, low)


if __name__ == "__main__":
    unittest.main()
