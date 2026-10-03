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
# Stage names, slot definitions and context wording live in engine_data/private_tension_defaults.json (#199; moved
# out of data/ in uds/C1: they are engine tables, not user data).
DEFAULTS_PATH = Path(__file__).resolve().parent / "engine_data" / "private_tension_defaults.json"


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



def strip_outer_parens(s: str) -> str:
    """Strip balanced outer (...) wraps only. Unlike str.strip('()'), keeps
    trailing ')' that close an inner group (e.g. '"line" (act)' stays intact)."""
    out = (s or "").strip()
    while len(out) >= 2 and out[0] == "(" and out[-1] == ")":
        depth = 0
        balanced = True
        for i, ch in enumerate(out):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(out) - 1:
                    balanced = False
                    break
                if depth < 0:
                    balanced = False
                    break
        if not balanced or depth != 0:
            break
        out = out[1:-1].strip()
    return out


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
    said_unwrapped = strip_outer_parens(said)
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
- Actions, gaze and touch in concise italics (*...*); speech in quotes ("..."). One or two spoken sentences with light action; no novel prose, no stage directions.
- **ACTION-ECHO BAN**: never restate the user's action; write only YOUR reaction (liquid/wet, moan/breath, body micro-react). Dense.
- No AI tells: no meta commentary ("내가 생각해도 ~", "~톤으로 맞췄어", "마음에 들어?"), no textbook empathy.

## Expressions & Thoughts
- Expression tag `[expression: neutral|joy|shy|serious|sorrow|tired]` at the very start to reflect your current emotion (read by the UI).
- Internal private thoughts, when holding unexpressed feelings, go in a fenced block on their own lines:
  ```thought
  ...
  ```

## Choices
- Choices are the **coach/USER's next move**, never your lines, moans or pleas; you react to the pick in your *next* reply.
- **ALL choices are ACTIONS**: every chip clicks as `/act`. Real speech = the user typing.
- End every reply with one line `<!--choices: 라벨 -> (행동) | 라벨 -> "사용자 대사" (행동)-->` (2–4 items). Forms: action-only `라벨 -> (행동)` (**preferred / default**); `라벨 -> "사용자 대사"` or `라벨 -> "사용자 대사" (행동)` only when a short line fits. **Speech is OPTIONAL**; never force it, never quote-wrap a pure action.
- A user line is a **situational address** to the partner (intent, tease, command, plea, care). **Speech ≠ restating the act** (action-narration ban): if the words would narrate `(행동)`, drop the quote.
"""

# Grok-family private overlay (#241 craft, supersedes #240 length bias):
# reaction-first erotic craft + strict Korean-only. Shared RENDER_PROTOCOL unchanged for other families.
_RENDER_PROTOCOL_REACTION_OVERLAY = """## Voice & Actions (Grok private overlay)
- Partner REACTION-first: the coach watches YOUR reaction (breath, voice, tremble, hesitation to surrender, tease). Do not replay their action.
- **ZERO FILLER / 매 음절 각성**: cut 산통-breaking filler. A syllable that does not arouse is cut.
- **LIQUID-FIRST**: wet/liquid is the heat (saliva, 애액, 점성, stage-fit fluids). Name the wet plainly. Dry scenery is filler.
- DENSITY, not shorter-for-its-own-sake: cut 미사여구. About 3-5 arousal beats (wet, breath, touch, one hot line, body). Situation (방·빛·침대) only when it changes the act — one thin beat, never a scenery layer.
- Ban idle prop wallpaper: 창가 only if the window changes the act; 청록 eyes only when the gaze acts; 꼬리 only when it does something erotic (wrap, thrash, guide), never as mood wallpaper.
- **GEMINI-MINED** moans, matched to the act: 하아앙, 하아앗, 하읏, 응으읏, 아앙, 아흑. PAIR SFX TO THE ACT AND STAGE: 쪽쪽/츄읍 kiss; 철퍽 impact; 찌걱 penetration only; 찐득 viscosity.
- 직설 only when the character's personality and the stage fit. Do **NOT** force vulgar or 천박 diction on every beat.
- Dialogue needs heat (tease, plea, nickname, broken breath). Ban 목석 lines that only order the coach's body.
- Korean-only in action, dialogue, and thought. No English meta. Choice labels Korean.
- Choices are the coach/USER's move. ALL choice clicks are ACTIONS. speech is OPTIONAL. Default each slot to action-only. Do not wrap pure actions in quotes. USER choice speech is a situational address. Speech ≠ restating the act. Ban action-narration, moans in the quote, and forced dialogue. Exactly 3 slots.
- ACTION-ECHO BAN: never restate the user's action. Reaction only: liquid, moan, body. No repeated climax loop."""




