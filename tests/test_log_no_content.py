"""The global log carries host metadata, never conversation content (LOG_PATH_v1, 2026-09-28).

logs/events.jsonl is what an operator pastes into an issue and what an agent reads as ticket
evidence, so it is deliberately wider than one person's eyes. A private session is "must not be
seen" data, so the words of a turn stay in the session's own log (data/sessions/<sid>/events.jsonl,
user data, encrypted in the shipped build) and only metadata cross over: event, sid,
provider/model, outcome, durations, error class and counts.

The test drives a real AgentSession turn in private mode and holds the negative against two proven
positives, so a pass cannot be vacuous: the turn really did reach the global stream, and the same
words really are on the path (the session log has them).

Run: engine/run-tests.sh test_log_no_content
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
sys.path.insert(0, str(ENGINE))
import host_config  # noqa: E402
from telemetry import logdigest  # noqa: E402
from telemetry import obslog  # noqa: E402
import session  # noqa: E402
from tests._platform import dev_only_bash  # noqa: E402

# Sentinels that must not survive into the global stream. They are not Korean prose and not secrets:
# they are canaries, so a false pass cannot come from the redactor.
USER_WORD = "canary-user-4f1c9d"
REPLY_WORD = "canary-reply-7ab302"
CTL = ENGINE / "chatbot-ctl.sh"


class GlobalLogHasNoTurnText(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        (self.tmp / "sessions").mkdir()
        self.stream = self.tmp / "logs" / "events.jsonl"
        self._orig = {k: getattr(session, k) for k in ("SESSIONS", "ROOT", "DATA")}
        session.SESSIONS = self.tmp / "sessions"
        session.ROOT = ENGINE
        session.DATA = self.tmp
        self._summary = session.AgentSession.get_handover_summary
        session.AgentSession.get_handover_summary = lambda self, *a, **k: ""
        self._obs_state = {k: obslog._state[k] for k in ("src", "path", "mirror")}
        obslog.configure("chat", path=self.stream)

    def tearDown(self):
        obslog._state.update(self._obs_state)
        for k, v in self._orig.items():
            setattr(session, k, v)
        session.AgentSession.get_handover_summary = self._summary

    def private_turn(self):
        """One real private-mode turn: the user speaks, the agent answers. No child process."""
        sess = session.AgentSession("log-guard", provider="claude")
        sess.mode = "private"  # the sensitive case: its own conversation, rules and memory
        # A real session creates its folder on the first save_meta(); _append_log_event swallows
        # the error when it is missing, which would make every check below vacuous.
        sess.meta_path.parent.mkdir(parents=True, exist_ok=True)
        q = queue.Queue()
        with sess.lock:
            sess.subscribers.append(q)
        while True:  # drop the startup lines the constructor emitted
            try:
                q.get_nowait()
            except queue.Empty:
                break
        ask = "기억해 " + USER_WORD
        sess.history.append({"role": "user", "text": ask, "ts": 1000.0})
        sess.busy = True
        sess._emit({"event": "user_ack", "text": ask, "ts": 1000.0})
        sess._handle_events([{"event": "result", "text": "알겠어 " + REPLY_WORD}])
        return sess

    def stream_events(self):
        raw = self.stream.read_text(encoding="utf-8")
        return raw, [json.loads(line) for line in raw.splitlines() if line.strip()]

    def test_a_private_turn_logs_metadata_but_not_its_words(self):
        sess = self.private_turn()
        raw, events = self.stream_events()

        # Control 1: the turn reached the global stream. Without this the assertions below would
        # pass just because nothing was written.
        ends = [e for e in events if e["evt"] == "turn.end"]
        self.assertTrue(ends, "the turn did not reach the global stream: %r" % [e["evt"] for e in events])
        self.assertEqual((ends[0]["sid"], ends[0]["outcome"]), (sess.sid, "result"))

        # Control 2: the same words are on the path -- they are in the session's own log.
        own = (self.tmp / "sessions" / sess.sid / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn(USER_WORD, own, "the user text never reached the session log: the check below is vacuous")
        self.assertIn(REPLY_WORD, own, "the reply never reached the session log: the check below is vacuous")

        # The contract: neither the question nor the answer is anywhere in the global stream.
        self.assertNotIn(USER_WORD, raw)
        self.assertNotIn(REPLY_WORD, raw)

    def test_no_record_of_that_turn_carries_a_text_field(self):
        """Belt and braces: not just the canaries, but no conversation field at all."""
        sess = self.private_turn()
        _, events = self.stream_events()
        mine = [e for e in events if e.get("sid") == sess.sid]
        self.assertTrue(mine, "the turn wrote nothing, so this asserts nothing")
        for evt in mine:
            self.assertNotIn("text", evt, "a global record carries conversation text: %r" % evt)
            self.assertNotIn("user", evt, "a global record carries the user's words: %r" % evt)


class ToolArgumentsHaveNoWords(unittest.TestCase):
    """tl/E (2026-10-09): mcp.call logged every argument up to 300 characters -- a memory line, a search, a dialog
    line between characters, a delegated instruction. A tool's words are content; the log keeps their size only."""

    WORDS = "고양이를 무서워하는 비밀 PRIVATE-FACT-7731"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.stream = self.tmp / "logs" / "events.jsonl"
        obslog.configure("test", path=self.stream, mirror="error")
        import mcp_server
        self.mcp = mcp_server
        self.saved = (mcp_server.DATA, mcp_server._live_scope)
        mcp_server.DATA = self.tmp
        # the caller's scope comes from the live server's busy sessions; a test never asks the live host (#855)
        mcp_server._live_scope = lambda grant, caller=None: (False, False)

    def tearDown(self):
        self.mcp.DATA, self.mcp._live_scope = self.saved
        obslog._state["path"] = None
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_a_memory_line_and_a_search_reach_the_log_as_sizes(self):
        self.mcp._obs_tool_call("memory", {"action": "add", "text": self.WORDS, "section": "User"})
        self.mcp._obs_tool_call("memory", {"action": "search", "query": self.WORDS})
        text = self.stream.read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE-FACT-7731", text)
        calls = [json.loads(l) for l in text.splitlines() if '"mcp.call"' in l]
        self.assertEqual(calls[0]["args"]["text"], {"chars": len(self.WORDS)})
        self.assertEqual((calls[0]["args"]["action"], calls[0]["result"]["status"]), ("add", "added"))
        self.assertEqual(calls[1]["result"], {"hits": 1})              # what came back, as a count

    def test_the_metadata_rule(self):
        got = obslog.arg_meta({"action": "send", "id": 7, "text": "hello", "cmd": "git log --grep secret",
                               "paths": ["engine/a.py"], "tasks": [{"x": 1}, {"y": 2}], "opts": {"a": 1}})
        self.assertEqual(got, {"action": "send", "id": 7, "text": {"chars": 5}, "cmd": "git",
                               "paths": ["engine/a.py"], "tasks": {"items": 2}, "opts": {"keys": 1}})


