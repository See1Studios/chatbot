"""PERSONAL_TURN_v1 (docs/plans/private-mode.md §8.3, W1): a work-room turn marked personal stays in the chat but
never becomes work material -- no work tools during it, no observation candidate, nothing recallable from work; and
a private session is never recallable from work at all.
Run: python3 -m unittest tests.test_personal_turn  (from services/chatbot)
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mcp_server as mcp  # noqa: E402
import personal_turn  # noqa: E402
import session  # noqa: E402


def _tmp_sessions(*sids):
    d = Path(tempfile.mkdtemp()).resolve() / "sessions"
    for sid in sids:
        (d / sid).mkdir(parents=True)
    return d


class Marks(unittest.TestCase):
    def test_a_marked_turn_is_found_by_its_user_message_ts(self):
        d = _tmp_sessions("s1")
        self.assertTrue(personal_turn.mark(d, "s1", 1727600000.1234))
        self.assertTrue(personal_turn.is_marked(d, "s1", 1727600000.1234))
        self.assertFalse(personal_turn.is_marked(d, "s1", 1727600001.0))
        self.assertFalse(personal_turn.is_marked(d, "s2", 1727600000.1234))

    def test_nothing_is_written_outside_a_session_folder(self):
        d = _tmp_sessions("s1")
        for sid, turn in (("../s1", 1.0), ("s2", 1.0), ("s1", None), ("", 1.0)):
            self.assertFalse(personal_turn.mark(d, sid, turn), sid)
        self.assertFalse((d / "s1" / personal_turn.FILE).exists())


class ToolsClose(unittest.TestCase):
    def setUp(self):
        self.d = _tmp_sessions("w1")
        p = mock.patch.object(mcp, "DATA", self.d.parent)
        p.start()
        self.addCleanup(p.stop)
        self.busy = [{"id": "w1", "mode": "work", "turn": 1727600000.5}]
        p = mock.patch.object(mcp, "_busy_sessions", lambda: self.busy)
        p.start()
        self.addCleanup(p.stop)

    def test_the_tool_marks_the_running_work_turn(self):
        self.assertEqual(mcp._live_scope("house-memory")[0], False)
        r = mcp.call_tool("personal_turn", {})
        self.assertTrue(r["success"], r)
        self.assertTrue(personal_turn.is_marked(self.d, "w1", 1727600000.5))

    def test_work_tools_close_for_the_rest_of_a_marked_turn_only(self):
        mcp.call_tool("personal_turn", {})
        self.assertEqual(mcp._live_scope("house-memory")[0], True)
        r = mcp.call_tool("memory", {"action": "add", "text": "a personal moment"})
        self.assertFalse(r["success"])
        self.busy[0]["turn"] = 1727600099.0          # the next turn is work again
        self.assertEqual(mcp._live_scope("house-memory")[0], False)

    def test_without_a_running_work_turn_nothing_is_marked(self):
        self.busy[:] = [{"id": "p1", "mode": "private", "turn": 1.0}]
        self.assertFalse(mcp.call_tool("personal_turn", {})["success"])


class NoObservation(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        (self.data / "sessions").mkdir()
        saved = {k: getattr(session, k) for k in ("SESSIONS", "DATA", "_record_live_pids", "evolution")}
        self.addCleanup(lambda: [setattr(session, k, v) for k, v in saved.items()])
        session.SESSIONS = self.data / "sessions"
        session.DATA = self.data
        session._record_live_pids = lambda: None
        self.calls = []
        session.evolution = mock.Mock(on_turn_end=lambda *a: self.calls.append(a))
        self.s = session.AgentSession("w-obs", provider="agy")
        (self.data / "sessions" / "w-obs").mkdir(exist_ok=True)

    def end(self, ts):
        self.s.history.append({"role": "user", "text": "hello", "ts": ts})
        self.s._finish_turn("result")

    def test_a_personal_turn_is_not_an_observation_candidate(self):
        personal_turn.mark(self.data / "sessions", "w-obs", 1727600000.25)
        self.end(1727600000.25)
        self.assertEqual(self.calls, [])

    def test_an_ordinary_turn_still_is(self):
        self.end(1727600000.75)
        self.assertEqual(len(self.calls), 1)


def _load_recall(path):
    spec = importlib.util.spec_from_file_location("recall_%d" % abs(hash(str(path))), path)
    mod = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # no __pycache__ inside the shipped template
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


class Recall(unittest.TestCase):
    """Both copies of the workspace tool (live data and the template new installs get)."""

    def setUp(self):
        self.d = _tmp_sessions("w1", "p1")
        hist = [{"role": "user", "text": "deploy the cache fix", "ts": 1.0},
                {"role": "assistant", "text": "done, cache fixed", "ts": 2.0},
                {"role": "user", "text": "you look lovely today", "ts": 3.0},
                {"role": "assistant", "text": "blushing reply", "ts": 4.0},
                {"role": "user", "text": "back to the cache", "ts": 5.0}]
        (self.d / "w1" / "meta.json").write_text(json.dumps({"id": "w1", "mode": "work", "history": hist}), encoding="utf-8")
        (self.d / "p1" / "meta.json").write_text(json.dumps({"id": "p1", "mode": "private", "history": [
            {"role": "user", "text": "a secret about the cache", "ts": 1.0}]}), encoding="utf-8")
        personal_turn.mark(self.d, "w1", 3.0)

    def check(self, path):
        rm = _load_recall(path)
        rm.SESSIONS_DIR = self.d
        texts = [m["text"] for r in rm.search_sessions(["cache", "lovely", "blushing"]) for m in r["matches"]]
        self.assertIn("deploy the cache fix", texts)
        self.assertIn("back to the cache", texts)
        for hidden in ("you look lovely today", "blushing reply", "a secret about the cache"):
            self.assertNotIn(hidden, texts)
        self.assertEqual([x["session_id"] for x in rm.list_recent_sessions()], ["w1"])
        self.assertIsNone(rm.inspect_session("p1"))

    def test_the_live_tool(self):
        self.check(ROOT / "data" / "workspace" / "tools" / "recall_memory.py")

    def test_the_template_tool(self):
        self.check(ROOT / "templates" / "workspace" / "tools" / "recall_memory.py")


class Wiring(unittest.TestCase):
    def test_every_charter_tells_the_agent_when_to_mark(self):
        for rel in ("data/workspace/AGENTS.md", "templates/workspace/AGENTS.md"):
            self.assertIn("call `personal_turn`", (ROOT / rel).read_text(encoding="utf-8"), rel)

    def test_a_cli_brain_with_a_tool_allowlist_may_call_it(self):
        from providers import adapter_claude
        self.assertIn("mcp__nas__personal_turn", adapter_claude.ClaudeAdapter.ALLOWED_TOOLS)

    def test_the_host_says_which_turn_is_running(self):
        self.assertIn('"turn": personal_turn.running_turn(x.history)', (ROOT / "server.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
