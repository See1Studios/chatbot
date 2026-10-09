"""PERSONAL_TURN_v1 (docs/plans/private-mode.md §8.3, W1): a work-room turn marked personal stays in the chat but
never becomes work material -- no work tools during it, nothing recallable from work; and
a private session is never recallable from work at all.
Run: engine/run-tests.sh test_personal_turn
"""
import importlib.util
import inspect
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))

import mcp_server as mcp  # noqa: E402
import personal_turn  # noqa: E402
import session  # noqa: E402
from tests.page_source import i18n_prelude  # noqa: E402


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


class MoveChoice(unittest.TestCase):
    """MOVE_CHOICE_v1 (docs/plans/engine-decides.md ed/B2, D3): the engine, not the model, adds the move choice to a
    marked personal turn -- the place from a list, the chips by catalog key, the cool-down kept."""

    def test_unmarked_turns_get_nothing_and_marked_ones_two_chips_by_key(self):
        d = _tmp_sessions("s1")
        self.assertEqual(personal_turn.move_choices(d, "s1", 100.0), [])
        personal_turn.mark(d, "s1", 100.0)
        move, stay = personal_turn.move_choices(d, "s1", 100.0)
        self.assertEqual((move["label_key"], move["kind"]), ("choice.move", "command"))
        self.assertEqual(move["label_vars"], {"place": {"key": "place.stairwell"}})
        self.assertEqual(move["payload"], "/move stairwell")   # PLACE_MOVE_v1: by id
        self.assertTrue(mcp._is_allowed_choice_command(move["payload"]))
        self.assertEqual(stay["label_key"], "choice.back_to_work")
        self.assertEqual(personal_turn.move_choices(d, "s1", 100.0), [], "once per turn")

    def test_the_next_offer_goes_somewhere_else_and_offers_do_not_count_as_marks(self):
        d = _tmp_sessions("s1")
        names = []
        for t in (1.0, 2.0):
            personal_turn.mark(d, "s1", t)
            names.append(personal_turn.move_choices(d, "s1", t)[0]["payload"])
        self.assertEqual(len(set(names)), 2, names)
        personal_turn.mark(d, "s1", 3.0)   # a third mark in the window with no move: the cool-down (W2b) holds
        self.assertEqual(personal_turn.move_choices(d, "s1", 3.0), [])
        personal_turn.moved(d, "s1")
        personal_turn.mark(d, "s1", 4.0)
        self.assertEqual(personal_turn.move_choices(d, "s1", 4.0)[0]["payload"], "/move meeting_room")

    def test_a_characters_own_places_win(self):
        d = _tmp_sessions("s1")
        state = d / "state.json"
        state.write_text(json.dumps({"places": ["신사 뒤뜰"]}), encoding="utf-8")
        personal_turn.mark(d, "s1", 5.0)
        move = personal_turn.move_choices(d, "s1", 5.0, state)[0]
        self.assertEqual((move["label_vars"]["place"], move["payload"]), ("신사 뒤뜰", "/move 신사 뒤뜰"))

    def test_the_answer_gets_them_after_its_own_choices_in_a_work_room_only(self):
        import session_turn
        d = _tmp_sessions("s1")
        personal_turn.mark(d, "s1", 7.0)
        s = type("S", (), {})()
        s.mode, s.sid, s.character = "work", "s1", ""
        s.meta_path = d / "s1" / "meta.json"
        s.history = [{"role": "user", "text": "hi", "ts": 7.0}]
        got = session_turn.SessionTurn.engine_choices(s, ["Yes", "No"])
        self.assertEqual(got[:2], ["Yes", "No"])
        self.assertEqual(got[2]["label_key"], "choice.move")
        s.mode = "private"
        self.assertEqual(session_turn.SessionTurn.engine_choices(s, ["A"]), ["A"])

    def test_the_page_shows_a_chip_label_by_its_key(self):
        page = (ROOT / "static" / "app-messages.js").read_text(encoding="utf-8")
        self.assertIn("x.label_key ? tr(x.label_key, x.label_vars || {}) : x.label", page)
        for lang in ("en", "ko"):
            cat = json.loads((ROOT / "static" / "i18n" / (lang + ".json")).read_text(encoding="utf-8"))
            for p in personal_turn.places():
                self.assertIn("place." + p["id"], cat, lang)


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
        self.check(ROOT / "templates" / "workspace" / "tools" / "recall_memory.py")

    def test_the_template_tool(self):
        self.check(ROOT / "templates" / "workspace" / "tools" / "recall_memory.py")