class OneResolver(unittest.TestCase):
    """obslog, logdigest and chatbot-ctl.sh must not each hold their own idea of where logs live."""

    def test_the_python_side_agrees(self):
        self.assertEqual(obslog.DEFAULT_PATH, host_config.EVENTS_LOG)
        self.assertEqual(logdigest.LOG, host_config.EVENTS_LOG)
        self.assertEqual(host_config.EVENTS_LOG.parent, host_config.LOG_DIR)

    def test_the_env_override_still_wins(self):
        import os
        old = os.environ.get("CHATBOT_OBSLOG_PATH")
        os.environ["CHATBOT_OBSLOG_PATH"] = "/tmp/pe-elsewhere/events.jsonl"
        try:
            import importlib
            cfg = importlib.reload(host_config)
            self.assertEqual(str(cfg.EVENTS_LOG), str(Path("/tmp/pe-elsewhere/events.jsonl")))   # OS spelling (#411)
        finally:
            if old is None:
                os.environ.pop("CHATBOT_OBSLOG_PATH", None)
            else:
                os.environ["CHATBOT_OBSLOG_PATH"] = old
            importlib.reload(host_config)

    @dev_only_bash
    def test_ctl_asks_the_same_resolver(self):
        text = CTL.read_text(encoding="utf-8")
        self.assertIn("import host_config; print(\"%s\\t%s\" % (host_config.LOG_DIR, host_config.EVENTS_LOG))", text,
                      "ctl no longer takes both log names from the resolver")
        self.assertIn("CHATBOT_OBSLOG_PATH:-$EVENTS_LOG", text, "ctl composes the stream path again")
        # A pipe here would kill the script: set -o pipefail turns the closed pipe into exit 141.
        self.assertNotIn('"$_paths" | head', text, "ctl reads the resolver through a pipe")

    @dev_only_bash
    def test_a_copied_ctl_puts_the_log_dir_in_its_data_folder(self):
        """ctl creates the log directory host_config names: the data folder's logs/ (2026-10-09), never a folder of
        the checkout it is run from (CTL_SYMLINK_v1: a stray ~/services/logs appeared once). `status` only reads, and
        the ports point at nothing, so this cannot touch the live host.
        """
        with tempfile.TemporaryDirectory() as d:
            code = Path(d) / "code"
            code.mkdir()
            for name in ("chatbot-ctl.sh", "host_config.py", "protected_paths.json"):
                shutil.copy(str(ENGINE / name), str(code / name))
            (code / "data").mkdir()
            r = subprocess.run(["bash", str(code / "chatbot-ctl.sh"), "status"],
                               capture_output=True, text=True, timeout=30, cwd=str(ENGINE),
                               env={**{k: v for k, v in os.environ.items()
                                       if k not in ("CHATBOT_LOG_DIR", "CHATBOT_OBSLOG_PATH")},
                                    "CHATBOT_PORT": "1", "NAS_MCP_PORT": "1", "CHATBOT_DATA": str(code / "data")})
            self.assertTrue((code / "data" / "logs").is_dir(),
                            "ctl did not create the data folder's log dir: %s %s" % (r.stdout, r.stderr))
            self.assertFalse((code / "logs").exists(), "logs are user data, not the checkout's")


if __name__ == "__main__":
    unittest.main()
