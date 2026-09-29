"""THRESHOLD_v1 + move choice (docs/plans/private-mode.md §8.3-8.4, W2/W2b): entering the private room hands one short
note across, once; never the work transcript. A personal work turn offers a move, until the user stays twice.
Run: python3 -m unittest tests.test_threshold  (from services/chatbot)
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import personal_turn  # noqa: E402
import private_engine  # noqa: E402
import threshold  # noqa: E402


class Room:
    def __init__(self, sessions, sid, mode, history=None):
        (sessions / sid).mkdir(parents=True, exist_ok=True)
        self.sid, self.mode, self.character = sid, mode, "c1"
        self.meta_path = sessions / sid / "meta.json"
        self.history = history or []
        self.lock = threading.Lock()
        self.is_private = mode == "private"
        self.tension_stage = 1
        self.recent_choices = []
        self.provider, self.model = "agy", ""


def _wait():
    for t in [t for t in threading.enumerate() if t.name == "private-threshold"]:
        t.join(5)


class Base(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        self.sessions = self.data / "sessions"
        now = time.time()
        self.hist = [{"role": "user", "text": "fix the cache in server.py", "ts": now - 60},
                     {"role": "assistant", "text": "done", "ts": now - 50},
                     {"role": "user", "text": "you look lovely", "ts": now - 30},
                     {"role": "assistant", "text": "eek", "ts": now - 20}]
        self.work = Room(self.sessions, "w1", "work", self.hist)
        self.priv = Room(self.sessions, "p1", "private")
        self.prompts = []

    def ask(self, text):
        def oneshot(prompt, timeout):
            self.prompts.append(prompt)
            return {"text": text}
        return oneshot

    def enter(self, text="/private on", reply="He looked tired but proud."):
        r = threshold.enter(self.work, self.priv, text, self.sessions, self.ask(reply), lambda: ("coach", "Nono"))
        _wait()
        return r

    def note(self):
        p = self.sessions / "p1" / threshold.FILE
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class Handoff(Base):
    def test_a_personal_last_turn_crosses_as_an_event_without_content(self):
        personal_turn.mark(self.sessions, "w1", self.hist[2]["ts"])
        self.assertIs(self.enter("/private on 계단실"), self.priv)
        self.assertEqual((self.note()["kind"], self.note()["text"], self.note()["place"]), ("brink", "", "계단실"))
        self.assertEqual(self.prompts, [])                      # no model call, nothing of the talk

    def test_otherwise_a_gist_without_paths_links_code_or_personal_turns(self):
        personal_turn.mark(self.sessions, "w1", self.hist[0]["ts"] - 1)   # an older mark does not make it a brink
        self.hist.append({"role": "user", "text": "ok next", "ts": time.time() - 5})
        personal_turn.mark(self.sessions, "w1", self.hist[2]["ts"])
        self.enter(reply="He looked tired but proud. He fixed server.py at https://x.y. We are done.")
        n = self.note()
        self.assertEqual(n["kind"], "gist")
        self.assertEqual(n["text"], "He looked tired but proud. We are done.")
        self.assertNotIn("you look lovely", self.prompts[0])     # a personal turn is not work to summarise
        self.assertIn("fix the cache", self.prompts[0])

    def test_old_work_hands_nothing(self):
        for h in self.hist:
            h["ts"] -= threshold.GIST_SEC + 10
        self.enter()
        self.assertIsNone(self.note())

    def test_off_hands_only_the_place(self):
        state = self.data / "workspace" / "characters" / "c1" / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"threshold": "off"}), encoding="utf-8")
        self.enter("/private on 옥상")
        self.assertEqual((self.note()["kind"], self.note()["place"]), ("place", "옥상"))
        self.assertEqual(self.prompts, [])


class Take(Base):
    def test_the_note_is_used_once_and_a_brink_raises_the_tension(self):
        personal_turn.mark(self.sessions, "w1", self.hist[2]["ts"])
        self.enter("/private on 계단실")
        first = threshold.take(self.priv, "coach")
        self.assertIn("flustered", first)
        self.assertIn("계단실", first)
        self.assertEqual(self.priv.tension_stage, 2)
        self.assertEqual(threshold.take(self.priv, "coach"), "")

    def test_the_private_turn_context_carries_it_and_a_work_turn_never_does(self):
        self.enter()
        self.assertEqual(private_engine.turn_context(self.work), "")
        ctx = private_engine.turn_context(self.priv)
        self.assertIn("[Threshold", ctx)
        self.assertIn("tired but proud", ctx)
        self.assertNotIn("[Threshold", private_engine.turn_context(self.priv))


class Scene(Base):
    """SCENE_v1: a room switch sends a scene line as an action, so the character speaks first."""

    def test_going_in_names_the_place_and_that_it_is_during_work(self):
        self.enter("/private on 비상계단")
        self.assertEqual(threshold.pop_scene(self.priv), "(업무 도중 잠깐 함께 비상계단에 왔다)")
        self.assertEqual(threshold.pop_scene(self.priv), "")                   # sent once

    def test_coming_back_says_only_where_they_went(self):
        self.enter("/private on 비상계단")
        digested = []
        self.assertIs(threshold.leave(self.priv, self.work, digested.append), self.work)
        self.assertEqual(digested, [self.priv])
        self.assertEqual(threshold.pop_scene(self.work), "(함께 비상계단에서 사무실로 돌아왔다)")
        self.assertFalse((self.sessions / "p1" / threshold.SCENE_FILE).exists())

    def test_without_a_place_or_recent_work_the_lines_stay_general(self):
        for h in self.hist:
            h["ts"] -= threshold.GIST_SEC + 10
        self.enter()
        self.assertEqual(threshold.pop_scene(self.priv), "(잠깐 둘만 있을 곳으로 함께 자리를 옮겼다)")
        threshold.leave(self.priv, self.work)
        self.assertEqual(threshold.pop_scene(self.work), "(둘만의 시간을 보내고 함께 사무실로 돌아왔다)")

    def test_the_character_setting_turns_it_off(self):
        state = self.data / "workspace" / "characters" / "c1" / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"auto_scene": False}), encoding="utf-8")
        self.enter("/private on 비상계단")
        threshold.leave(self.priv, self.work)
        self.assertEqual((threshold.pop_scene(self.priv), threshold.pop_scene(self.work)), ("", ""))


class Repeat(Base):
    """A second switch request within REPEAT_SEC (a re-tap while the switch loads, another tab) is the same move:
    no second scene line, no second note (2026-09-30: the stairwell scene went twice, 8 s apart)."""

    def test_going_in_twice_sends_one_scene(self):
        self.enter("/private on 계단실")
        self.assertEqual(threshold.pop_scene(self.priv), "(업무 도중 잠깐 함께 계단실에 왔다)")
        self.enter("/private on 계단실")
        self.assertEqual(threshold.pop_scene(self.priv), "")

    def test_coming_back_twice_sends_one_scene(self):
        self.enter("/private on 계단실")
        threshold.leave(self.priv, self.work)
        self.assertTrue(threshold.pop_scene(self.work))
        threshold.leave(self.priv, self.work)
        self.assertEqual(threshold.pop_scene(self.work), "")

    def test_a_later_visit_is_a_new_move(self):
        self.enter("/private on 계단실")
        threshold.pop_scene(self.priv)
        self.priv.visit_started -= threshold.REPEAT_SEC + 1
        self.enter("/private on 옥상")
        self.assertEqual(threshold.pop_scene(self.priv), "(업무 도중 잠깐 함께 옥상에 왔다)")


class Pending(Base):
    def test_the_first_turn_waits_for_a_gist_still_being_written(self):
        _write = threshold._write
        threshold._write(self.sessions, "p1", {"kind": "pending", "place": "", "ts": 0})
        t = threading.Timer(0.5, lambda: _write(self.sessions, "p1", {"kind": "gist", "text": "Tired.", "place": ""}))
        t.start()
        self.assertIn("Tired.", threshold.take(self.priv, "coach"))

    def test_a_gist_later_than_the_wait_is_dropped(self):
        saved = threshold.WAIT_SEC
        threshold.WAIT_SEC = 0.2
        self.addCleanup(setattr, threshold, "WAIT_SEC", saved)
        gate = threading.Event()

        def slow(prompt, timeout):
            gate.wait(5)
            return {"text": "He looked tired."}
        threshold.enter(self.work, self.priv, "/private on", self.sessions, slow, lambda: ("coach", "Nono"))
        self.assertEqual(threshold.take(self.priv, "coach"), "")               # gave up waiting
        gate.set()
        _wait()
        self.assertIsNone(self.note())                                         # and the late gist never lands


class MoveOffer(Base):
    def test_two_offers_then_quiet_until_the_user_moves(self):
        busy = [{"id": "w1", "mode": "work", "turn": 0}]
        said = []
        for i in range(3):
            busy[0]["turn"] = 100.0 + i
            said.append(personal_turn.tool_call(self.sessions, busy, "w1")[1])
        self.assertIn("Offer the move", said[0])
        self.assertIn("Offer the move", said[1])
        self.assertIn("Do not offer", said[2])
        self.enter()                                            # the user took a move: offers start over
        busy[0]["turn"] = 200.0
        self.assertIn("Offer the move", personal_turn.tool_call(self.sessions, busy, "w1")[1])

    def test_place_hints(self):
        self.assertEqual(threshold.place_hint("/private on  퇴근길 "), "퇴근길")
        self.assertEqual(threshold.place_hint("/private on"), "")


class Wiring(unittest.TestCase):
    def test_the_switch_accepts_a_place_and_hands_the_note(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("threshold.leave(sess, REG.get_active(sess.character), _digest_private_later)", src)
        self.assertIn('"scene": threshold.pop_scene(target)', src)
        page = (ROOT / "static" / "app-session.js").read_text(encoding="utf-8")
        self.assertIn("if (res.scene && typeof sendAction === 'function') sendAction(res.scene);", page)
        self.assertIn('or stripped.startswith("/private on "):', src)
        self.assertIn("threshold.enter(sess, REG.get_private(sess.character, like=sess, fresh=True), text)", src)

    def test_a_move_chip_is_an_allowed_command(self):
        import mcp_server
        self.assertTrue(mcp_server._is_allowed_choice_command("/private on 계단실"))
        for rel in ("data/workspace/AGENTS.md", "templates/workspace/AGENTS.md"):
            self.assertIn("-> command: /private on", (ROOT / rel).read_text(encoding="utf-8"), rel)


if __name__ == "__main__":
    unittest.main()