class PageMark(unittest.TestCase):
    """The page reads a session's marks and shows a line-icon lock on marked bubbles, in the advanced density only."""

    def test_the_route_returns_one_sessions_keys_and_leaves_other_paths(self):
        d = _tmp_sessions("w1")
        personal_turn.mark(d, "w1", 1790682406.3824167)
        self.assertEqual(personal_turn.api("GET", "/api/sessions/w1/personal-turns", None, d),
                         (200, {"turns": ["1790682406.382"]}))
        self.assertEqual(personal_turn.api("GET", "/api/sessions/nope/personal-turns", None, d), (200, {"turns": []}))
        self.assertIsNone(personal_turn.api("GET", "/api/sessions/../x/personal-turns", None, d))
        self.assertIsNone(personal_turn.api("POST", "/api/sessions/w1/personal-turns", None, d))
        self.assertIn('(None, _api(personal_turn.api, "GET")),', (ENGINE / "server.py").read_text(encoding="utf-8"))

    def test_the_lock_is_a_standard_line_icon_hidden_in_the_simple_density(self):
        js = (ROOT / "static" / "app-flow.js").read_text(encoding="utf-8")
        self.assertIn("getActionSvg('lock')", js)
        self.assertIn("lock:", (ROOT / "static" / "app-messages.js").read_text(encoding="utf-8"))
        css = (ROOT / "static" / "chat-log.css").read_text(encoding="utf-8")
        self.assertIn("#log .personal-mark{display:none}", css)
        self.assertIn("body.density-advanced #log > .msg.assistant > .msg-footer > .personal-mark{display:inline-flex", css)
        self.assertIn("body.density-advanced #log > .msg.user > .personal-mark{display:inline-flex", css)

    @unittest.skipUnless(__import__("shutil").which("node"), "node not installed")
    def test_the_lock_goes_on_the_marked_bubble_and_the_replies_footer_until_the_next_user_bubble(self):
        js = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const cut = src.slice(src.indexOf('const PERSONAL_TEXT'), src.indexOf('// CHAT_DENSITY_v1'));
const el = (cls, ts, footer) => {
  const kids = [];
  const n = { classList: { contains: c => cls.includes(c), toggle() {} }, dataset: ts ? { ts } : {}, kids,
              appendChild(k) { kids.push(k); }, querySelector: q => q.includes('msg-footer') ? footer : null };
  return n;
};
const box = () => { const kids = []; return { kids, appendChild(k) { kids.push(k); }, querySelector: () => null }; };
const f1 = box(), f2 = box(), f3 = box();
const nodes = [el(['msg', 'user'], '10.0'), el(['msg', 'assistant'], '11', f1), el(['msg', 'assistant', 'system'], '', box()),
               el(['msg', 'assistant'], '12', f2), el(['msg', 'user'], '20.0'), el(['msg', 'assistant'], '21', f3)];
const env = { sessionId: 's', api: async () => ({ turns: ['10.000'] }), getActionSvg: () => '<svg/>',
              document: { createElement: () => ({ setAttribute() {} }) } };
const mark = new Function(...Object.keys(env), cut + '; return markPersonal;')(...Object.values(env));
mark({ children: nodes }).then(() => console.log(JSON.stringify([nodes[0].kids.length, f1.kids.length, f2.kids.length,
                                                                  nodes[4].kids.length, f3.kids.length])));
