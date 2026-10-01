"""inbox/0: a tool call is tied to the session whose agent process made it, from the connection's process ancestry,
never from what the model says; an HTTP brain (the host's own process) names its session in a header.
Run: python3 -m unittest tests.test_tool_caller  (from services/chatbot)
"""
import os
import socket
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CHATBOT_EDITION", "dev")

import platform_compat as pc  # noqa: E402
import session  # noqa: E402
import mcp_server as mcp  # noqa: E402

# A client connected to the test's server port; with "deep" it is a grandchild (an agent's shell running curl).
CLIENT = textwrap.dedent("""
    import socket, subprocess, sys, time
    if sys.argv[2] == "deep":
        sys.exit(subprocess.call([sys.executable, "-c", sys.argv[3], sys.argv[1], "flat", ""]))
    c = socket.create_connection(("127.0.0.1", int(sys.argv[1])))
    print(c.getsockname()[1], flush=True)
    time.sleep(10)
""")


@unittest.skipUnless(pc.has_proc(), "needs a Linux-style /proc")
class CallerSession(unittest.TestCase):
    def setUp(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            for pid in pc.child_pids({p.pid}) - {p.pid}:   # the "deep" client's own child
                pc.terminate(pid)
            p.kill()
            p.wait()
            p.stdout.close()
        self.srv.close()

    def _client(self, how="flat"):
        p = subprocess.Popen([sys.executable, "-c", CLIENT, str(self.port), how, CLIENT], stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p, int(p.stdout.readline())

    def test_the_agent_process_and_its_descendants_are_its_session(self):
        for how in ("flat", "deep"):
            agent, port = self._client(how)
            with mock.patch.object(session, "owned_agent_procs", return_value={agent.pid: {"owner": "session", "sid": "s-agent"}}):
                self.assertEqual(session.caller_session(port, self.port, claimed="s-other")[0], "s-agent", how)

    def test_a_process_no_session_owns_is_nobody(self):
        _, port = self._client()
        with mock.patch.object(session, "owned_agent_procs", return_value={}):
            sid, proc = session.caller_session(port, self.port, claimed="s-other")
        self.assertEqual(sid, "")
        self.assertTrue(proc.startswith("python"), proc)

    def test_only_the_host_itself_may_name_its_session(self):
        cli = socket.create_connection(("127.0.0.1", self.port))
        try:
            port = cli.getsockname()[1]
            with mock.patch.object(session.REG, "peek", side_effect=lambda sid: object() if sid == "s-http" else None):
                self.assertEqual(session.caller_session(port, self.port, claimed="s-http"), ("s-http", "host"))
                self.assertEqual(session.caller_session(port, self.port, claimed="s-gone"), ("", "host"))
        finally:
            cli.close()

    def test_no_connection_is_nobody(self):
        self.assertEqual(session.caller_session(1, self.port), ("", ""))


class Handler:
    client_address = ("127.0.0.1", 40001)
    headers = {"X-Chatbot-Session": "s-http"}


class ToolServerCaller(unittest.TestCase):
    def test_outside_a_call_there_is_no_caller(self):
        self.assertEqual(mcp.caller_session_id(), "")

    def test_the_host_is_asked_once_per_call_with_the_connection(self):
        asked = []

        def host(path):
            asked.append(path)
            return {"id": "s1", "proc": "agy"}
        with mock.patch.object(mcp, "_host_get", side_effect=host):
            got = mcp.mcp_caller.serving(Handler(), "choices", lambda: (mcp.caller_session_id(), mcp.caller_session_id()))
        self.assertEqual(got, ("s1", "s1"))
        self.assertEqual(len(asked), 1)
        self.assertIn("port=40001", asked[0])
        self.assertIn("server=%d" % mcp.PORT, asked[0])
        self.assertIn("claim=s-http", asked[0])
        self.assertEqual(mcp.caller_session_id(), "")

    def test_an_unknown_caller_is_logged_with_its_process(self):
        with mock.patch.object(mcp, "_host_get", return_value={"id": "", "proc": "grok"}), \
                mock.patch.object(mcp.obslog, "event") as ev:
            self.assertEqual(mcp.mcp_caller.serving(Handler(), "choices", mcp.caller_session_id), "")
        ev.assert_called_once_with("mcp.caller_unknown", lvl="warn", tool="choices", proc="grok")

    def test_choices_go_to_the_calling_session_not_the_one_on_screen(self):
        with mock.patch.object(mcp, "_host_get", return_value={"id": "s-caller"}), \
                mock.patch.object(mcp, "_find_live_session", return_value=None), \
                mock.patch.object(mcp.mcp_caller, "screen_session", return_value="s-screen"):
            out = mcp.mcp_caller.serving(Handler(), "choices", lambda: mcp.record_session_choices([{"label": "a"}]))
        self.assertEqual(out["data"]["session_id"], "s-caller")

    def test_older_tools_still_guess_the_screen_when_the_caller_is_unknown(self):
        with mock.patch.object(mcp, "_host_get", side_effect=lambda path: {"id": "s-screen"} if "active" in path else {}):
            self.assertEqual(mcp.mcp_caller.serving(Handler(), "t", lambda: mcp.caller_session_id(guess=True)), "s-screen")
            self.assertEqual(mcp.mcp_caller.serving(Handler(), "t", mcp.caller_session_id), "")


if __name__ == "__main__":
    unittest.main()
