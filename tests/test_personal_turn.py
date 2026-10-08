"""PERSONAL_TURN_v1 (docs/plans/private-mode.md §8.3, W1): a work-room turn marked personal stays in the chat but
never becomes work material -- no work tools during it, nothing recallable from work; and
a private session is never recallable from work at all.
Run: engine/run-tests.sh test_personal_turn
"""
import importlib.util
import json
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
