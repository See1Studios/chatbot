"""tl/B (docs/plans/telemetry.md): the event log's history is archived, not overwritten -- gzip, KEEP_DAYS, a size
cap -- and the digest reads the archive for a long window.
Run: engine/run-tests.sh test_telemetry_archive
"""
import gzip
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
from telemetry import archive, logdigest, obslog  # noqa: E402
import platform_compat  # noqa: E402


class Archive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "events.jsonl"
        obslog.configure("test", path=self.log, mirror="error")
        obslog._dedup.clear()
        obslog._fp_state.clear()

    def tearDown(self):
        obslog._state["path"] = None
        obslog._state.pop("archived_at", None)
        self.tmp.cleanup()

    def all_lines(self):
        out = []
        for p in archive.files(self.log) + sorted(self.log.parent.glob("events.jsonl*")):
            opener = gzip.open if p.name.endswith(".gz") else open
            with opener(p, "rt", encoding="utf-8") as f:
                out += [json.loads(l) for l in f if l.strip()]
        return out

    def test_rotation_keeps_every_line(self):
        # before tl/B the file falling off the last backup was overwritten
        with mock.patch.object(obslog, "MAX_BYTES", 400), mock.patch.object(obslog, "BACKUPS", 1):
            for i in range(40):
                obslog.event("unit.line", n=i)
        self.assertGreater(len(archive.files(self.log)), 1)
        self.assertEqual(sorted(r["n"] for r in self.all_lines() if r["evt"] == "unit.line"), list(range(40)))

    def test_maintain_compresses_and_keeps_the_time_of_the_last_line(self):
        d = archive.dir_for(self.log)
        d.mkdir()
        p = d / "events-20261001-120000.jsonl"
        p.write_text('{"evt": "x"}\n', encoding="utf-8")
        os.utime(str(p), (1_790_000_000, 1_790_000_000))
        got = archive.maintain(self.log, now=1_790_000_100)
        self.assertEqual(got["compressed"], 1)
        gz = d / "events-20261001-120000.jsonl.gz"
        self.assertFalse(p.exists())
        self.assertEqual(int(gz.stat().st_mtime), 1_790_000_000)
        with gzip.open(gz, "rt", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"evt": "x"}\n')

    def test_old_and_oversize_files_are_pruned_oldest_first(self):
        d = archive.dir_for(self.log)
        d.mkdir()
        now = 1_800_000_000
        for i, age_days in enumerate((120, 30, 20, 10)):
            p = d / ("events-2026010%d-000000.jsonl.gz" % i)
            p.write_bytes(b"x" * 100)
            t = now - age_days * 86400
            os.utime(str(p), (t, t))
        with mock.patch.object(archive, "MAX_BYTES", 250):
            got = archive.maintain(self.log, now=now)
        self.assertEqual(got["pruned"], 2)                  # 120 days by age, then the oldest by size
        self.assertEqual([p.name for p in archive.files(self.log)],
                         ["events-20260102-000000.jsonl.gz", "events-20260103-000000.jsonl.gz"])

    def test_one_maintainer_at_a_time(self):
        d = archive.dir_for(self.log)
        d.mkdir()
        with open(d / ".lock", "a", encoding="utf-8", newline="\n") as held:
            self.assertTrue(platform_compat.lock_file(held, blocking=False))
            self.assertEqual(archive.maintain(self.log), {"busy": True})
            platform_compat.unlock_file(held)

    def test_the_background_tick_runs_hourly_and_logs_what_changed(self):
        d = archive.dir_for(self.log)
        d.mkdir()
        (d / "events-20261001-120000.jsonl").write_text('{"evt": "x"}\n', encoding="utf-8")
        got = obslog.archive_tick(now=time.time())
        self.assertEqual(got["compressed"], 1)
        self.assertIsNone(obslog.archive_tick(now=time.time() + 60))          # not again within the hour
        self.assertIn("log.archive", [r["evt"] for r in self.all_lines()])

    def test_the_digest_reads_the_archive(self):
        d = archive.dir_for(self.log)
        d.mkdir()
        old = time.time() - 20 * 86400
        rec = {"ts": obslog.iso_now(old), "lvl": "info", "src": "chat", "evt": "unit.archived", "pid": 1}
        gz = d / "events-20260920-000000.jsonl.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        os.utime(str(gz), (old, old))
        saved = logdigest.LOG
        logdigest.LOG = self.log
        try:
            evts = [e.get("evt") for e in logdigest.read_events(time.time() - 30 * 86400)]
            self.assertIn("unit.archived", evts)
            self.assertNotIn("unit.archived", [e.get("evt") for e in logdigest.read_events(time.time() - 86400)])
        finally:
            logdigest.LOG = saved


if __name__ == "__main__":
    unittest.main()
