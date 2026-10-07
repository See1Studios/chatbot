"""The 개선 tab's history: every resolved observation, in the log or archived, newest resolution first, in pages
(OBS_HISTORY_v1). Replaces '오늘 처리', which drifted because archiving only happens on the next write.
Run: engine/run-tests.sh test_observation_history
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import workspace_status as W  # noqa: E402


def obs(d, oid, status, date, resolved=""):
    d.mkdir(parents=True, exist_ok=True)
    (d / ("%04d-x.md" % oid)).write_text(
        "---\nid: %d\ntitle: t%d\nstatus: %s\ndate: %s\nresolved: %s\n---\nbody\n" % (oid, oid, status, date, resolved),
        encoding="utf-8")


class History(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        self.root = self.ws / "skill-observations"
        log = self.root / "observation-log"
        obs(log, 1, "open", "2026-09-01")
        obs(log, 2, "parked", "2026-09-01")
        obs(log, 3, "actioned", "2026-09-02", "2026-09-20")                 # resolved, not yet archived
        for i in range(4, 16):                                               # archived
            obs(log / "archive", i, "dismissed" if i % 2 else "actioned", "2026-09-01", "2026-09-%02d" % i)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_log_and_archive_in_one_history_newest_first(self):
        page = W.observation_history(self.root, 1, per=5)
        self.assertEqual((page["total"], page["pages"], page["page"]), (13, 3, 1))
        self.assertEqual([x["id"] for x in page["items"]], [3, 15, 14, 13, 12])
        self.assertEqual([x["id"] for x in W.observation_history(self.root, 3, per=5)["items"]], [6, 5, 4])
        self.assertEqual(W.observation_history(self.root, 99, per=5)["page"], 3)                 # clamped
        self.assertNotIn(1, [x["id"] for p in (1, 2, 3) for x in W.observation_history(self.root, p, per=5)["items"]])

    def test_the_route(self):
        saved = W.WORKSPACE
        W.WORKSPACE = self.ws
        try:
            code, body = W.observation_api("GET", "/api/observations/history/2", None)
            self.assertEqual((code, body["page"], body["total"]), (200, 2, 13))
            self.assertEqual(W.observation_api("GET", "/api/observations/history", None)[1]["page"], 1)
        finally:
            W.WORKSPACE = saved

if __name__ == "__main__":
    unittest.main()
