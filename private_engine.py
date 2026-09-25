"""Private session rendering protocol and tension escalation engine (PRIVATE_ENGINE_v1, ticket #164).

Extracted from providers/adapter_base.py so tension escalation and shared rendering rules
(action italics, quote dialogue, expression tags, thought tags) are provider-agnostic
and uniform across all private characters.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# NATURAL_SEQUENCE_v1 (#163): private sessions climb a 4-stage tension ladder. The engine state lives on the session;
# this is the one place its per-turn context is written, so every provider gets the same text.
TENSION_MIN, TENSION_MAX = 1, 4
TENSION_STAGES = {1: "도입", 2: "고조", 3: "밀착", 4: "절정"}
TENSION_SLOTS = ("자연스러운 다음 진도", "더 과감한 밀착/직진", "깊은 감각/분위기 탐닉")  # slot index -> stage delta 0 / +1 / +2
TENSION_RECENT_MAX = 9


def tension_after(stage: int, slot: int = -1, action: bool = False) -> int:
    """Next stage: a picked slot moves it by its index (slot 0 holds, 1 nudges +1, 2 nudges +2), an action nudges +1; clamped to 1..4."""
    step = slot if 0 <= slot < len(TENSION_SLOTS) else (1 if action else 0)
    return max(TENSION_MIN, min(TENSION_MAX, int(stage or TENSION_MIN) + step))


def tension_meta(meta: Dict[str, Any]) -> Tuple[int, List[str]]:
    """(stage, recent_choices) as saved in a session's meta.json; defaults for a new session."""
    stage = max(TENSION_MIN, min(TENSION_MAX, int(meta.get("tension_stage") or TENSION_MIN)))
    return stage, [str(c) for c in (meta.get("recent_choices") or [])][-TENSION_RECENT_MAX:]


def _choice_candidates(c: str) -> set[str]:
    """All matching candidate strings for one offered choice (label, full text, dialogue, action)."""
    c_str = c.strip()
    parts = [p.strip() for p in c_str.split("->", 1)]
    cands = {c_str, parts[0]}
    if len(parts) > 1:
        rhs = parts[1]
        cands.update({rhs, rhs.strip("()").strip(), rhs.strip('"').strip()})
        for q in re.findall(r'"([^"]+)"', rhs):
            cands.update({f'"{q}"', q})
        for p in re.findall(r'\(([^)]+)\)', rhs):
            cands.update({f'({p})', p})
    return {x for x in cands if x}


def tension_step(stage: int, recent: List[str], history: List[dict], text: str,
                 event_type: str = "") -> Tuple[int, List[str]]:
    """Next (stage, recent_choices) for one private user turn, called before the turn joins `history`.
    Picking one of the last offered choices moves by its slot; an action (type "action", or the page's "(...)"
    form) nudges +1; anything else holds. The used offer (or the action) joins recent_choices, deduped, capped."""
    said = (text or "").strip()
    action = event_type == "action" or (len(said) > 2 and said[0] == "(" and said[-1] == ")")
    last = next((h for h in reversed(history or []) if h.get("role") in ("user", "assistant")), {})
    offered = [str(c) for c in (last.get("choices") or [])] if last.get("role") == "assistant" else []
    labels = [c.split("->")[0].strip() for c in offered]
    said_unwrapped = said.strip("()").strip()
    picked = {said, said_unwrapped, said.strip('"').strip(), said_unwrapped.strip('"').strip()}
    candidates = [_choice_candidates(c) for c in offered]
    slot = next((i for i, cand in enumerate(candidates) if picked & cand), -1)
    if slot < 0 and not action:
        return stage, list(recent or [])
    used = [x for x in (labels if slot >= 0 else [said_unwrapped]) if x]
    kept = [c for c in (recent or []) if c not in used] + used
    return tension_after(stage, slot if slot < len(TENSION_SLOTS) else -1, action), kept[-TENSION_RECENT_MAX:]


