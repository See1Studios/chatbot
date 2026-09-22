"""The status tab's observation summary (workspace_status._observation_summary).
Run: python3 -m unittest tests.test_observation_status  (from services/chatbot)
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import workspace_status as W  # noqa: E402


class ObservationSummaryTest(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        self.obs = self.ws / "skill-observations"
        (self.obs / "observation-log").mkdir(parents=True)
        self._ws = W.WORKSPACE
        W.WORKSPACE = self.ws

    def tearDown(self):
        W.WORKSPACE = self._ws

    def put(self, name, status):
        (self.obs / "observation-log" / name).write_text("---\nid: 1\nstatus: %s\n---\n" % status, encoding="utf-8")

    def test_counts_open_and_total_and_reads_the_real_last_review(self):
        self.put("0001-a.md", "open")
        self.put("0002-b.md", "actioned")
        self.put("0003-c.md", "parked")
        (self.obs / "last-review-date.txt").write_text("2026-09-18\n", encoding="utf-8")
        s = W._observation_summary()
        self.assertEqual((s["open_observations"], s["total_observations"], s["last_review_date"]), (1, 3, "2026-09-18"))

    def test_last_review_is_no_longer_stuck_on_never(self):
        self.assertEqual(W._observation_summary()["last_review_date"], "never")
        (self.obs / "last-review-date.txt").write_text("2026-09-20\n", encoding="utf-8")
        self.assertEqual(W._observation_summary()["last_review_date"], "2026-09-20")

    def test_candidates_since_the_review_are_counted(self):
        (self.obs / "last-review-date.txt").write_text("2026-09-20\n", encoding="utf-8")
        start = time.mktime(time.strptime("2026-09-20", "%Y-%m-%d"))
        rows = [{"epoch": start - 10, "signal": "stopped"}, {"epoch": start + 10, "signal": "correction"}]
        (self.obs / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.assertEqual(W._observation_summary()["unreviewed_candidates"], 1)

    def test_the_summary_survives_a_missing_core_module_and_a_missing_directory(self):
        saved = W.observations
        W.observations = None
        try:
            s = W._observation_summary()
            self.assertEqual((s["unreviewed_candidates"], s["last_review_date"]), (0, "never"))
        finally:
            W.observations = saved
        W.WORKSPACE = self.ws / "nope"
        self.assertEqual(W._observation_summary()["open_observations"], 0)

    def test_the_hooks_note_does_not_claim_a_configured_hook(self):
        src = Path(W.__file__).read_text(encoding="utf-8")
        self.assertNotIn("실제로 설정돼 있음", src)
        self.assertIn("프로바이더 훅을 설정하지 않습니다", src)

    def test_the_status_key_is_the_role_name(self):
        src = (Path(W.__file__)).read_text(encoding="utf-8")
        self.assertIn('"observation": _observation_summary()', src)
        for old in ("task_observer", "task-observer"):
            self.assertNotIn(old, src)


if __name__ == "__main__":
    unittest.main()
