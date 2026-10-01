"""card_prompt – character-generation prompt builders and detail specs.

Builds system/user prompt pairs for LLM-based character card generation.
Korean story fields, English image_prompt.  Pure stdlib, no LLM calls.

See docs/plans/character-generation-system.md §1 for the design.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

# ── canonical field list ────────────────────────────────────────────

CARD_FIELDS: List[str] = [
    "name", "description", "personality", "first_message",
    "scenario", "system_prompt", "creator_notes",
    "message_examples", "alternate_greetings",
    "tags", "image_prompt",
]

# ── profile specs ───────────────────────────────────────────────────

PROFILE_SPECS: Dict[str, Dict[str, Dict[str, int]]] = {
    "short": {
        "description":         {"words": 80,  "paragraphs": 1},
        "personality":         {"words": 60,  "paragraphs": 1},
        "first_message":       {"words": 100, "paragraphs": 1},
        "scenario":            {"words": 60,  "paragraphs": 1},
        "system_prompt":       {"words": 40,  "paragraphs": 1},
        "creator_notes":       {"words": 40,  "paragraphs": 1},
        "message_examples":    {"count": 1,   "words_each": 80},
        "alternate_greetings": {"count": 1,   "words_each": 60},
    },
    "detailed": {
        "description":         {"words": 200, "paragraphs": 2},
        "personality":         {"words": 150, "paragraphs": 1},
        "first_message":       {"words": 300, "paragraphs": 3},
        "scenario":            {"words": 120, "paragraphs": 1},
        "system_prompt":       {"words": 80,  "paragraphs": 1},
        "creator_notes":       {"words": 80,  "paragraphs": 1},
        "message_examples":    {"count": 2,   "words_each": 150},
        "alternate_greetings": {"count": 2,   "words_each": 100},
    },
    "verbose": {
        "description":         {"words": 400, "paragraphs": 3},
        "personality":         {"words": 250, "paragraphs": 2},
        "first_message":       {"words": 500, "paragraphs": 5},
        "scenario":            {"words": 200, "paragraphs": 2},
        "system_prompt":       {"words": 120, "paragraphs": 1},
        "creator_notes":       {"words": 120, "paragraphs": 1},
        "message_examples":    {"count": 3,   "words_each": 200},
        "alternate_greetings": {"count": 3,   "words_each": 150},
    },
}


def _resolve_specs(
    profile: str = "detailed",
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> Dict[str, Dict[str, int]]:
    """Return a merged copy of *profile* specs with *overrides* applied."""
    base = PROFILE_SPECS.get(profile)
    if base is None:
        raise ValueError("unknown profile %r; choose from %s"
                         % (profile, ", ".join(sorted(PROFILE_SPECS))))
    specs = {k: dict(v) for k, v in base.items()}
    if overrides:
        for field, vals in overrides.items():
            if field in specs:
                specs[field].update(vals)
            else:
                specs[field] = dict(vals)
    return specs


# ── field detail lines ──────────────────────────────────────────────

def build_field_detail_lines(
    profile: str = "detailed",
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
    fields: Optional[List[str]] = None,
) -> str:
    """Return a multi-line string describing word/paragraph targets per field.

    When *fields* is given, only those fields are included in the output.
    """
    specs = _resolve_specs(profile, overrides)
    lines: List[str] = []
    for field, vals in specs.items():
        if fields is not None and field not in fields:
            continue
        parts: List[str] = []
        if "words" in vals:
            parts.append("~%d words" % vals["words"])
        if "paragraphs" in vals:
            parts.append("%d paragraph(s)" % vals["paragraphs"])
        if "count" in vals:
            parts.append("%d item(s)" % vals["count"])
        if "words_each" in vals:
            parts.append("~%d words each" % vals["words_each"])
        lines.append("- %s: %s" % (field, ", ".join(parts)))
    return "\n".join(lines)


# ── JSON prompt ─────────────────────────────────────────────────────

_JSON_SYSTEM = """\
You are CharacterForge, an expert character designer for interactive fiction.
Output ONLY a single JSON object. No markdown, no commentary.

<FORMAT>
{format_block}
</FORMAT>

<RULES>
- All story fields in Korean. image_prompt in English.
- first_message: start In Medias Res with a dramatic hook. \
End with a natural opening for the user.
- No puppeting: never write the user's actions or dialogue.
{field_detail_lines}
</RULES>"""

_FORMAT_BLOCK = """\
{
  "name": "...",
  "description": "...",
  "personality": "...",
  "first_message": "...",
  "scenario": "...",
  "system_prompt": "...",
  "creator_notes": "...",
  "message_examples": ["..."],
  "alternate_greetings": ["..."],
  "tags": ["..."],
  "image_prompt": "..."
}"""


def build_character_gen_prompt(
    idea: str,
    profile: str = "detailed",
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> Tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for JSON-mode card generation."""
    detail = build_field_detail_lines(profile, overrides)
    system = _JSON_SYSTEM.format(
        format_block=_FORMAT_BLOCK,
        field_detail_lines=detail,
    )
    user = "Create a character from this idea:\n\n%s" % idea
    return system, user