"""
        import subprocess
        out = subprocess.run(["node", "-e", i18n_prelude() + js, str(ROOT / "static" / "app-flow.js")], capture_output=True, text=True,
                             encoding="utf-8", timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), [1, 1, 1, 0, 0])

    def test_page_and_host_key_a_turn_the_same_way(self):
        self.assertIn("n.toFixed(3)", (ROOT / "static" / "app-flow.js").read_text(encoding="utf-8"))
        self.assertEqual(personal_turn.key(1790682406.3824167), "1790682406.382")


class Wiring(unittest.TestCase):
    def test_every_charter_tells_the_agent_when_to_mark(self):
        for rel in ("templates/workspace/AGENTS.md",):   # one charter for both builds (DEV_SPLIT_v1)
            self.assertIn("call `personal_turn`", (ROOT / rel).read_text(encoding="utf-8"), rel)

    def test_a_cli_brain_with_a_tool_allowlist_may_call_it(self):
        from providers import adapter_claude
        self.assertIn("mcp__nas__personal_turn", adapter_claude.ClaudeAdapter.ALLOWED_TOOLS)

    def test_the_host_says_which_turn_is_running(self):
        self.assertIn('"turn": personal_turn.running_turn(x.history)', (ENGINE / "route_sessions.py").read_text(encoding="utf-8"))


class Judgment(unittest.TestCase):
    """engine-decides D1: the engine marks a work-room turn as it starts. The classifier is injected; no live model."""

    def setUp(self):
        self._quiet()

    def tearDown(self):
        self._quiet()

    def _quiet(self):
        with personal_turn._lock:
            jobs = list(personal_turn._inflight.values()) + list(personal_turn._pending.values())
            for job in jobs:
                job.applied = True
            personal_turn._inflight.clear()
            personal_turn._pending.clear()
        for job in jobs:
            thread = getattr(job, "thread", None)
            if thread is not None:
                thread.join(timeout=1)

    def _sess(self, d, private=False):
        import session_turn
        s = type("S", (), {})()
        s.is_private = private
        s.sid = "s1"
        s.meta_path = d / "s1" / "meta.json"
        s.history = []

        def _start_turn(text, client_mid, client_context, notice, event_type):
            if not notice:
                s.history.append({"role": "user", "text": text, "ts": 5.0})

        s._start_turn = _start_turn
        s.open = session_turn.SessionTurn._open_turn
        return s

    def test_a_work_room_action_is_personal_without_the_classifier(self):
        d = _tmp_sessions("s1")
        s = self._sess(d)

        def boom(line):
            raise AssertionError("classifier ran: %s" % line)

        with mock.patch.object(personal_turn, "_default_ask", boom):
            s.open(s, "leans in", "", None, False, "action")
        self.assertTrue(personal_turn.is_marked(d, "s1", 5.0))

    def test_a_scene_a_notice_and_a_private_session_are_not_judged(self):
        d = _tmp_sessions("s1")
        s = self._sess(d)

        def boom(line):
            raise AssertionError("classifier ran")

        with mock.patch.object(personal_turn, "_default_ask", boom):
            s.open(s, "rain starts", "", None, False, "scene")
            s.open(s, "leans in", "", None, True, "action")
            priv = self._sess(d, private=True)
            priv.open(priv, "love you", "", None, False, "action")
        self.assertFalse((d / "s1" / personal_turn.FILE).exists())

    def test_personal_marks_and_any_other_word_does_not(self):
        d = _tmp_sessions("s1")
        for word, marked in (("personal", True), ("Personal.", True), ("work", False), ("maybe personal", False), ("", False)):
            sid = "s%d" % abs(hash(word))
            (d / sid).mkdir()
            job = personal_turn.start_judgment(d, sid, "hello", "", ask=lambda line, word=word: word)
            personal_turn.bind_judgment(job, 4.0)
            personal_turn.await_judgment(d, sid, 4.0)
            self.assertEqual(personal_turn.is_marked(d, sid, 4.0), marked, word)

    def test_overtime_stays_work_after_a_late_personal(self):
        d = _tmp_sessions("w1")

        def slow(line):
            time.sleep(0.4)
            return "personal"

        with mock.patch.object(personal_turn, "JUDGE_SEC", 0.05):
            job = personal_turn.start_judgment(d, "w1", "miss you", "", ask=slow)
        personal_turn.bind_judgment(job, 4.0)
        personal_turn.await_judgment(d, "w1", 4.0)
        self.assertFalse(personal_turn.is_marked(d, "w1", 4.0))
        time.sleep(0.5)
        self.assertFalse(personal_turn.is_marked(d, "w1", 4.0))

    def test_the_classifier_sees_one_line_and_the_oneshot_provider(self):
        d = _tmp_sessions("w1")
        seen = {}

        def fake(prompt, timeout):
            seen["prompt"] = prompt
            seen["timeout"] = timeout
            return {"text": "personal"}

        with mock.patch.dict(os.environ, {"CHATBOT_TEST_RUNNER": ""}):
            with mock.patch("session._oneshot", fake):
                job = personal_turn.start_judgment(d, "w1", "사랑해\n어제 일", "")
                personal_turn.bind_judgment(job, 8.0)
                personal_turn.await_judgment(d, "w1", 8.0)
        self.assertEqual(seen["prompt"], personal_turn._PROMPT % "사랑해 어제 일")
        self.assertEqual(seen["timeout"], personal_turn.JUDGE_SEC)
        self.assertTrue(personal_turn.is_marked(d, "w1", 8.0))

    def test_the_suite_does_not_call_the_provider(self):
        with mock.patch("session._oneshot", side_effect=AssertionError("called")):
            self.assertEqual(personal_turn._default_ask("hi"), "")

    def test_a_work_verdict_can_still_be_marked_once(self):
        d = _tmp_sessions("w1")
        job = personal_turn.start_judgment(d, "w1", "ship the fix", "", ask=lambda line: "work")
        personal_turn.bind_judgment(job, 9.0)
        personal_turn.await_judgment(d, "w1", 9.0)
        self.assertFalse(personal_turn.is_marked(d, "w1", 9.0))
        self.assertTrue(personal_turn.mark(d, "w1", 9.0))
        self.assertTrue(personal_turn.mark(d, "w1", 9.0))
        self.assertEqual(len((d / "w1" / personal_turn.FILE).read_text(encoding="utf-8").splitlines()), 1)

    def test_live_scope_waits_and_only_that_session_closes(self):
        import role_guard as R
        d = _tmp_sessions("w1", "w2")
        personal_turn.start_judgment(d, "w1", "hug", "action", ask=lambda line: "work")
        busy = [
            {"id": "w1", "mode": "work", "turn": 1.25, "tools": ["delegate"]},
            {"id": "w2", "mode": "work", "turn": 2.0, "tools": ["delegate"]},
        ]
        self.assertEqual(R.live_scope(busy, "delegate", d, {"id": "w2", "mode": "work"}), (False, False))
        self.assertEqual(R.live_scope(busy, "delegate", d, {}), (True, False))   # no caller: the pending mark still counts
        self.assertTrue(personal_turn.is_marked(d, "w1", 1.25))

    def test_move_chips_wait_for_the_judgment(self):
        import session_turn
        d = _tmp_sessions("s1")
        s = self._sess(d)
        s.mode = "work"
        s.character = ""
        s.history = [{"role": "user", "text": "보고 싶었어", "ts": 7.0}]
        personal_turn.start_judgment(d, "s1", "보고 싶었어", "", ask=lambda line: "personal")
        got = session_turn.SessionTurn.engine_choices(s, [])
        self.assertEqual(got[0]["label_key"], "choice.move")

    def test_send_direct_opens_the_turn(self):
        import session
        self.assertIn("self._open_turn(", inspect.getsource(session.AgentSession._send_direct))


if __name__ == "__main__":
    unittest.main()
