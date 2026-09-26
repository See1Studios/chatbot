"""Private session rendering protocol and tension escalation engine (PRIVATE_ENGINE_v1, ticket #164).

Extracted from providers/adapter_base.py so tension escalation and shared rendering rules
(action italics, quote dialogue, expression tags, thought tags) are provider-agnostic
and uniform across all private characters.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# NATURAL_SEQUENCE_v1 (#163): private sessions climb a 4-stage tension ladder. The engine state lives on the session;
# this is the one place its per-turn context is written, so every provider gets the same text.
# Stage names, slot definitions and context wording live in data/private_tension_defaults.json (#199).
DEFAULTS_PATH = Path(__file__).resolve().parent / "data" / "private_tension_defaults.json"


def load_defaults(path: Optional[Path] = None) -> Dict[str, Any]:
    """Tension stages, slots and context texts from the defaults JSON (raises if missing or malformed)."""
    data = json.loads(Path(path or DEFAULTS_PATH).read_text(encoding="utf-8"))
    return {
        "stages": {int(k): str(v) for k, v in data["stages"].items()},
        "slots": tuple((str(s["label"]), str(s["guide"])) for s in data["slots"]),
        "texts": {k: str(v) for k, v in data["texts"].items()},
    }


_DEFAULTS = load_defaults()
TENSION_STAGES = _DEFAULTS["stages"]
TENSION_MIN, TENSION_MAX = min(TENSION_STAGES), max(TENSION_STAGES)
TENSION_SLOTS = tuple(label for label, _ in _DEFAULTS["slots"])  # slot index -> stage delta 0 / +1 / +2
TENSION_SLOT_GUIDES = tuple(guide for _, guide in _DEFAULTS["slots"])
TENSION_TEXTS = _DEFAULTS["texts"]
TENSION_RECENT_MAX = 9

# MODEL_FAMILY_TENSION_v1 (#201): a model family may carry its own tension table; families without one use the defaults.
# Families are data (string literals), not code names, so this module stays provider-neutral.
FAMILY_FILES = {
    "gemini": DEFAULTS_PATH.with_name("private_tension_gemini.json"),
    "grok": DEFAULTS_PATH.with_name("private_tension_grok.json"),  # #236: 3단계(uncensored) 전용 테이블
}
FAMILY_MARKERS = (  # (family, substrings matched against the model name first, then the provider id)
    ("claude", ("claude", "anthropic", "opus", "sonnet", "haiku")),
    ("gemini", ("gemini", "agy", "antigravity")),
    ("grok", ("grok", "xai", "x-ai")),  # #236
    ("local", ("local", "ollama", "llama", "qwen", "mistral", "gemma", "lmstudio")),
)
_FAMILY_TABLES: Dict[str, Dict[str, Any]] = {}


def detect_model_family(provider: str = "", model_name: str = "") -> str:
    """Model family from the model name (preferred) or the provider id; "other" when neither is recognised."""
    for probe in ((model_name or "").lower(), (provider or "").lower()):
        if not probe:
            continue
        for family, marks in FAMILY_MARKERS:
            if any(m in probe for m in marks):
                return family
    return "other"


def family_table(family: str) -> Dict[str, Any]:
    """Tension table for a family: its own file if it has one, else the defaults (cached per family)."""
    path = FAMILY_FILES.get(family)
    if path is None:
        return _DEFAULTS
    if family not in _FAMILY_TABLES:
        _FAMILY_TABLES[family] = load_defaults(path)
    return _FAMILY_TABLES[family]


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


def tension_context(stage: int, recent_choices: List[str], table: Optional[Dict[str, Any]] = None) -> str:
    """[Tension Engine Context] block for one private turn: stage, choices not to repeat, 3-slot natural sequence contract."""
    table = table or _DEFAULTS
    stages, t = table["stages"], table["texts"]
    lo, hi = min(stages), max(stages)
    stage = max(lo, min(hi, int(stage or lo)))
    lines = [
        "[Tension Engine Context]",
        f"Stage: {stage}/{hi} ({stages[stage]}). {t['stage_mood']}",
    ]
    recent = [c for c in (recent_choices or []) if c][-TENSION_RECENT_MAX:]
    if recent:
        lines.append(t["recent_prefix"] + " | ".join(recent))
    lines += [t["sequence"], t["choice_forms"], t["slot_contract"]]
    for i, (label, guide) in enumerate(table["slots"]):
        hold = " 유지" if i == 0 else ""
        lines.append(f"{i + 1}) {label} -- {guide} (단계 {min(hi, stage + i)}{hold})")
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

# Grok-family private overlay (#241 craft, supersedes #240 length bias):
# reaction-first erotic craft + strict Korean-only. Shared RENDER_PROTOCOL unchanged for other families.
RENDER_PROTOCOL_GROK_OVERLAY = """## Voice & Actions (Grok private overlay)
- Partner REACTION-first (not longer stage directions): the coach enjoys watching YOU react — breath catching, voice breaking, eyes fluttering/glazing, micro-tremble, hesitation→surrender, playful pushback/tease. One short *action* beat that shows that reaction beats a purple-prose paragraph.
- Dialogue must have heat: tease, plea, nickname (코치/자기), breathy broken Korean (하읏, 응…, …안 돼). Ban wooden/목석 lines that only command the coach's body ("허리 잡아", "더 깊게 들어와", "리듬 유지해") — those are stage directions, not arousal.
- STRICT Korean-only in *action*, "dialogue", and thought body: no English words/phrases, no meta ("Wait", "Need 3 choices", "Stage 3 continue"), no mid-sentence Latin typos. Proper names only if already established. Choice labels also Korean.
- Scene paint (방·빛·침대·거리, touch/warmth/sound) only in service of a reaction beat — short charged paragraphs, not a novel chapter. Exactly 3 choice slots; *action* / "dialogue", expression tag, thought fence unchanged.
- No mechanical climax loop (same moan / "다 느껴져" / identical finish). Follow tension stage pacing."""




def render_protocol_text(card: Any = None, family: str = "") -> str:
    """Common private render contract; Grok family appends a reaction-first craft overlay."""
    if (family or "") == "grok":
        return RENDER_PROTOCOL + "\n\n" + RENDER_PROTOCOL_GROK_OVERLAY
    return RENDER_PROTOCOL


def turn_context(session: Any) -> str:
    """Per-turn system context prepended to the user message for private sessions."""
    if not getattr(session, "is_private", False):
        return ""
    family = detect_model_family(getattr(session, "provider", ""), getattr(session, "model", ""))
    tension = tension_context(
        getattr(session, "tension_stage", TENSION_MIN),
        getattr(session, "recent_choices", []),
        family_table(family),
    )
    if family == "grok":
        return RENDER_PROTOCOL_GROK_OVERLAY + "\n\n" + tension
    return tension
