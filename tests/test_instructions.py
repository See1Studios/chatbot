"""Unit tests for the host-built instruction bundle and its injection contract
(docs/plans/instruction-architecture.md §3/§5). No model calls, no live server.

    python3 tests/test_instructions.py
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import instructions as I  # noqa: E402
import session as S  # noqa: E402


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "workspace"
        _write(self.ws / "AGENTS.md", "# 헌장\nCHARTER-MARK")
        _write(self.ws / "PERSONA.md", "# 페르소나\nPERSONA-MARK")
        _write(self.ws / ".agents/skills/alpha/SKILL.md",
               "---\nname: alpha\ndescription: >\n  알파 스킬 설명\n  두 번째 줄\n---\n본문")
        _write(self.ws / ".agents/skills/_off/SKILL.md", "---\nname: _off\ndescription: 꺼짐\n---\n")
        _write(self.ws / "memory/MEMORY.md", "# 기억\n\n## 실장님\n\n## 운영 결정\n")
        _write(self.ws / "skill-observations/observation-log/0001-x.md", "---\nstatus: open\n---\n")
        _write(self.ws / "skill-observations/observation-log/0002-y.md", "---\nstatus: actioned\n---\n")
        _write(self.ws / "skill-observations/last-review-date.txt", "2026-09-16\n")
        I.WORKSPACE = self.ws
        I.WS_SKILLS_DIR = self.ws / ".agents" / "skills"
        I.MEMORY_FILE = self.ws / "memory" / "MEMORY.md"
        I.OBS_DIR = self.ws / "skill-observations" / "observation-log"
        I.LAST_REVIEW_FILE = self.ws / "skill-observations" / "last-review-date.txt"
        # rule files are resolved from I.WORKSPACE at call time
        S.build_instruction_bundle = I.build_instruction_bundle


class BundleTests(WorkspaceCase):
    def test_contains_layers(self):
        b = I.build_instruction_bundle()
        t = b["text"]
        self.assertIn("CHARTER-MARK", t)
        self.assertIn("PERSONA-MARK", t)
        self.assertIn("- alpha — 알파 스킬 설명 두 번째 줄", t)
        self.assertNotIn("_off", t)
        self.assertIn("열린 관찰 1건 · 미검토 후보 0건 · 마지막 리뷰 2026-09-16", t)

    def test_the_badge_counts_candidates_since_the_last_review_only(self):
        import time
        day_start = time.mktime(time.strptime("2026-09-16", "%Y-%m-%d"))
        rows = [{"epoch": day_start - 3600, "signal": "stopped"}, {"epoch": day_start + 3600, "signal": "correction"},
                {"epoch": day_start + 7200, "signal": "stopped"}]
        _write(self.ws / "skill-observations/candidates.jsonl", "".join(json.dumps(r) + "\n" for r in rows))
        self.assertIn("열린 관찰 1건 · 미검토 후보 2건 · 마지막 리뷰 2026-09-16", I.build_instruction_bundle()["text"])

    def test_the_badge_survives_a_missing_core_module_and_a_missing_candidate_file(self):
        self.assertIn("미검토 후보 0건", I.build_instruction_bundle()["text"])  # no candidates.jsonl
        saved = I.observations
        I.observations = None
        try:
            self.assertIn("미검토 후보 0건", I.build_instruction_bundle()["text"])
        finally:
            I.observations = saved

    def test_the_badge_is_not_part_of_the_hash(self):
        h0 = I.build_instruction_bundle()["hash"]
        _write(self.ws / "skill-observations/candidates.jsonl", json.dumps({"epoch": 9e9, "signal": "stopped"}) + "\n")
        self.assertEqual(h0, I.build_instruction_bundle()["hash"])

    def test_empty_memory_template_is_omitted(self):
        self.assertNotIn("[장기 기억 스냅샷]", I.build_instruction_bundle()["text"])

    def test_memory_fact_is_included_but_does_not_change_hash(self):
        h0 = I.build_instruction_bundle()["hash"]
        _write(self.ws / "memory/MEMORY.md", "# 기억\n\n## 실장님\n- [2026-09-19] 커피는 아메리카노\n")
        b = I.build_instruction_bundle()
        self.assertIn("[장기 기억 스냅샷]", b["text"])
        self.assertIn("아메리카노", b["text"])
        self.assertEqual(h0, b["hash"])

    def test_hash_changes_with_charter_persona_and_skills(self):
        h0 = I.build_instruction_bundle()["hash"]
        _write(self.ws / "AGENTS.md", "# 헌장\nCHANGED")
        h1 = I.build_instruction_bundle()["hash"]
        self.assertNotEqual(h0, h1)
        _write(self.ws / ".agents/skills/beta/SKILL.md", "---\nname: beta\ndescription: 베타\n---\n")
        self.assertNotEqual(h1, I.build_instruction_bundle()["hash"])

    def test_no_rules_means_no_bundle(self):
        for f in ("AGENTS.md", "PERSONA.md"):
            (self.ws / f).unlink()
        import shutil
        shutil.rmtree(self.ws / ".agents")
        self.assertEqual(I.build_instruction_bundle(), {"text": "", "hash": ""})


class InjectionTests(WorkspaceCase):
    def make(self, http=False):
        S.SESSIONS = self.tmp / "sessions"
        (S.SESSIONS / "t").mkdir(parents=True, exist_ok=True)
        s = S.AgySession("t", provider="agy")
        s.adapter = types.SimpleNamespace(
            keeps_stdin_open=False, transport_kind="http" if http else "process",
            format_stdin=lambda c: c, mints_own_conversation_id=lambda: False,
        )
        self.sent = []
        s._spawn = lambda prompt="": self.sent.append(prompt)
        s._run_http_turn = lambda content: self.sent.append(content)
        s._http_turn_watchdog = lambda seq: None
        s._emit = lambda ev: None
        return s

    def test_first_turn_gets_bundle_then_never_again(self):
        s = self.make()
        s._send_direct("첫 질문")
        self.assertTrue(self.sent[0].startswith("[시스템 안내]"))
        self.assertIn("CHARTER-MARK", self.sent[0])
        self.assertTrue(self.sent[0].rstrip().endswith("첫 질문"))
        self.assertTrue(s.persona_injected)
        self.assertTrue(s.persona_bundle_hash)
        s._send_direct("둘째 질문")
        self.assertEqual(self.sent[1], "둘째 질문")

    def test_state_survives_reload_without_reinjection(self):
        s = self.make()
        s._send_direct("a")
        s.save_meta()
        s2 = S.AgySession("t", provider="agy")
        self.assertTrue(s2.persona_injected)
        self.assertEqual(s2.persona_bundle_hash, s.persona_bundle_hash)

    def test_rule_change_reinjects_once_as_update(self):
        s = self.make()
        s._send_direct("a")
        _write(self.ws / "PERSONA.md", "# 페르소나\nPERSONA-V2")
        s._send_direct("b")
        self.assertIn("규칙이 갱신되었다", self.sent[1])
        self.assertIn("PERSONA-V2", self.sent[1])
        s._send_direct("c")
        self.assertEqual(self.sent[2], "c")

    def test_memory_change_does_not_reinject(self):
        s = self.make()
        s._send_direct("a")
        _write(self.ws / "memory/MEMORY.md", "## 실장님\n- [2026-09-19] 새 사실\n")
        s._send_direct("b")
        self.assertEqual(self.sent[1], "b")

    def test_legacy_flag_without_hash_adopts_silently(self):
        s = self.make()
        s.persona_injected, s.persona_bundle_hash = True, ""
        s._send_direct("a")
        self.assertEqual(self.sent[0], "a")
        self.assertTrue(s.persona_bundle_hash)

    def test_order_is_rules_then_handoff_then_message(self):
        s = self.make()
        s.handoff_summary = "HANDOFF-MARK"
        s._send_direct("현재-MSG")
        t = self.sent[0]
        self.assertTrue(t.startswith("[시스템 안내]"))
        i_rules, i_handoff, i_msg = t.index("CHARTER-MARK"), t.index("HANDOFF-MARK"), t.rindex("현재-MSG")
        self.assertLess(i_rules, i_handoff)
        self.assertLess(i_handoff, i_msg)

    def test_swap_resets_so_new_provider_gets_bundle_with_handoff(self):
        s = self.make()
        s._send_direct("a")
        s.get_handover_summary = lambda use_cache=False: "HANDOFF-MARK"
        s.stop = lambda notify=True: None   # mirror the real signature; a swap stops with notify=False
        s.maybe_swap_provider("claude")
        self.assertFalse(s.persona_injected)
        self.assertEqual(s.persona_bundle_hash, "")
        s.adapter = types.SimpleNamespace(keeps_stdin_open=False, transport_kind="process",
                                          format_stdin=lambda c: c, mints_own_conversation_id=lambda: True)
        s._send_direct("b")
        self.assertIn("CHARTER-MARK", self.sent[1])
        self.assertIn("HANDOFF-MARK", self.sent[1])

    def test_http_transport_flags_but_does_not_prefix(self):
        s = self.make(http=True)
        s._send_direct("질문")
        self.assertEqual(self.sent[0], "질문")
        self.assertTrue(s.persona_injected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