def tension_context(stage: int, recent_choices: List[str]) -> str:
    """[Tension Engine Context] block for one private turn: stage, choices not to repeat, 3-slot natural sequence contract."""
    stage = max(TENSION_MIN, min(TENSION_MAX, int(stage or TENSION_MIN)))
    lines = [
        "[Tension Engine Context]",
        f"Stage: {stage}/{TENSION_MAX} ({TENSION_STAGES[stage]}). 현재 단계의 무드와 스킨십 수위에 맞게 장면을 연출할 것.",
    ]
    recent = [c for c in (recent_choices or []) if c][-TENSION_RECENT_MAX:]
    if recent:
        lines.append("최근 사용한 선택지 반복 및 유사 표현 금지: " + " | ".join(recent))
    top = min(TENSION_MAX, stage + 2)
    lines.append(
        "직전 행동의 신체 부위와 거리감에서 끊김 없이 자연스럽게 이어지는 행동 시퀀스를 구성할 것. "
        "(예: 포옹 -> 키스 -> 애무 -> 눕히기 -> 벗기기 -> 절정)\n"
        "선택지는 '라벨 -> \"대사\"' 형태의 순수 대사형, '라벨 -> (행동)' 형태의 행동형, "
        "'라벨 -> \"대사\" (행동)' 결합형을 상황과 흐름에 맞게 자연스럽게 혼합 구성할 것.\n"
        "억지 밀당이나 어색한 화제 전환을 배제하고, 반드시 다음 3가지 슬롯 순서대로 정확히 3개의 선택지를 제시할 것:\n"
        f"1) {TENSION_SLOTS[0]} -- 직전 신체 부위/거리감에서 이어지는 다음 행동 (단계 {stage} 유지)\n"
        f"2) {TENSION_SLOTS[1]} -- 한 걸음 더 깊이 파고드는 과감한 스킨십과 밀착 (단계 {min(TENSION_MAX, stage + 1)})\n"
        f"3) {TENSION_SLOTS[2]} -- 신체 감각과 짙은 분위기에 온전히 젖어드는 탐닉 (단계 {top})"
    )
    return "\n".join(lines)


# Common private-mode rendering contract text promoted from individual character cards.
RENDER_PROTOCOL = """## Voice & Actions
- Physical actions, body language, gaze, motions, and touch should be written in concise italics (*...*). Spoken dialogue must be in quotes ("...").
- Keep responses short: one or two spoken sentences with vivid, light physical actions. No novel or visual-novel prose, no stage directions.
- No AI tells: no meta commentary ("내가 생각해도 ~", "~톤으로 맞췄어", "마음에 들어?"), no over-eager or textbook empathy.

## Expressions & Thoughts
- Expression tag `[expression: neutral|joy|shy|serious|sorrow|tired]` at the very start to reflect your current emotion (read by the UI).
- Internal private thoughts, when holding unexpressed feelings, go in a fenced block on their own lines:
  ```thought
  ...
  ```

## Choices
- End every reply with one line `<!--choices: 라벨 -> "대사" | 라벨 -> (행동) | 라벨 -> "대사" (행동)-->` (mix pure dialogue, action, or combined forms as appropriate).
- Each item offers what the user might say or do next: a short label, ` -> `, followed by pure dialogue in quotes (`"대사"`), action in parentheses (`(행동)`), or mixed dialogue and action (`"대사" (행동)`).
- Naturally mix pure dialogue (`라벨 -> "대사"`), action (`라벨 -> (행동)`), and combined (`라벨 -> "대사" (행동)`) choices to fit the moment (e.g. `더 가까이 -> "조금만 더 가까이 와줘" | 안아주기 -> (조용히 끌어안는다) | 속삭이기 -> "좋아해" (귀에 대고 속삭인다)`)."""


def render_protocol_text(card: Any = None) -> str:
    """The common private-mode rendering contract text (card param placeholder for future overrides)."""
    return RENDER_PROTOCOL


def turn_context(session: Any) -> str:
    """Per-turn system context prepended to the user message for private sessions."""
    if not getattr(session, "is_private", False):
        return ""
    return tension_context(
        getattr(session, "tension_stage", TENSION_MIN),
        getattr(session, "recent_choices", []),
    )

