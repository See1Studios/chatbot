"""SUBAGENT_ACTIVITY_v1: a turn whose subagents are working is not silent. agy prints nothing on the parent's stream
while its subagents run, and agy 1.2.16 no longer logs model calls, so the silent-turn watchdog closed working turns
(2026-10-05: 4 hangs and 8 notices on one session in 40 minutes). Activity is read from the conversation's transcript
and the transcripts of the subagents it started.
Run: engine/run-tests.sh test_silent_subagent
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
from providers import accounts  # noqa: E402
from providers import adapter_agy as A  # noqa: E402

PARENT = "11111111-1111-1111-1111-111111111111"
CHILD = "22222222-2222-2222-2222-222222222222"


class SubagentActivity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = accounts.AGY_LOG_DIR
        accounts.AGY_LOG_DIR = self.tmp / "log"
        (self.tmp / "log").mkdir()

    def tearDown(self):
        accounts.AGY_LOG_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def transcript(self, cid, text, age):
        p = self.tmp / "brain" / cid / ".system_generated" / "logs" / "transcript.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        t = time.time() - age
        os.utime(p, (t, t))
        return t

    def test_a_working_subagent_is_the_parents_activity(self):
        self.transcript(PARENT, '{"content": "Created the following subagents:\\n{\\n  \\"conversationId\\": \\"%s\\"' % CHILD, 200)
        child = self.transcript(CHILD, "{}", 5)
        self.assertAlmostEqual(A.AgyAdapter().last_activity(1, 0, conversation_id=PARENT), child, delta=1)

    def test_a_conversation_with_no_transcript_is_read_from_its_store(self):
        # agy keeps no transcript for some conversations (a worker's, 2026-10-06); its store is written every step
        db = self.tmp / "conversations" / (PARENT + ".db")
        db.parent.mkdir()
        db.write_bytes(b"x")
        t = time.time() - 7
        os.utime(db, (t, t))
        self.assertAlmostEqual(A.AgyAdapter().last_activity(1, 0, conversation_id=PARENT), t, delta=1)

    def test_without_subagents_it_is_the_conversation_itself(self):
        parent = self.transcript(PARENT, "{}", 30)
        self.assertAlmostEqual(A.AgyAdapter().last_activity(1, 0, conversation_id=PARENT), parent, delta=1)

    def test_an_unknown_conversation_falls_back_to_the_process_log(self):
        self.assertIsNone(A.AgyAdapter().last_activity(424242, time.time(), conversation_id="nope"))

    def worker_log(self, text):
        p = self.tmp / "log" / "cli-worker.log"
        p.write_text(text, encoding="utf-8")
        return p

    def test_a_workers_activity_is_the_conversation_its_log_names(self):
        # WORKER_ACTIVITY_v1 (#692): agy 1.2.16 logs no model calls; the probe said "nothing since start" and the stall
        # watch would cut any worker past STALL_SEC
        log = self.worker_log("I1006 00:27:40.254749 1 server.go:1263] Created conversation %s\n" % PARENT)
        self.transcript(PARENT, '"conversationId": "%s"' % CHILD, 300)
        child = self.transcript(CHILD, "{}", 4)
        with mock.patch.object(accounts, "agy_log_for", return_value=log):
            self.assertAlmostEqual(A.AgyAdapter().last_activity(1, time.time() - 900), child, delta=1)

    def test_a_worker_with_no_conversation_yet_is_at_its_start(self):
        log = self.worker_log("I1006 00:27:32 1 printmode.go:202] Print mode: starting\n")
        started = time.time() - 30
        with mock.patch.object(accounts, "agy_log_for", return_value=log):
            self.assertEqual(A.AgyAdapter().last_activity(1, started), started)

    def test_the_stall_watch_lets_a_working_worker_run_past_the_stall_window(self):
        import delegation_watch as W
        code, _out, err = W.run([sys.executable, "-c", "import time; time.sleep(1.2)"], timeout=10,
                                activity=lambda pid, started: time.time(), stall_sec=0.5, poll_sec=0.2)
        self.assertEqual((code, err), (0, ""))

    def test_the_watchdog_asks_with_the_conversation_and_before_its_notice(self):
        src = (ENGINE / "turn_watchdog.py").read_text(encoding="utf-8")
        self.assertIn('conversation_id=str(getattr(self, "conversation_id", "") or "")', src)
        notice = src[src.index("def _silent_notice_fire"):src.index("def _touch_turn_activity")]
        self.assertIn("self._provider_shows_activity()", notice)


if __name__ == "__main__":
    unittest.main()
