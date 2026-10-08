"""tools/ticket_quick.py (plan pew/K): the repo copy of ticket-quick. It finds the data folder through host_config,
keeps the claim token in a private file so a lost terminal line does not strand the lease, and reads that file when
--token is left out.
Run: engine/run-tests.sh test_ticket_quick
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from tests._paths import ENGINE, REPO  # noqa: E402

ROOT = REPO
TOOL = ENGINE / "tools" / "ticket_quick.py"
DATA_ENV = ("CHATBOT_DATA", "PE_HOME", "PRIVATEENGINE_HOME")

sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "tools"))


class TicketQuickCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.data, self.state = base / "data", base / "state"
        self.data.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in DATA_ENV}
        self.env.update(CHATBOT_DATA=str(self.data), XDG_STATE_HOME=str(self.state))

    def tearDown(self):
        self._tmp.cleanup()

    def run_tq(self, *args):
        # `done` runs the guard tests on the engine checkout (tickets.GUARD_TIMEOUT_SEC): ~40 s alone, and 60 s ran out
        # whenever another suite was running (main.check, 2026-10-08)
        return subprocess.run([sys.executable, str(TOOL)] + list(args), cwd=str(ROOT), env=self.env,
                              capture_output=True, text=True, timeout=360)

    def start(self):
        r = self.run_tq("start", "--title", "[test] probe", "--paths", "a.py", "--actor", "tester")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l and not l.startswith(" "))
        return int(out["TICKET_ID"]), out["CLAIM_TOKEN"], Path(out["TOKEN_FILE"])

    def ticket(self, tid):
        hits = list(self.data.rglob("%04d.json" % tid))
        self.assertEqual(len(hits), 1, "ticket %d not under the CHATBOT_DATA folder" % tid)
        return json.loads(hits[0].read_text(encoding="utf-8"))

    def test_start_writes_under_the_configured_data_folder_and_a_private_token_file(self):
        tid, token, tf = self.start()
        self.assertEqual(self.ticket(tid)["status"], "in_progress")
        self.assertTrue(str(tf).startswith(str(self.state)), tf)
        self.assertEqual(tf.read_text().strip(), token)
        if os.name == "posix":   # mode bits are POSIX; on Windows the state folder is the user's profile (#411)
            self.assertEqual(stat.S_IMODE(tf.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(tf.parent.stat().st_mode), 0o700)

    def test_done_reads_the_token_file_and_removes_it(self):
        tid, _, tf = self.start()
        r = self.run_tq("done", "--id", str(tid), "--actor", "tester")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ticket(tid)["status"], "done")
        self.assertFalse(tf.exists())

    def test_widen_reads_the_token_file_and_adds_the_files(self):
        tid, _, _ = self.start()
        r = self.run_tq("widen", "--id", str(tid), "--paths", "b.py", "--actor", "tester")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ADDED=b.py", r.stdout)
        self.assertEqual(self.ticket(tid)["paths"], ["a.py", "b.py"])

    def test_explicit_token_still_works(self):
        tid, token, tf = self.start()
        r = self.run_tq("fail", "--id", str(tid), "--token", token, "--outcome", "abandoned", "--actor", "tester")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(tf.exists())

    def test_without_token_or_file_it_says_where_the_file_would_be(self):
        tid, _, tf = self.start()
        tf.unlink()
        r = self.run_tq("done", "--id", str(tid), "--actor", "tester")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no claim token", r.stderr)
        self.assertEqual(self.ticket(tid)["status"], "in_progress")

    def test_every_command_is_offered(self):
        r = self.run_tq("--help")
        for cmd in ("start", "claim", "done", "fail", "renew", "widen", "await-merge", "merge-go"):
            self.assertIn(cmd, r.stdout)


class ActorNames(unittest.TestCase):
    def test_known_agents_are_named_from_executables_only(self):
        import ticket_quick as tq
        self.assertEqual(tq._exec_names(["/usr/bin/node", "/opt/x/opencode", "run"]), ["node", "opencode"])
        self.assertIn(tq._ACTOR_EXECS.get("opencode"), ("opencode",))
        self.assertEqual(tq._exec_names(["bash", "-c", "claude do things"]), ["bash", "claude do things"])
        self.assertNotIn("claude do things", tq._ACTOR_EXECS)

    def test_an_unnamed_actor_records_nothing(self):
        # ACTOR_REQUIRED_v1: no --actor and an ancestry that names no agent -> refused before any write
        import ticket_quick as tq
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tq, "DATA_DIR", Path(d)), \
                mock.patch.object(tq, "detect_actor", return_value="unknown-cli"):
            with self.assertRaises(SystemExit) as cm:
                tq.main(["start", "--title", "[test] nobody", "--paths", "a.py"])
            self.assertEqual(cm.exception.code, 2)
            self.assertEqual(list(Path(d).rglob("*")), [])                        # no ticket, no candidate row
        with mock.patch.object(tq, "detect_actor", return_value="unknown-cli"):
            self.assertEqual(tq.named_actor(SimpleNamespace(actor="codex")), "codex")


if __name__ == "__main__":
    unittest.main()