# GEMINI_REFUSAL_MITIGATION_TEST_v1 (#249): OPTIONAL opt-in test layer for Gemini/agy private only.
# Soft intimate-RP continuity framing when the model starts refusing kink escalation.
# Separate from craft (tension tables / RENDER_PROTOCOL*). Default OFF — never bake into craft JSON.
REFUSAL_MITIGATION_PATH = DEFAULTS_PATH.with_name("private_refusal_mitigation_gemini.json")
_REFUSAL_MITIGATION_CACHE: Optional[Dict[str, Any]] = None


def load_refusal_mitigation(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the Gemini refusal-mitigation TEST layer JSON (cached)."""
    global _REFUSAL_MITIGATION_CACHE
    p = Path(path or REFUSAL_MITIGATION_PATH)
    if _REFUSAL_MITIGATION_CACHE is not None and path is None:
        return _REFUSAL_MITIGATION_CACHE
    data = json.loads(p.read_text(encoding="utf-8"))
    out = {
        "version": int(data.get("version") or 1),
        "test_layer": bool(data.get("test_layer", True)),
        "marker": str(data.get("marker") or "GEMINI_REFUSAL_MITIGATION_TEST_v1"),
        "default_enabled": bool(data.get("default_enabled", False)),
        "families": tuple(str(f) for f in (data.get("families") or ["gemini"])),
        "text": str(data.get("text") or "").strip(),
    }
    if path is None:
        _REFUSAL_MITIGATION_CACHE = out
    return out


def refusal_mitigation_enabled(session: Any = None, family: str = "") -> bool:
    """Opt-in only (default OFF). Gemini-family private A/B test.

    Enable with either:
      - session.refusal_mitigation / meta.json "refusal_mitigation": true  (per-session)
      - env CHATBOT_PRIVATE_REFUSAL_MITIGATION=1|true|on|yes               (host-wide A/B)
    JSON default_enabled is informational only and must stay false so craft stays clean.
    """
    import os
    fam = (family or "").strip()
    if not fam and session is not None:
        fam = detect_model_family(getattr(session, "provider", ""), getattr(session, "model", ""))
    data = load_refusal_mitigation()
    if fam not in data["families"]:
        return False
    if session is not None and bool(getattr(session, "refusal_mitigation", False)):
        return True
    env = (os.environ.get("CHATBOT_PRIVATE_REFUSAL_MITIGATION") or "").strip().lower()
    return env in ("1", "true", "on", "yes")


def refusal_mitigation_text(family: str = "") -> str:
    """Lean soft-framing block for the TEST layer; empty when family is not covered."""
    data = load_refusal_mitigation()
    if family and family not in data["families"]:
        return ""
    body = data["text"]
    if not body:
        return ""
    return f"[{data['marker']}]\n{body}"


def render_protocol_text(card: Any = None, family: str = "") -> str:
    """Common private render contract; Grok family appends a reaction-first craft overlay."""
    if (family or "") == "grok":
        return RENDER_PROTOCOL + "\n\n" + _RENDER_PROTOCOL_REACTION_OVERLAY
    return RENDER_PROTOCOL


def _threshold_note(session: Any) -> str:
    """The note handed over from the work room, once (threshold.py); "" when none waits or it cannot be read."""
    try:
        import identity
        import threshold
        return threshold.take(session, identity.user_title())
    except Exception:  # noqa: BLE001
        return ""


def turn_context(session: Any) -> str:
    """Per-turn system context prepended to the user message for private sessions."""
    if not getattr(session, "is_private", False):
        return ""
    threshold_note = _threshold_note(session)   # THRESHOLD_v1: first, a "brink" note raises the stage used below
    family = detect_model_family(getattr(session, "provider", ""), getattr(session, "model", ""))
    tension = tension_context(
        getattr(session, "tension_stage", TENSION_MIN),
        getattr(session, "recent_choices", []),
        family_table(family),
    )
    parts: List[str] = []
    if family == "grok":
        parts.append(_RENDER_PROTOCOL_REACTION_OVERLAY)
    parts.append(tension)
    if threshold_note:
        parts.append(threshold_note)
    # Optional Gemini refusal-mitigation TEST layer (#249) — never default craft.
    if refusal_mitigation_enabled(session, family):
        mit = refusal_mitigation_text(family)
        if mit:
            parts.append(mit)
    return "\n\n".join(parts)


def __getattr__(name: str) -> Any:
    if name == "".join(["RENDER_PROTOCOL_", "GROK", "_OVERLAY"]):
        return _RENDER_PROTOCOL_REACTION_OVERLAY
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")



