"""#864 (private-mode.md section 3.3): a first meeting opened a private visit at tension stage 3 -- the host's scene line
counted as the user's act (+1) and a brink note lifted it again (+1) -- and every offer was explicit touch. The engine
now opens a visit at the relationship level's stage, holds on the scene line, tells the character its level every
turn, and logs each private turn's stage move as metadata only (private.turn).
Run: engine/run-tests.sh test_relationship_guard
"""
import json
import sys
import threading
import unittest
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import items  # noqa: E402
import private_engine as PE  # noqa: E402
import route_sessions  # noqa: E402


class Visit:
    def __init__(self, history=None, stage=1):
        self.sid, self.character, self.is_private = "p1", "c1", True
        self.history, self.tension_stage, self.recent_choices = history or [], stage, []
        self.provider, self.model, self.lock = "agy", "gemini-x", threading.Lock()


def points(n):
    return mock.patch.object(items, "read_state", lambda cid, ws=None: {"affection": {"points": n}, "given": {}})


class Levels(unittest.TestCase):
    def test_the_level_table_carries_each_level_s_opening_and_stance(self):
        for lv in items.table()["levels"]:
            self.assertLessEqual(lv["start_stage"], lv["start_max"])
            self.assertTrue(lv["stance"].isascii(), "agent-facing text is English")
        with points(0):
            r = PE.relationship(Visit())
        self.assertEqual((r["level"], r["start"], r["start_max"]), (1, 1, 1))
        with points(60):
            self.assertEqual(PE.relationship(Visit())["start"], 2)


class KnownCharacters(unittest.TestCase):
    def test_a_character_with_private_history_is_not_guarded_as_a_stranger(self):
        # #876: points come only from gifts, so 1,944 private lines read as level 1 "strangers" after #864
        with points(4), mock.patch.object(items, "private_turns", lambda cid: 1944):
            r = PE.relationship(Visit())
        self.assertEqual((r["level"], r["start"], r["stance"]), (0, 1, ""))
        self.assertEqual(PE.relationship_context(r), "", "no level line until the level is measured (D14)")
        with points(0), mock.patch.object(items, "private_turns", lambda cid: 20):
            self.assertEqual(PE.relationship(Visit())["level"], 1, "a first meeting (20 lines) is still guarded")

class Turn(unittest.TestCase):
    def setUp(self):
        self.logged = []
        p = mock.patch("telemetry.obslog.event", lambda evt, **kw: self.logged.append((evt, kw)))
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(PE, "_threshold_note", lambda s: "")
        q.start()
        self.addCleanup(q.stop)

    def test_the_scene_line_is_not_the_user_s_act(self):
        v = Visit()
        PE.step_turn(v, "(업무 도중 잠깐 함께 비상계단에 왔다)", "scene")
        self.assertEqual(v.tension_stage, 1)
        with points(0):
            PE.step_turn(v, "(손을 잡는다)", "action")
        self.assertEqual(v.tension_stage, 2, "a real act on the first turn still nudges, from the level's opening")

    def test_a_visit_opens_at_its_level_and_hears_the_guard_every_turn(self):
        v = Visit(stage=3)                                # whatever the stage was, a first turn opens at the level
        with points(0):
            PE.step_turn(v, "(scene)", "scene")
            ctx = PE.turn_context(v)
        self.assertEqual(v.tension_stage, 1)
        self.assertIn("[Relationship -- engine state", ctx)
        self.assertIn("Level 1/5: strangers", ctx)
        v.history = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello", "choices": ["a", "b", "c"]}]
        v.tension_stage = 2
        with points(0):
            self.assertIn("Level 1/5", PE.turn_context(v))
        self.assertEqual(v.tension_stage, 2, "after the opening the user's picks move it")

    def test_each_private_turn_is_logged_without_a_word_of_the_talk(self):
        v = Visit(history=[{"role": "assistant", "text": "말", "choices": ["안아 주기 -> (x)", "b", "c"]}], stage=1)
        PE.step_turn(v, "안아 주기", "")
        with points(0):
            PE.turn_context(v)
        evt, kw = self.logged[-1]
        self.assertEqual(evt, "private.turn")
        self.assertEqual({k: kw[k] for k in ("level", "stage_from", "stage", "cause", "first", "offered")},
                         {"level": 1, "stage_from": 1, "stage": 1, "cause": "slot1", "first": False, "offered": 3})
        self.assertNotIn("안아", json.dumps(kw, ensure_ascii=False))


class Route(unittest.TestCase):
    def test_the_page_marks_the_scene_line(self):
        self.assertEqual(route_sessions._action_text({"type": "action", "action_text": "x", "scene": True}, "/act x"),
                         ("(x)", "scene"))
        self.assertEqual(route_sessions._action_text({"type": "action", "action_text": "x"}, "/act x"), ("(x)", "action"))


if __name__ == "__main__":
    unittest.main()
