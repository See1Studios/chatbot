"""Work and private talk are separate sessions (SESSION_SPLIT_v1, plan doc §12): the live work session never
lands on a private one, each character's private session is reused, and a private bundle carries no work.
Run: python3 -m unittest tests.test_session_split  (from services/chatbot)
"""
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import characters as C  # noqa: E402
import host_config  # noqa: E402
import instructions as I  # noqa: E402
import route_sessions  # noqa: E402
import session as S  # noqa: E402


class SessionSplit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._sessions = S.SESSIONS
        S.SESSIONS = self.tmp / "sessions"
        S.SESSIONS.mkdir()
        self.reg = S.Registry()
        self._ov = mock.patch("characters.read_brain_overrides", return_value={})
        self._ov.start()

    def tearDown(self):
        self._ov.stop()
        S.SESSIONS = self._sessions
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, sid, **extra):
        d = S.SESSIONS / sid
        d.mkdir()
        payload = {"id": sid, "history": [{"role": "user", "text": "hi"}], "successor_session_id": ""}
        payload.update(extra)
        (d / "meta.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_the_live_work_session_skips_private_and_other_characters(self):
        self.write("20260921-100000-work01")
        self.write("20260921-110000-priv01", mode="private")
        self.write("20260921-120000-other1", character=C.new_id())
        self.assertEqual(self.reg.get_active().sid, "20260921-100000-work01")
        self.assertEqual(self.reg.get_active().mode, "work")

    def test_a_card_named_private_brain_wins_over_the_current_one(self):
        # pew/N4 (operator 2026-09-27): card brains.private first, else the brain the user is on
        work = self.reg.get_active()
        work.provider, work.model = "codex", "gpt-x"
        with mock.patch("session_registry._first_brain", return_value={"provider": "grok", "model": "grok-4.7"}):
            priv = self.reg.get_private("", like=work)
        self.assertEqual((priv.provider, priv.model), ("grok", "grok-4.7"))

    def test_a_saved_override_beats_the_card_private_brain(self):
        work = self.reg.get_active()
        saved = {"private": {"provider": "agy", "model": "gemini-x", "effort": ""}}
        with mock.patch("session_registry._first_brain", return_value={"provider": "grok", "model": "grok-4.7"}), mock.patch("characters.read_brain_overrides", return_value=saved):
            priv = self.reg.get_private("", like=work, fresh=True)
        self.assertEqual((priv.provider, priv.model), ("agy", "gemini-x"))

    def test_a_reset_override_falls_back_to_the_card(self):
        work = self.reg.get_active()
        with mock.patch("session_registry._first_brain", return_value={"provider": "grok", "model": "grok-4.7", "effort": "low"}), mock.patch("characters.read_brain_overrides", return_value={"private": None}):
            priv = self.reg.get_private("", like=work, fresh=True)
        self.assertEqual((priv.provider, priv.model, priv.effort), ("grok", "grok-4.7", "low"))

    def test_a_private_session_is_created_once_and_keeps_its_mode(self):
        work = self.reg.get_active()
        work.provider, work.model = "agy", "gemini-3.1-pro-high"
        # hermetic: no card-named private brain, whatever the live default character's card says (#240 gave it one)
        with mock.patch("session_registry._first_brain", return_value={}):
            priv = self.reg.get_private("", like=work)
        self.assertTrue(priv.is_private)
        self.assertEqual((priv.provider, priv.model), ("agy", "gemini-3.1-pro-high"))
        self.assertTrue(priv.history == [] and priv.sid != work.sid)
        priv.history.append({"role": "user", "text": "x", "ts": 1})
        priv.save_meta()
        again = S.Registry()
        self.assertEqual(again.get_private("").sid, priv.sid)
        self.assertEqual(again.get(priv.sid).mode, "private")
        self.assertEqual(again.get_active().sid, work.sid)
        listed = {x["id"]: x["mode"] for x in again.list()}
        self.assertEqual(listed[priv.sid], "private")

    def test_private_sessions_are_per_character(self):
        other = C.new_id()
        a = self.reg.get_private("")
        b = self.reg.get_private(other)
        for s in (a, b):
            s.history.append({"role": "user", "text": "x", "ts": 1})
            s.save_meta()
        self.assertNotEqual(a.sid, b.sid)
        self.assertEqual(S.Registry().get_private(other).sid, b.sid)
        self.assertEqual(S.Registry().get_private(other).character, other)

    def test_each_visit_to_the_private_room_is_a_new_session_with_the_last_brain(self):
        # PRIVATE_VISIT_v1 (operator 2026-09-29): the last scene's place and talk must not leak into the next visit
        with mock.patch("session_registry._first_brain", return_value={}):
            first = self.reg.get_private("", fresh=True)
            first.provider, first.model = "grok", "grok-4.7"
            first.history.append({"role": "user", "text": "(at the stairwell)", "ts": 1})
            first.save_meta()
            second = self.reg.get_private("", fresh=True)
        self.assertNotEqual(second.sid, first.sid)
        self.assertTrue(second.is_private and second.history == [])
        self.assertEqual((second.provider, second.model), ("grok", "grok-4.7"))

    def test_a_repeated_switch_lands_in_the_room_it_just_opened(self):
        with mock.patch("session_registry._first_brain", return_value={}):
            first = self.reg.get_private("", fresh=True)
            first.history.append({"role": "user", "text": "(scene)", "ts": 1})
            first.visit_started = __import__("time").time()
            self.assertEqual(self.reg.get_private("", fresh=True).sid, first.sid)

    def test_an_unused_private_session_is_reused_not_multiplied(self):
        with mock.patch("session_registry._first_brain", return_value={}):
            first = self.reg.get_private("", fresh=True)
            first.save_meta()
            self.assertEqual(self.reg.get_private("", fresh=True).sid, first.sid)

    def test_every_way_into_the_private_room_asks_for_a_fresh_session(self):
        src = (Path(route_sessions.__file__)).read_text(encoding="utf-8")
        self.assertEqual(src.count("REG.get_private("), src.count("fresh=True)"))

    def test_the_successor_of_a_private_session_is_private(self):
        self.write("20260921-100000-work01")
        self.write("20260921-110000-priv01", mode="private", successor_session_id="20260921-130000-priv02")
        self.write("20260921-130000-priv02", mode="private")
        self.assertEqual(self.reg.get_private("").sid, "20260921-130000-priv02")


class NewSessionKeepsKind(unittest.TestCase):
    """/new (POST /api/sessions) in a private or non-default character's session stays there (#154)."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.pd, self.lulu = C.new_id(), C.new_id()
        C.save(self.pd, C.new_card("P", "pd"), self.ws)
        C.save(self.lulu, C.new_card("L", "staff"), self.ws)
        C.save_team({"default": self.pd, "members": {self.pd: ["pd"], self.lulu: ["staff"]}}, self.ws)   # who is default
        self.saved = (S.SESSIONS, S.WORKSPACE, I.WORKSPACE, host_config.WORKSPACE)
        S.SESSIONS = self.tmp / "sessions"
        S.SESSIONS.mkdir()
        S.WORKSPACE = I.WORKSPACE = host_config.WORKSPACE = self.ws
        self.reg = S.Registry()

    def tearDown(self):
        S.SESSIONS, S.WORKSPACE, I.WORKSPACE, host_config.WORKSPACE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new(self, body):
        mode, character = route_sessions._new_session_kind(body)
        return self.reg.create(model="m", provider="agy", mode=mode, character=character)

    def test_a_private_session_with_a_character_keeps_both(self):
        sess = self.new({"mode": "private", "character": self.lulu})
        self.assertEqual((sess.mode, sess.character), ("private", self.lulu))
        again = S.Registry().get(sess.sid)
        self.assertEqual((again.mode, again.character), ("private", self.lulu))

    def test_no_mode_or_character_is_the_default_work_session(self):
        sess = self.new({})
        self.assertEqual((sess.mode, sess.character), ("work", self.pd))
        self.assertEqual(route_sessions._new_session_kind({"mode": "bogus", "character": ""}), ("work", ""))

    def test_an_unknown_character_is_refused(self):
        self.assertIsNone(route_sessions._new_session_kind({"character": C.new_id()}))
        self.assertIsNone(route_sessions._new_session_kind({"character": "../x"}))


class PrivateBundle(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        (self.ws / "memory").mkdir()
        (self.ws / "AGENTS.md").write_text("charter", encoding="utf-8")
        (self.ws / "memory" / "MEMORY.md").write_text("# Memory\n- work fact\n", encoding="utf-8")
        card = C.new_card("P", "pd", description="persona body")
        card["data"]["system_prompt"] = "private rules"
        self.cid = C.new_id()
        C.save(self.cid, card, self.ws)
        C.remember_private(self.cid, ["likes tea"], ws=self.ws)
        skill = self.ws / ".agents" / "skills" / "fixture-skill"   # the index reads this tree, not the runner's data dir
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: fixture-skill\ndescription: a fixture\n---\n", encoding="utf-8")
        self.saved = (I.WORKSPACE, I.MEMORY_FILE, I.WS_SKILLS_DIR)
        I.WORKSPACE, I.MEMORY_FILE, I.WS_SKILLS_DIR = self.ws, self.ws / "memory" / "MEMORY.md", skill.parent

    def tearDown(self):
        I.WORKSPACE, I.MEMORY_FILE, I.WS_SKILLS_DIR = self.saved
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_private_gets_private_rules_and_memory_and_no_work(self):
        text = I.build_instruction_bundle(mode="private")["text"]
        for want in ("charter", "persona body", "private rules", "likes tea", I.PRIVATE_SESSION_NOTE):
            self.assertIn(want, text)
        for never in ("work fact", "[스킬 색인]", "[자기개선 상태]"):
            self.assertNotIn(never, text)
        work = I.build_instruction_bundle()["text"]
        self.assertIn("work fact", work)
        self.assertNotIn("likes tea", work)
        self.assertNotIn("private rules", work)
        self.assertNotEqual(I.build_instruction_bundle(mode="private")["hash"], I.build_instruction_bundle()["hash"])
        self.assertIn("likes tea", I.build_instruction_bundle(mode="private", character=self.cid)["text"])

    def test_history_to_openai_messages_reflects_session_character_and_mode(self):
        card_pd = C.load(self.cid, self.ws)
        card_pd["data"]["extensions"][C.EXT]["work"] = {"instructions": "pd work instructions"}
        C.save(self.cid, card_pd, self.ws)

        other_cid = C.new_id()
        other_card = C.new_card("Other", "staff", description="unique other staff description")
        other_card["data"]["system_prompt"] = "other private rules"
        C.save(other_cid, other_card, self.ws)
        C.remember_private(other_cid, ["likes coffee"], ws=self.ws)
        C.save_team({"default": self.cid, "members": {self.cid: [], other_cid: []}}, self.ws)

        sess_priv = S.AgentSession("s_priv")
        sess_priv.mode = "private"
        sess_priv.character = other_cid
        msgs_priv = sess_priv._history_to_openai_messages()
        sys_priv = msgs_priv[0]["content"]

        self.assertIn("unique other staff description", sys_priv)
        self.assertIn("other private rules", sys_priv)
        self.assertIn("likes coffee", sys_priv)
        for never in ("persona body", "pd work instructions", "[스킬 색인]", "work fact", "likes tea"):
            self.assertNotIn(never, sys_priv)

        sess_work = S.AgentSession("s_work")
        sess_work.mode = "work"
        sess_work.character = ""
        msgs_work = sess_work._history_to_openai_messages()
        sys_work = msgs_work[0]["content"]

        self.assertIn("persona body", sys_work)
        self.assertIn("pd work instructions", sys_work)
        self.assertIn("[스킬 색인]", sys_work)
        self.assertNotIn("services/chatbot/data/", sys_work)   # uds/F: skills live in the data dir's workspace
        self.assertIn("work fact", sys_work)
        for never in ("unique other staff description", "other private rules", "likes coffee"):
            self.assertNotIn(never, sys_work)


class HandoverExchange(unittest.TestCase):
    """_with_last_exchange includes recent N turns, get_handover_summary caches only base,
    and _finish_turn / _start_turn invalidate the cache (#605)."""

    def setUp(self):
        # a fixture sessions dir: the old fixed id wrote a "test-handover" session into the live chat (2026-10-03)
        self._sessions = S.SESSIONS
        S.SESSIONS = Path(tempfile.mkdtemp()) / "sessions"
        S.SESSIONS.mkdir()

    def tearDown(self):
        shutil.rmtree(str(S.SESSIONS.parent), ignore_errors=True)
        S.SESSIONS = self._sessions

    def _session(self, history, sid="20260101-000000-handov"):
        s = S.AgentSession(sid)
        s.history = list(history)
        return s

    def _past(self, sid, history, pred=""):
        d = S.SESSIONS / sid
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"id": sid, "history": history, "predecessor_session_id": pred}),
                                     encoding="utf-8")

    def test_recent_turns_come_from_the_chain_when_this_session_is_short(self):
        # sessions here are often 2-8 turns: the last 8 turns span several of them (#613)
        self._past("20260101-000001-aaaaaa", [{"role": "user", "text": "q0"}, {"role": "assistant", "text": "a0"},
                                             {"role": "user", "text": "q1"}, {"role": "assistant", "text": "a1"}])
        self._past("20260101-000002-bbbbbb", [{"role": "user", "text": "q2"}, {"role": "assistant", "text": "a2"},
                                             {"role": "user", "text": "q3"}, {"role": "assistant", "text": "a3"}],
                   pred="20260101-000001-aaaaaa")
        s = self._session([{"role": "user", "text": "q4"}, {"role": "assistant", "text": "a4"}],
                          sid="20260101-000003-cccccc")
        s.predecessor_session_id = "20260101-000002-bbbbbb"
        got = s._with_last_exchange("base")
        for t in ("q1", "a1", "q2", "a3", "q4", "a4"):
            self.assertIn(t, got)
        self.assertNotIn("q0", got)                      # 8 turns: q1..a4
        self.assertLess(got.index("q1"), got.index("q4"), "oldest first")
        s.predecessor_session_id = "20260101-000009-gone00"
        self.assertNotIn("q3", s._with_last_exchange("base"), "a missing predecessor ends the walk")

    def test_multiple_turns_included(self):
        """Up to 8 recent user/assistant turns appear in the exchange section."""
        hist = []
        for i in range(6):
            hist.append({"role": "user", "text": f"q{i}"})
            hist.append({"role": "assistant", "text": f"a{i}"})
        s = self._session(hist)
        result = s._with_last_exchange("base summary")
        self.assertIn("[최근 주고받은 대화 원문]", result)
        self.assertIn("base summary", result)
        # last 8 turns = q2..q5 user + a2..a5 assistant
        for i in range(2, 6):
            self.assertIn(f"q{i}", result)
            self.assertIn(f"a{i}", result)
        # turns before the window are excluded
        self.assertNotIn("q0", result)
        self.assertNotIn("a0", result)

    def test_char_budget_limits_turns(self):
        """The char budget stops adding turns once exceeded."""
        hist = []
        # 4 exchanges with long text (800 chars each turn => 6400 total > 3000 budget)
        for i in range(4):
            hist.append({"role": "user", "text": f"q{i}_" + "x" * 800})
            hist.append({"role": "assistant", "text": f"a{i}_" + "y" * 800})
        s = self._session(hist)
        result = s._with_last_exchange("")
        # at ~800 chars per line, budget 3000 fits ~3 lines
        # the first line always gets in (even if > budget), then stops once exceeded
        lines = [l for l in result.split("\n") if l.strip() and l != "[최근 주고받은 대화 원문]"]
        self.assertGreaterEqual(len(lines), 1)
        self.assertLess(len(lines), 8)  # not all 8 turns
        # newest turns are kept, oldest in the window are dropped
        self.assertIn("q3_", result)
        self.assertIn("a3_", result)
        self.assertNotIn("q0_", result)

    def test_empty_history_returns_base(self):
        s = self._session([])
        self.assertEqual(s._with_last_exchange("base"), "base")

    def test_single_user_turn(self):
        s = self._session([{"role": "user", "text": "hello"}])
        result = s._with_last_exchange("base")
        self.assertIn("hello", result)
        self.assertIn("[최근 주고받은 대화 원문]", result)

    def test_header_changed_from_old(self):
        """The section header is now [최근 주고받은 대화 원문], not the old single-exchange one."""
        s = self._session([{"role": "user", "text": "x"}, {"role": "assistant", "text": "y"}])
        result = s._with_last_exchange("b")
        self.assertNotIn("마지막으로", result)
        self.assertIn("최근 주고받은", result)

    def test_base_only_cached(self):
        """get_handover_summary caches only the compressed base, not the exchange tail."""
        s = self._session([
            {"role": "user", "text": "turn1"},
            {"role": "assistant", "text": "reply1"},
        ])
        s.provider = "agy"
        with mock.patch.object(s, "_dialogue_summary_fallback", return_value="compressed base"):
            with mock.patch.object(s, "_native_compact", return_value=""):
                result = s.get_handover_summary(native=True)
        # cache holds only the base, not the exchange section
        self.assertEqual(s._cached_summary, "compressed base")
        # but the returned value includes the exchange
        self.assertIn("[최근 주고받은 대화 원문]", result)
        self.assertIn("turn1", result)

    def test_cached_call_appends_fresh_exchange(self):
        """A cached call re-appends the exchange from current history."""
        s = self._session([
            {"role": "user", "text": "old"},
            {"role": "assistant", "text": "old-reply"},
        ])
        s._cached_summary = "cached base"
        s.provider = "agy"
        # add a newer turn AFTER the cache was set
        s.history.append({"role": "user", "text": "new-question"})
        s.history.append({"role": "assistant", "text": "new-answer"})
        result = s.get_handover_summary()
        self.assertIn("new-question", result)
        self.assertIn("new-answer", result)

    def test_finish_turn_invalidates_cache(self):
        """_finish_turn clears _cached_summary."""
        s = self._session([{"role": "user", "text": "x"}])
        s._cached_summary = "old"
        s.provider = "agy"
        s.model = "m"
        s._obs_turn_logged = None
        s.turn_started_at = 0
        with mock.patch("session.evolution", None):
            s._finish_turn("result")
        self.assertEqual(s._cached_summary, "")

    def test_start_turn_invalidates_cache(self):
        """_start_turn clears _cached_summary when a new user message arrives."""
        s = self._session([])
        s._cached_summary = "stale"
        s.provider = "agy"
        s.model = "m"
        s.mode = "work"
        s._loop_hint = ""
        s.handoff_summary = ""
        s.persona_injected = True
        s.persona_bundle_hash = "h"
        s.adapter = mock.MagicMock()
        s.adapter.keeps_stdin_open = False
        s.adapter.transport_kind = "stdio"
        s.adapter.turn_context.return_value = ""
        s.proc = None
        s.lock = __import__("threading").RLock()
        with mock.patch("session_turn._s") as mock_s:
            mock_s.return_value = mock.MagicMock()
            mock_s.return_value.build_instruction_bundle.return_value = {"text": "", "hash": "h"}
            mock_s.return_value.boot_notice.return_value = ""
            mock_s.return_value.format_client_context.return_value = ""
            try:
                s._start_turn("hello", "", None, False, "chat")
            except Exception:
                pass  # adapter spawn may fail in test; cache invalidation happens before
        self.assertEqual(s._cached_summary, "")


if __name__ == "__main__":
    unittest.main()


class NoPrecompute(unittest.TestCase):
    def test_a_heavy_session_does_not_summarize_ahead_of_a_rotation(self):
        # NO_PRECOMPUTE_v1: a full-context /compact after every turn of a heavy session (2026-10-05)
        src = (Path(__file__).resolve().parent.parent / "session.py").read_text(encoding="utf-8")
        self.assertNotIn("_precompute_summary", src)