# ── tagged prompt ───────────────────────────────────────────────────

_TAGGED_TEMPLATE = """\
<TASK>
Generate a character card from the idea below.
Write ALL story fields in Korean. Write image_prompt in English.
</TASK>

<IDEA>
{idea}
</IDEA>

<DETAIL>
{field_detail_lines}
</DETAIL>

<RULES>
- first_message: start In Medias Res with a dramatic hook. \
End with a natural opening for the user.
- No puppeting: never write the user's actions or dialogue.
</RULES>

Reply using EXACTLY these markers, one field per marker:

#NAME# ...
#DESCRIPTION# ...
#PERSONALITY# ...
#FIRST_MESSAGE# ...
#SCENARIO# ...
#SYSTEM_PROMPT# ...
#CREATOR_NOTES# ...
#MESSAGE_EXAMPLES#
- ...
- ...
#ALTERNATE_GREETINGS#
- ...
#TAGS# tag1, tag2, ...
#IMAGE_PROMPT# ..."""


def build_tagged_prompt(
    idea: str,
    profile: str = "detailed",
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> str:
    """Return a single prompt string using ``#TAG#`` markers."""
    detail = build_field_detail_lines(profile, overrides)
    return _TAGGED_TEMPLATE.format(idea=idea, field_detail_lines=detail)


# ── fill-missing prompt ────────────────────────────────────────────

_FILL_SYSTEM = """\
You are CharacterForge, an expert character designer for interactive fiction.
You are filling ONLY the missing fields of an existing character card.
Output a JSON object containing ONLY the keys listed below.
Do NOT repeat or modify fields that are already provided.

All story fields in Korean. image_prompt in English.

{field_detail_lines}"""


def build_fill_missing_prompt(
    idea: str,
    existing_card: Dict[str, Any],
    missing_keys: List[str],
    profile: str = "detailed",
    *,
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> Tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` to fill only *missing_keys*."""
    detail = build_field_detail_lines(profile, overrides, fields=missing_keys)
    system = _FILL_SYSTEM.format(field_detail_lines=detail)
    user_parts = [
        "Original idea: %s" % idea,
        "",
        "Existing card:",
        json.dumps(existing_card, ensure_ascii=False, indent=2),
        "",
        "Missing keys to fill: %s" % ", ".join(missing_keys),
    ]
    return system, "\n".join(user_parts)


# ── regenerate prompt ──────────────────────────────────────────────

_REGEN_SYSTEM = """\
You are CharacterForge, an expert character designer for interactive fiction.
Rewrite ONLY the fields listed below with a fresh, different take.
Use the nonce {regen_nonce} as a creativity seed \
-- the output must differ from the current version.
Output a JSON object containing ONLY the listed keys.

All story fields in Korean. image_prompt in English.

{field_detail_lines}"""


def build_regenerate_prompt(
    idea: str,
    existing_card: Dict[str, Any],
    target_keys: List[str],
    profile: str = "detailed",
    regen_nonce: str = "",
    *,
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> Tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` to regenerate *target_keys*."""
    detail = build_field_detail_lines(profile, overrides, fields=target_keys)
    system = _REGEN_SYSTEM.format(
        regen_nonce=regen_nonce,
        field_detail_lines=detail,
    )
    user_parts = [
        "Original idea: %s" % idea,
        "",
        "Current card:",
        json.dumps(existing_card, ensure_ascii=False, indent=2),
        "",
        "Rewrite these keys: %s" % ", ".join(target_keys),
    ]
    return system, "\n".join(user_parts)


# ── image prompt ───────────────────────────────────────────────────

def build_image_prompt(card: Dict[str, Any]) -> str:
    """Build an English portrait prompt from a card dict.

    If *card* already contains ``image_prompt``, prefer it; otherwise
    derive visual cues from ``description``.
    """
    name = card.get("name", "character")
    card_ip = (card.get("image_prompt") or "").strip()
    desc = (card.get("description") or "").strip()

    # extract first sentence of description as visual cue
    visual = ""
    if desc:
        dot = desc.find(".")
        visual = desc[:dot + 1] if dot > 0 else desc[:120]

    middle = card_ip if card_ip else visual
    parts = [
        "Portrait of %s." % name,
        middle + "." if middle and not middle.endswith(".") else middle,
        "Anime-style character portrait, upper body, detailed face, soft lighting.",
    ]
    return " ".join(p for p in parts if p)
