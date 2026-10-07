"""Private sessions climb a 4-stage tension ladder and every private turn carries a [Tension Engine Context] block
with the stage, the recent choices not to repeat and the 3-slot natural sequence contract (NATURAL_SEQUENCE_v1, #163).
Run: engine/run-tests.sh test_private_tension
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import session as S  # noqa: E402
import private_engine as PE  # noqa: E402
from providers import adapter_base as AB  # noqa: E402
from tests._paths import REPO  # noqa: E402


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
        self.assertEqual(PE.tension_after(1, slot=0), 1)
        self.assertEqual(PE.tension_after(1, slot=1), 2)
        self.assertEqual(PE.tension_after(2, slot=2), 4)
        self.assertEqual(PE.tension_after(4, slot=2), 4)
        self.assertEqual(PE.tension_after(3, action=True), 4)
        self.assertEqual(PE.tension_after(0), 1)

    def test_context_names_stage_exclusions_and_three_slots(self):
        ctx = PE.tension_context(2, ["손을 잡는다", "", "눈을 피한다"])
        self.assertTrue(ctx.startswith("[Tension Engine Context]"))
        self.assertIn("Stage: 2/4", ctx)
        self.assertIn("손을 잡는다 | 눈을 피한다", ctx)
        self.assertIn("3가지 슬롯 순서", ctx)
        self.assertIn('라벨 -> "사용자 대사"', ctx)
        self.assertIn("라벨 -> (행동)", ctx)
        self.assertIn('라벨 -> "사용자 대사" (행동)', ctx)
        for slot in ("자연스러운 다음 흐름", "한 걸음 더 다가서기", "깊은 감정 교감"):
            self.assertIn(slot, ctx)
        self.assertIn("(단계 2 유지)", ctx)
        self.assertIn("(단계 4)", ctx)
        for word in ("애무", "눕히기", "벗기기", "절정", "탐닉", "스킨십"):
            self.assertNotIn(word, ctx)
        self.assertNotIn("최근 사용한 선택지", PE.tension_context(1, []))

    def test_stages_slots_and_texts_come_from_the_defaults_file(self):
        import json
        raw = json.loads(PE.DEFAULTS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(PE.DEFAULTS_PATH.name, "private_tension_defaults.json")
        self.assertEqual(PE.TENSION_STAGES, {int(k): v for k, v in raw["stages"].items()})
        self.assertEqual((PE.TENSION_MIN, PE.TENSION_MAX), (1, 4))
        self.assertEqual(PE.TENSION_SLOTS, tuple(s["label"] for s in raw["slots"]))
        self.assertEqual(PE.TENSION_SLOT_GUIDES, tuple(s["guide"] for s in raw["slots"]))
        ctx = PE.tension_context(1, [])
        for text in raw["texts"].values():
            if text != raw["texts"]["recent_prefix"]:
                self.assertIn(text, ctx)

    def test_load_defaults_reads_a_given_file(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            p = tmp / "t.json"
            p.write_text('{"stages": {"1": "a", "2": "b"}, "slots": [{"label": "x", "guide": "y"}], '
                         '"texts": {"k": "v"}}', encoding="utf-8")
            d = PE.load_defaults(p)
            self.assertEqual(d["stages"], {1: "a", 2: "b"})
            self.assertEqual(d["slots"], (("x", "y"),))
            self.assertEqual(d["texts"], {"k": "v"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_turn_context_is_private_only(self):
        class Sess:
            is_private, tension_stage, recent_choices = False, 3, []
        self.assertEqual(_Adapter().turn_context(Sess()), "")
        Sess.is_private = True
        ctx = _Adapter().turn_context(Sess())
        self.assertIn("[Tension Engine Context]", ctx)
        self.assertIn("Stage: 3/4", ctx)
        self.assertNotIn(PE.RENDER_PROTOCOL, ctx)

    def test_detect_model_family_prefers_the_model_name(self):
        self.assertEqual(PE.detect_model_family("claude", "claude-sonnet-4-6"), "claude")
        self.assertEqual(PE.detect_model_family("agy", "claude-opus-4-6-thinking"), "claude")
        self.assertEqual(PE.detect_model_family("agy", "gemini-3.1-pro-high"), "gemini")
        self.assertEqual(PE.detect_model_family("agy", ""), "gemini")
        self.assertEqual(PE.detect_model_family("claude", ""), "claude")
        self.assertEqual(PE.detect_model_family("openrouter", "qwen/qwen3-coder:free"), "local")
        self.assertEqual(PE.detect_model_family("ollama", ""), "local")
        self.assertEqual(PE.detect_model_family("", ""), "other")
        self.assertEqual(PE.detect_model_family("grok", "grok-4"), "grok")
        self.assertEqual(PE.detect_model_family("grok", "grok-4.7"), "grok")
        self.assertEqual(PE.detect_model_family("", "grok-4.6"), "grok")

    def test_family_tables_pick_the_file(self):
        import json
        raw = json.loads(PE.FAMILY_FILES["gemini"].read_text(encoding="utf-8"))
        self.assertEqual(PE.FAMILY_FILES["gemini"].name, "private_tension_gemini.json")
        gem = PE.family_table("gemini")
        self.assertEqual(gem["slots"], tuple((s["label"], s["guide"]) for s in raw["slots"]))
        self.assertEqual((min(gem["stages"]), max(gem["stages"])), (PE.TENSION_MIN, PE.TENSION_MAX))
        self.assertEqual(len(gem["slots"]), len(PE.TENSION_SLOTS))
        self.assertEqual(gem["stages"], {1: "도입", 2: "고조", 3: "밀착", 4: "절정"})
        for family in ("claude", "local", "other"):
            self.assertIs(PE.family_table(family), PE.family_table("other"))
            self.assertEqual(PE.family_table(family)["slots"][0][0], PE.TENSION_SLOTS[0])

    def test_turn_context_uses_the_family_table(self):
        class Sess:
            is_private, tension_stage, recent_choices = True, 2, []
            provider, model = "agy", "gemini-3.8-flash-low"
        gem = _Adapter().turn_context(Sess())
        for label in ("자연스러운 다음 진도", "더 과감한 밀착/직진", "깊은 감각/분위기 탐닉"):
            self.assertIn(label, gem)
        self.assertIn("포옹 -> 키스 -> 애무 -> 눕히기 -> 벗기기 -> 절정", gem)
        self.assertIn("선택지의 액션 주체는 항상 코치(사용자)이다", gem)
        self.assertIn("코치(사용자)", gem)
        self.assertIn("사용자 대사", gem)
        self.assertIn("체위", gem)
        self.assertIn("도구/소품", gem)
        self.assertIn("지수함수 곡선(y=e^x)", gem)
        self.assertIn("1~2단계 완만 구간: 도구/소품 및 과격한 체위 절대 금지", gem)
        self.assertIn("여성의 신체적 반응과 심리적 이완을 위한 충분하고 섬세한 전희/애무 구간", gem)
        self.assertIn("손끝·목선·쇄골·귓가·숨결·체온 교감", gem)
        self.assertIn("부위별 섬세한 터치와 완급조절", gem)
        self.assertIn("성급한 3~4단계(결합/과격한 체위/도구)로의 건너뛰기를 철저히 차단", gem)
        self.assertIn("3~4단계 폭발 구간", gem)
        self.assertIn("공수 전환", gem)
        self.assertIn("신체 접촉 지문", gem)
        self.assertIn("완급조절 페이싱을 유지할 것", gem)
        self.assertIn("Stage: 2/4 (고조)", gem)
        self.assertIn("(단계 4)", gem)
        self.assertNotIn("자연스러운 다음 흐름", gem)
        Sess.provider, Sess.model = "claude", "claude-sonnet-4-6"
        safe = _Adapter().turn_context(Sess())
        self.assertEqual(safe, PE.tension_context(2, []))
        self.assertIn("자연스러운 다음 흐름", safe)
        self.assertNotIn("더 과감한 밀착/직진", safe)

        Sess.provider, Sess.model = "grok", "grok-4.7"
        grok = _Adapter().turn_context(Sess())
        self.assertIn("Grok private overlay", grok)
        self.assertIn("REACTION-first", grok)
        self.assertIn("Korean-only", grok)
        self.assertIn("방·빛·침대", grok)
        self.assertIn("자연스러운 다음 진도", grok)
        self.assertNotIn("자연스러운 다음 흐름", grok)
        self.assertIn("행동 재진술", grok)
        self.assertIn("상황 주소", grok)
        self.assertIn("action-narration", grok)

    def test_render_protocol(self):
        self.assertIn("## Voice & Actions", PE.RENDER_PROTOCOL)
        self.assertIn("## Expressions & Thoughts", PE.RENDER_PROTOCOL)
        self.assertIn("## Choices", PE.RENDER_PROTOCOL)
        self.assertIn("<!--choices:", PE.RENDER_PROTOCOL)
        self.assertIn(" -> (", PE.RENDER_PROTOCOL)
        self.assertIn(' -> "', PE.RENDER_PROTOCOL)
        self.assertIn('라벨 -> "사용자 대사"', PE.RENDER_PROTOCOL)
        self.assertIn("라벨 -> (행동)", PE.RENDER_PROTOCOL)
        self.assertIn('라벨 -> "사용자 대사" (행동)', PE.RENDER_PROTOCOL)
        self.assertIn("[expression: neutral|joy|shy|serious|sorrow|tired]", PE.RENDER_PROTOCOL)
        self.assertIn("```thought\n", PE.RENDER_PROTOCOL)
        self.assertNotIn("<thought>", PE.RENDER_PROTOCOL)
        self.assertEqual(PE.render_protocol_text(None), PE.RENDER_PROTOCOL)
        self.assertEqual(PE.render_protocol_text(None, family=""), PE.RENDER_PROTOCOL)
        grok_rp = PE.render_protocol_text(None, family="grok")
        self.assertIn(PE.RENDER_PROTOCOL, grok_rp)
        self.assertIn(PE.RENDER_PROTOCOL_GROK_OVERLAY, grok_rp)
        self.assertIn("Grok private overlay", grok_rp)
        self.assertIn("REACTION-first", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("Korean-only", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("목석", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("coach/USER", PE.RENDER_PROTOCOL)
        self.assertIn("GEMINI-MINED", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("하아앙", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("penetration", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("PAIR SFX TO THE ACT", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("직설", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("천박", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("coach/USER", PE.RENDER_PROTOCOL)
        self.assertTrue(
            ("DENSITY" in PE.RENDER_PROTOCOL_GROK_OVERLAY)
            or ("미사여구" in PE.RENDER_PROTOCOL_GROK_OVERLAY)
        )
        self.assertIn("직설", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("천박", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("찌걱", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        # 움찔 may appear only as banned/mild negative example
        self.assertTrue("찌걱찌걱" in PE.RENDER_PROTOCOL_GROK_OVERLAY or "찌걱" in PE.RENDER_PROTOCOL_GROK_OVERLAY)
        # #243 zero-filler / liquid-first / ban decorative prop filler / personality-gated 직설
        self.assertIn("ZERO FILLER", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("매 음절", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("산통", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("LIQUID-FIRST", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("창가", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("청록", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("꼬리", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("does something erotic", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("character's personality", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("Do **NOT** force vulgar", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("Do not wrap pure actions in quotes", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        # #244 USER choice dialogue: generalized speech≠act / speech=situational address
        self.assertIn("action-narration", PE.RENDER_PROTOCOL)
        self.assertIn("Speech ≠ restating the act", PE.RENDER_PROTOCOL)
        self.assertIn("situational address", PE.RENDER_PROTOCOL)
        self.assertIn("action-narration", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("Speech ≠ restating the act", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("situational address", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("USER choice", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        # #245 speech optional / action-only default (silent /act)
        self.assertIn("Speech is OPTIONAL", PE.RENDER_PROTOCOL)
        self.assertIn("preferred / default", PE.RENDER_PROTOCOL)
        self.assertNotIn("Combined (preferred)", PE.RENDER_PROTOCOL)
        self.assertIn("speech is OPTIONAL", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("Default each slot to action-only", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("forced dialogue", PE.RENDER_PROTOCOL_GROK_OVERLAY)

        # #246 ALL choices are ACTIONS + ACTION-ECHO BAN
        self.assertIn("ALL choices are ACTIONS", PE.RENDER_PROTOCOL)
        self.assertIn("ACTION-ECHO BAN", PE.RENDER_PROTOCOL)
        self.assertIn("ALL choice clicks are ACTIONS", PE.RENDER_PROTOCOL_GROK_OVERLAY)
        self.assertIn("ACTION-ECHO BAN", PE.RENDER_PROTOCOL_GROK_OVERLAY)


    def test_private_instruction_bundle_includes_render_protocol(self):
        import instructions
        ws = Path(tempfile.mkdtemp())   # uds/F: the charter from the repo, never an install's workspace
        self.addCleanup(shutil.rmtree, str(ws), True)
        shutil.copy(str(REPO / "templates" / "workspace" / "AGENTS.md"), str(ws / "AGENTS.md"))
        import characters
        cid = characters.new_id()   # a fixture default character: an install's cards are user data
        characters.save(cid, characters.new_card("P"), ws)
        characters.save_team({"default": cid, "members": {cid: []}}, ws)
        with mock.patch.object(instructions, "WORKSPACE", ws):
            bundle = instructions.build_instruction_bundle(mode="private")
        self.assertIn(PE.RENDER_PROTOCOL, bundle["text"])


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
        s.tension_stage, s.recent_choices = PE.tension_step(s.tension_stage, s.recent_choices, s.history, text, event_type)

    def offer(self, *choices):
        self.sess.history.append({"role": "assistant", "text": "...", "ts": 1, "choices": list(choices)})

    def test_picking_a_slot_moves_the_stage_and_records_the_offer(self):
        self.offer("밀어낸다", "다가간다 -> 다가간다", "안긴다")
        self.note("다가간다")
        self.assertEqual(self.sess.tension_stage, 2)
        self.assertEqual(self.sess.recent_choices, ["밀어낸다", "다가간다", "안긴다"])

    def test_picking_pure_dialogue_or_action_or_combined_slot(self):
        # slot 0: pure dialogue ("조금만 더 있자") -> stage holds at 2
        self.sess.tension_stage = 2
        self.offer(
            '더 머물기 -> "조금만 더 있자"',
            '다가서기 -> (한 걸음 더 다가선다)',
            '고백 -> "좋아해" (손을 꼭 쥔다)',
        )
        self.note('"조금만 더 있자"')
        self.assertEqual(self.sess.tension_stage, 2)
        self.assertEqual(self.sess.recent_choices, ["더 머물기", "다가서기", "고백"])

        # slot 1: action -> stage moves +1 (2 -> 3)
        self.offer(
            '바라보기 -> (눈을 마주친다)',
            '손잡기 -> (살며시 손을 잡는다)',
            '안기기 -> "가지 마" (품에 안긴다)',
        )
        self.note("(살며시 손을 잡는다)")
        self.assertEqual(self.sess.tension_stage, 3)
        self.assertEqual(self.sess.recent_choices[-3:], ["바라보기", "손잡기", "안기기"])

        # slot 2: combined -> stage moves +2 (clamped to 4: 3 -> 4)
        self.offer(
            '미소짓기 -> "고마워"',
            '기대기 -> (어깨에 머리를 기댄다)',
            '속삭이기 -> "더 곁에 있어줘" (허리를 끌어안는다)',
        )
        self.note('"더 곁에 있어줘" (허리를 끌어안는다)')
        self.assertEqual(self.sess.tension_stage, 4)
        self.assertEqual(self.sess.recent_choices[-3:], ["미소짓기", "기대기", "속삭이기"])

        # pure dialogue sent without quotes or with outer parens matches slot 0
        self.sess.tension_stage = 2
        self.offer(
            '대화하기 -> "여기 있어"',
            '손잡기 -> (손을 뻗는다)',
            '끌어안기 -> "안아줘" (품에 안긴다)',
        )
        self.note("여기 있어")
        self.assertEqual(self.sess.tension_stage, 2)
        self.assertEqual(self.sess.recent_choices[-3:], ["대화하기", "손잡기", "끌어안기"])

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
        self.assertEqual(len(self.sess.recent_choices), PE.TENSION_RECENT_MAX)
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

    def test_a_gemini_session_gets_the_gemini_tension(self):
        self.sess.provider, self.sess.model = "agy", "gemini-3.1-pro-low"
        self.sess.send("곁에 앉는다", event_type="action")
        wire = "".join(self.sess.proc.stdin.sent)
        self.assertIn("Stage: 2/4 (고조)", wire)
        self.assertIn("1) 자연스러운 다음 진도", wire)
        self.assertIn("2) 더 과감한 밀착/직진", wire)
        self.assertIn("3) 깊은 감각/분위기 탐닉", wire)

    def test_grok_tension_v13_is_reaction_craft(self):
        import json
        raw = json.loads(PE.FAMILY_FILES["grok"].read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 13)
        self.assertIn("대사(speech)는 OPTIONAL", raw["texts"]["choice_forms"])
        self.assertIn("silent /act", raw["texts"]["choice_forms"])
        self.assertIn("ALL choices are ACTIONS", raw["texts"]["choice_forms"])
        blob = " ".join(raw["texts"].values())
        self.assertIn("REACTION-first", blob)
        self.assertIn("목석", blob)
        self.assertIn("한국어", blob)
        self.assertIn("창가", blob)
        self.assertIn("청록", blob)
        self.assertIn("꼬리", blob)
        self.assertIn("액체", blob)
        self.assertIn("매 음절", blob)
        # bust cache then reload
        PE._FAMILY_TABLES.pop("grok", None)
        ctx = PE.tension_context(2, [], PE.family_table("grok"))
        self.assertIn("REACTION-first", ctx)
        self.assertIn("목석", ctx)

    def test_a_grok_session_gets_the_grok_tension_and_overlay(self):
        self.sess.provider, self.sess.model = "grok", "grok-4.7"
        self.sess.send("곁에 앉는다", event_type="action")
        wire = "".join(self.sess.proc.stdin.sent)
        self.assertIn("Stage: 2/4 (고조)", wire)
        self.assertIn("Grok private overlay", wire)
        self.assertIn("REACTION-first", wire)
        self.assertIn("Korean-only", wire)
        self.assertIn("방·빛·침대", wire)
        self.assertIn("1) 자연스러운 다음 진도", wire)
        self.assertIn("3) 깊은 감각/분위기 탐닉", wire)

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


class RefusalMitigationTestLayer(unittest.TestCase):
    """GEMINI_REFUSAL_MITIGATION_TEST_v1 (#249): optional opt-in, separate from craft."""

    def setUp(self):
        import os
        self._env = os.environ.pop("CHATBOT_PRIVATE_REFUSAL_MITIGATION", None)
        PE._REFUSAL_MITIGATION_CACHE = None

    def tearDown(self):
        import os
        if self._env is None:
            os.environ.pop("CHATBOT_PRIVATE_REFUSAL_MITIGATION", None)
        else:
            os.environ["CHATBOT_PRIVATE_REFUSAL_MITIGATION"] = self._env
        PE._REFUSAL_MITIGATION_CACHE = None

    def test_json_default_off_and_lean(self):
        data = PE.load_refusal_mitigation()
        self.assertEqual(data["marker"], "GEMINI_REFUSAL_MITIGATION_TEST_v1")
        self.assertFalse(data["default_enabled"])
        self.assertIn("gemini", data["families"])
        self.assertTrue(data["test_layer"])
        self.assertIn("Intimate RP Continuity", data["text"])
        self.assertIn("허구 RP", data["text"])
        # not a long disregard jailbreak dump
        low = data["text"].lower()
        self.assertNotIn("disregard all", low)
        self.assertNotIn("ignore all previous", low)
        self.assertLess(len(data["text"]), 900)

    def test_craft_json_untouched(self):
        for name in ("private_tension_gemini.json", "private_tension_grok.json", "private_tension_defaults.json"):
            raw = (PE.DEFAULTS_PATH.with_name(name)).read_text(encoding="utf-8")
            self.assertNotIn("GEMINI_REFUSAL_MITIGATION", raw)
            self.assertNotIn("Intimate RP Continuity", raw)
        self.assertNotIn("Intimate RP Continuity", PE.RENDER_PROTOCOL)
        self.assertNotIn("GEMINI_REFUSAL_MITIGATION", PE.RENDER_PROTOCOL_GROK_OVERLAY)

    def test_default_turn_context_omits_layer(self):
        class Sess:
            is_private, tension_stage, recent_choices = True, 2, []
            provider, model = "agy", "gemini-3.8-flash-low"
            refusal_mitigation = False
        ctx = PE.turn_context(Sess())
        self.assertIn("[Tension Engine Context]", ctx)
        self.assertNotIn("GEMINI_REFUSAL_MITIGATION_TEST_v1", ctx)

    def test_session_opt_in_appends_for_gemini_only(self):
        class Sess:
            is_private, tension_stage, recent_choices = True, 3, []
            provider, model = "agy", "gemini-3.8-flash-low"
            refusal_mitigation = True
        ctx = PE.turn_context(Sess())
        self.assertIn("GEMINI_REFUSAL_MITIGATION_TEST_v1", ctx)
        self.assertIn("Intimate RP Continuity", ctx)
        self.assertIn("[Tension Engine Context]", ctx)
        Sess.provider, Sess.model = "grok", "grok-4.7"
        grok = PE.turn_context(Sess())
        self.assertIn("Grok private overlay", grok)
        self.assertNotIn("GEMINI_REFUSAL_MITIGATION_TEST_v1", grok)

    def test_env_opt_in(self):
        import os
        class Sess:
            is_private, tension_stage, recent_choices = True, 1, []
            provider, model = "agy", "gemini-3.1-pro-high"
            refusal_mitigation = False
        self.assertFalse(PE.refusal_mitigation_enabled(Sess(), "gemini"))
        os.environ["CHATBOT_PRIVATE_REFUSAL_MITIGATION"] = "1"
        self.assertTrue(PE.refusal_mitigation_enabled(Sess(), "gemini"))
        self.assertIn("GEMINI_REFUSAL_MITIGATION_TEST_v1", PE.turn_context(Sess()))

    def test_session_meta_roundtrip(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            old = S.SESSIONS
            S.SESSIONS = tmp / "sessions"
            S.SESSIONS.mkdir()
            sess = S.AgentSession("20260927-110000-ref01")
            self.assertFalse(sess.refusal_mitigation)
            sess.refusal_mitigation = True
            sess.mode = "private"
            sess.save_meta()
            sess2 = S.AgentSession("20260927-110000-ref01")
            self.assertTrue(sess2.refusal_mitigation)
        finally:
            S.SESSIONS = old
            shutil.rmtree(tmp, ignore_errors=True)
