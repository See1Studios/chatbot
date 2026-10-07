"""After the host restarts, the agent is told once per session on its next turn: when, which HEAD, what landed.
Run: engine/run-tests.sh test_restart_notice
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATBOT_EVENTS_DIR", tempfile.mkdtemp())   # never the live event mailbox (evt/B)
from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import server  # noqa: E402
import session as S  # noqa: E402
from tests.test_conversation_sync import Base as SyncBase  # noqa: E402

NEW = "b" * 40
OLD = "a" * 40


def fake_git(log_lines=()):
    def git(*args):
        if args[0] == "rev-parse":
            return NEW
        if args[0] == "log":
            n = int(args[args.index("-n") + 1])
            return "\n".join(list(log_lines)[:n])
        return ""
    return git


class BootCase(unittest.TestCase):
    def setUp(self):
        self._info = dict(server.BOOT_INFO)
        self._hook = S.boot_notice
        self.state = Path(tempfile.mkdtemp()) / "last_boot.json"

    def tearDown(self):
        server.BOOT_INFO.clear()
        server.BOOT_INFO.update(self._info)
        S.boot_notice = self._hook

    def boot(self, old=None, log_lines=()):
        if old is not None:
            self.state.write_text(json.dumps({"ts": 1.0, "head": old}), encoding="utf-8")
        with mock.patch.object(server, "_git", fake_git(log_lines)):
            return server._record_boot(self.state)


class Landed(BootCase):
    def test_same_head_lands_nothing(self):
        self.assertEqual(self.boot(old=NEW, log_lines=["x"])["landed"], [])

    def test_missing_previous_state_lands_nothing(self):
        info = self.boot(log_lines=["x"])
        self.assertEqual((info["head"], info["landed"]), (NEW, []))

    def test_commits_between_boots_are_capped(self):
        subjects = ["commit %d" % i for i in range(15)]
        self.assertEqual(self.boot(old=OLD, log_lines=subjects)["landed"], subjects[:server.LANDED_MAX])

    def test_this_boot_is_remembered_for_the_next(self):
        self.boot(old=OLD)
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8"))["head"], NEW)

    def test_git_failure_degrades_to_empty(self):
        self.state.write_text(json.dumps({"head": OLD}), encoding="utf-8")
        with mock.patch.object(server.subprocess, "run", side_effect=OSError("no git")):
            info = server._record_boot(self.state)
        self.assertEqual((info["head"], info["landed"]), ("", []))
        self.assertTrue(info["boot_ts"])

    def test_unreadable_state_file_does_not_block_boot(self):
        self.state.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.boot(log_lines=["x"])["landed"], [])


class FirstTurnOnly(SyncBase):
    def setUp(self):
        super().setUp()
        self._info = dict(server.BOOT_INFO)
        self._hook = S.boot_notice
        with mock.patch.object(server, "_git", fake_git(["fix one", "add two"])):
            server._record_boot(Path(tempfile.mkdtemp()) / "last_boot.json")
        server.BOOT_INFO["landed"] = ["fix one", "add two"]

    def tearDown(self):
        server.BOOT_INFO.clear()
        server.BOOT_INFO.update(self._info)
        S.boot_notice = self._hook
        super().tearDown()

    def test_the_notice_goes_with_the_first_turn_only(self):
        s = self.make()
        s._send_direct("첫 메시지")
        s._send_direct("두 번째")
        first, second = self.sent[-2], self.sent[-1]
        self.assertIn("[Host note] The host restarted", first)
        self.assertIn("(HEAD %s). Landed: fix one · add two" % NEW[:7], first)
        self.assertNotIn("The host restarted at", second)

    def test_no_landed_commits_says_so(self):
        server.BOOT_INFO["landed"] = []
        s = self.make()
        s._send_direct("안녕")
        self.assertIn("Landed: no new commits", self.sent[-1])

    def test_a_host_notice_turn_does_not_use_it_up(self):
        s = self.make()
        s._send_direct("loop note", notice=True)
        self.assertNotIn("The host restarted at", self.sent[-1])
        s._send_direct("사용자 메시지")
        self.assertIn("The host restarted at", self.sent[-1])

    def test_no_boot_info_no_notice(self):
        server.BOOT_INFO["boot_ts"] = 0
        s = self.make()
        s._send_direct("안녕")
        self.assertNotIn("The host restarted at", self.sent[-1])


if __name__ == "__main__":
    unittest.main()
