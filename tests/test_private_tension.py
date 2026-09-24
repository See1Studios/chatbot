"""Private sessions climb a 4-stage tension ladder and every private turn carries a [Tension Engine Context] block
with the stage, the recent choices not to repeat and the 3-slot natural sequence contract (NATURAL_SEQUENCE_v1, #163).
Run: python3 -m unittest tests.test_private_tension  (from services/chatbot)
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session as S  # noqa: E402
from providers import adapter_base as AB  # noqa: E402


class _Stdin:
    def __init__(self):
        self.sent = []

    def write(self, data):
        self.sent.append(data)

    def flush(self):
        pass


class _Proc:
    def __init__(self):
        self.stdin = _Stdin()

    def poll(self):
        return None


class _Adapter(AB.AgentAdapter):
    id = "fake"

    def format_stdin(self, content):
        return content


class TensionLadder(unittest.TestCase):
    def test_slots_move_by_index_and_actions_nudge(self):
        self.assertEqual(AB.tension_after(1, slot=0), 1)
        self.assertEqual(AB.tension_after(1, slot=1), 2)
        self.assertEqual(AB.tension_after(2, slot=2), 4)
        self.assertEqual(AB.tension_after(4, slot=2), 4)
        self.assertEqual(AB.tension_after(3, action=True), 4)
        self.assertEqual(AB.tension_after(0), 1)

    def test_context_names_stage_exclusions_and_three_slots(self):
        ctx = AB.tension_context(2, ["손을 잡는다", "", "눈을 피한다"])
        self.assertTrue(ctx.startswith("[Tension Engine Context]"))
        self.assertIn("Stage: 2/4", ctx)
        self.assertIn("손을 잡는다 | 눈을 피한다", ctx)
        self.assertIn("3가지 슬롯 순서", ctx)
        for slot in ("자연스러운 다음 진도", "더 과감한 밀착/직진", "깊은 감각/분위기 탐닉"):
            self.assertIn(slot, ctx)
        self.assertIn("포옹 -> 키스 -> 애무 -> 눕히기 -> 벗기기 -> 절정", ctx)
        self.assertNotIn("최근 사용한 선택지", AB.tension_context(1, []))

    def test_turn_context_is_private_only(self):
        class Sess:
            is_private, tension_stage, recent_choices = False, 3, []
        self.assertEqual(_Adapter().turn_context(Sess()), "")
        Sess.is_private = True
        self.assertIn("Stage: 3/4", _Adapter().turn_context(Sess()))


class SessionTension(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._sessions = S.SESSIONS
        S.SESSIONS = self.tmp / "sessions"
        S.SESSIONS.mkdir()
        self.sess = S.AgentSession("20260925-100000-priv01")
        self.sess.mode = "private"
        self.sess.adapter = _Adapter()
        self.sess.proc = _Proc()
        self.sess.ensure = lambda: None

    def tearDown(self):
        S.SESSIONS = self._sessions
        shutil.rmtree(self.tmp, ignore_errors=True)

    def note(self, text, event_type=""):
        s = self.sess
        s.tension_stage, s.recent_choices = AB.tension_step(s.tension_stage, s.recent_choices, s.history, text, event_type)

    def offer(self, *choices):
        self.sess.history.append({"role": "assistant", "text": "...", "ts": 1, "choices": list(choices)})

    def test_picking_a_slot_moves_the_stage_and_records_the_offer(self):
        self.offer("밀어낸다", "다가간다 -> 다가간다", "안긴다")
        self.note("다가간다")
        self.assertEqual(self.sess.tension_stage, 2)
        self.assertEqual(self.sess.recent_choices, ["밀어낸다", "다가간다", "안긴다"])

    def test_an_action_nudges_and_free_text_holds(self):
        self.note("그냥 얘기하자")
        self.assertEqual((self.sess.tension_stage, self.sess.recent_choices), (1, []))
        self.note("(고개를 끄덕인다)")
        self.assertEqual(self.sess.tension_stage, 2)
        self.note("가까이 앉는다", event_type="action")
        self.assertEqual(self.sess.tension_stage, 3)
        self.assertEqual(self.sess.recent_choices, ["고개를 끄덕인다", "가까이 앉는다"])

    def test_recent_choices_dedupe_and_cap(self):
        for i in range(12):
            self.note(f"(동작{i % 10})")
        self.assertEqual(len(self.sess.recent_choices), AB.TENSION_RECENT_MAX)
        self.assertEqual(len(set(self.sess.recent_choices)), len(self.sess.recent_choices))
        self.assertEqual(self.sess.recent_choices[-1], "동작1")
        self.assertEqual(self.sess.tension_stage, 4)

    def test_state_survives_a_reload(self):
        self.note("(웃는다)")
        self.sess.save_meta()
        again = S.AgentSession(self.sess.sid)
        self.assertEqual((again.tension_stage, again.recent_choices), (2, ["웃는다"]))

    def test_a_private_turn_carries_the_tension_context(self):
        self.offer("모른 척한다", "손을 잡는다", "입을 맞춘다")
        self.sess.send("입을 맞춘다")
        wire = "".join(self.sess.proc.stdin.sent)
        self.assertIn("[Tension Engine Context]", wire)
        self.assertIn("Stage: 3/4", wire)
        self.assertIn("모른 척한다 | 손을 잡는다 | 입을 맞춘다", wire)
        self.assertTrue(wire.rstrip().endswith("입을 맞춘다"))

    def test_a_work_turn_has_no_tension_context(self):
        self.sess.mode = "work"
        self.sess.send("(웃는다)")
        self.assertNotIn("[Tension Engine Context]", "".join(self.sess.proc.stdin.sent))
        self.assertEqual((self.sess.tension_stage, self.sess.recent_choices), (1, []))

    def test_an_explicit_action_event_reaches_the_engine(self):
        self.sess.send("곁에 앉는다", event_type="action")
        self.assertEqual((self.sess.tension_stage, self.sess.recent_choices), (2, ["곁에 앉는다"]))
        self.assertIn("Stage: 2/4", "".join(self.sess.proc.stdin.sent))


if __name__ == "__main__":
    unittest.main()
