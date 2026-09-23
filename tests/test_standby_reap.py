"""STANDBY_REAP_v1: chatbot-ctl.sh kill_orphan_agy decides from what ctl owns (the process table and
its own pid file), never killing a descendant of the live chat server.
Runs the real heredoc from chatbot-ctl.sh against a fake `ps` table; nothing is killed for real.
Run: python3 -m unittest tests.test_standby_reap  (from services/chatbot)
"""
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import obslog  # noqa: E402

AGY = "/h/.local/bin/agy --input-format stream-json --output-format stream-json --model gemini-3.8-flash-low"


def heredoc():
    src = (ROOT / "chatbot-ctl.sh").read_text(encoding="utf-8")
    body = src.split("kill_orphan_agy() {", 1)[1]
    return re.search(r"<<'PY'\n(.*?)\nPY\n", body, re.S).group(1)


class KillOrphanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.code = Path(self.tmp.name)
        (self.code / "data" / "sessions").mkdir(parents=True)
        (self.code / "logs").mkdir()
        (self.code / "logs" / "chatbot.pid").write_text("100")
        self._state = dict(obslog._state)

    def tearDown(self):
        obslog._state.clear()
        obslog._state.update(self._state)
        self.tmp.cleanup()

    def run_with(self, table):
        killed = []
        real_out, real_kill, real_argv = subprocess.check_output, os.kill, sys.argv
        subprocess.check_output = lambda *a, **k: table
        os.kill = lambda pid, sig: killed.append(pid)
        sys.argv = ["-", str(self.code / "data" / "sessions")]
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                exec(compile(heredoc(), "kill_orphan_agy", "exec"), {"__name__": "__main__"})
        finally:
            subprocess.check_output, os.kill, sys.argv = real_out, real_kill, real_argv
        return sorted(killed)

    TABLE = "\n".join([
        "100 1 500 python3 /x/services/chatbot/server.py",
        "200 100 280 %s --conversation standby-cid" % AGY,          # warm standby: not in live_pids.json
        "300 1 400 %s --conversation old-cid" % AGY,                # orphan of a dead server
        "400 100 50 /h/.local/bin/codex exec --json x",             # codex wrapper...
        "401 400 50 /h/node_modules/@openai/codex/bin/codex exec --json x",  # ...and its native child
        "500 999 300 %s --conversation term-cid" % AGY,             # someone else's, not the server's
        "999 1 900 bash",
    ]) + "\n"

    def test_the_live_servers_descendants_are_left_alone(self):
        killed = self.run_with(self.TABLE)
        self.assertNotIn(200, killed)       # the standby that used to die every doctor run
        self.assertNotIn(400, killed)
        self.assertNotIn(401, killed)       # grandchild counts too
        self.assertIn(300, killed)          # a real orphan is still reaped
        self.assertIn(500, killed)          # unchanged rule for processes outside the server

    def test_a_stale_pid_file_protects_nothing(self):
        (self.code / "logs" / "chatbot.pid").write_text("999")   # not server.py: not trusted
        self.assertIn(200, self.run_with(self.TABLE))


if __name__ == "__main__":
    unittest.main()
