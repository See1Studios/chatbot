"""card_prompt – character-generation prompt builders and detail specs.

1:1 clean port of ST-CardGen ``domain/character/prompt.ts`` and
``domain/character/fieldDetail.ts``.  Korean story fields, English
image_prompt / negative_prompt.  Pure stdlib, no LLM calls.

See docs/plans/character-generation-system.md §1 for the design.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

# ── canonical field list ────────────────────────────────────────────

CARD_FIELDS: List[str] = [
    "name", "description", "personality", "first_message",
    "scenario", "system_prompt", "creator_notes",
    "message_examples", "alternate_greetings",
    "tags", "image_prompt", "negative_prompt",
]

# ── profile specs (ST-CardGen fieldDetail.ts 1:1 port) ──────────

# Each field maps to quantitative targets:
#   min_words / max_words  – word count range
#   min_chars              – minimum character count
#   min_paragraphs / max_paragraphs – paragraph range
#   min_count / max_count  – item count range (lists)
#   min_pairs / max_pairs  – dialogue pair range (mes_example)

PROFILE_SPECS: Dict[str, Dict[str, Dict[str, int]]] = {
    "short": {
        "description":         {"min_words": 60,  "max_words": 120,
                                "min_paragraphs": 1, "max_paragraphs": 2},
        "personality":         {"min_words": 40,  "max_words": 80,
                                "min_paragraphs": 1, "max_paragraphs": 1},
        "first_message":       {"min_words": 150, "max_words": 240,
                                "min_chars": 700,
                                "min_paragraphs": 2, "max_paragraphs": 3},
        "scenario":            {"min_words": 40,  "max_words": 80,
                                "min_paragraphs": 1, "max_paragraphs": 1},
        "system_prompt":       {"min_words": 30,  "max_words": 60,
                                "min_paragraphs": 1, "max_paragraphs": 1},
        "creator_notes":       {"min_words": 30,  "max_words": 60,
                                "min_paragraphs": 1, "max_paragraphs": 1},
        "message_examples":    {"min_pairs": 1,   "max_pairs": 2},
        "alternate_greetings": {"min_count": 1,   "max_count": 1},
        "tags":                {"min_count": 4,   "max_count": 8},
    },
    "detailed": {
        "description":         {"min_words": 150, "max_words": 280,
                                "min_paragraphs": 2, "max_paragraphs": 3},
        "personality":         {"min_words": 100, "max_words": 180,
                                "min_paragraphs": 1, "max_paragraphs": 2},
        "first_message":       {"min_words": 220, "max_words": 360,
                                "min_chars": 900,
                                "min_paragraphs": 3, "max_paragraphs": 5},
        "scenario":            {"min_words": 80,  "max_words": 150,
                                "min_paragraphs": 1, "max_paragraphs": 2},
        "system_prompt":       {"min_words": 50,  "max_words": 100,
                                "min_paragraphs": 1, "max_paragraphs": 1},
        "creator_notes":       {"min_words": 50,  "max_words": 100,
                                "min_paragraphs": 1, "max_paragraphs": 1},
        "message_examples":    {"min_pairs": 2,   "max_pairs": 3},
        "alternate_greetings": {"min_count": 2,   "max_count": 2},
        "tags":                {"min_count": 6,   "max_count": 10},
    },
    "verbose": {
        "description":         {"min_words": 300, "max_words": 500,
                                "min_paragraphs": 3, "max_paragraphs": 4},
        "personality":         {"min_words": 180, "max_words": 300,
                                "min_paragraphs": 2, "max_paragraphs": 3},
        "first_message":       {"min_words": 360, "max_words": 560,
                                "min_chars": 1200,
                                "min_paragraphs": 4, "max_paragraphs": 6},
        "scenario":            {"min_words": 150, "max_words": 250,
                                "min_paragraphs": 1, "max_paragraphs": 2},
        "system_prompt":       {"min_words": 80,  "max_words": 150,
                                "min_paragraphs": 1, "max_paragraphs": 1},
        "creator_notes":       {"min_words": 80,  "max_words": 150,
                                "min_paragraphs": 1, "max_paragraphs": 1},
        "message_examples":    {"min_pairs": 3,   "max_pairs": 5},
        "alternate_greetings": {"min_count": 2,   "max_count": 3},
        "tags":                {"min_count": 8,   "max_count": 12},
    },
}

# ── default negative prompt (server-injected preset) ────────────

DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, deformed, bad anatomy, extra limbs, "
    "mutated hands, poorly drawn face, watermark, text, signature"
)


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

def _format_spec_line(field: str, vals: Dict[str, int]) -> Optional[str]:
    """Format one field's spec into the ST-CardGen style detail line."""
    parts: List[str] = []
    if "min_words" in vals and "max_words" in vals:
        parts.append("%d\u2013%d words" % (vals["min_words"],
                                           vals["max_words"]))
    if "min_chars" in vals:
        parts.append("min %d characters" % vals["min_chars"])
    if "min_paragraphs" in vals and "max_paragraphs" in vals:
        mn, mx = vals["min_paragraphs"], vals["max_paragraphs"]
        parts.append("%d\u2013%d paragraphs" % (mn, mx) if mn != mx
                     else "%d paragraph(s)" % mn)
    if "min_pairs" in vals and "max_pairs" in vals:
        parts.append("%d\u2013%d dialogue pairs" % (vals["min_pairs"],
                                                    vals["max_pairs"]))
    if "min_count" in vals and "max_count" in vals:
        mn, mx = vals["min_count"], vals["max_count"]
        parts.append("%d\u2013%d items" % (mn, mx) if mn != mx
                     else "%d item(s)" % mn)
    if not parts:
        return None
    suffix = ""
    if "min_paragraphs" in vals and vals.get("max_paragraphs", 0) > 1:
        suffix = ". Use \\n\\n between paragraphs"
    return "- %s: %s%s" % (field, ", ".join(parts), suffix)


def build_field_detail_lines(
    profile: str = "detailed",
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
    fields: Optional[List[str]] = None,
) -> str:
    """Return a multi-line string describing quantitative targets per field.

    Output matches ST-CardGen ``fieldDetail.ts`` format::

        - first_message: 220-360 words, min 900 characters, ...

    When *fields* is given, only those fields appear in the output.
    """
    specs = _resolve_specs(profile, overrides)
    lines: List[str] = []
    for field, vals in specs.items():
        if fields is not None and field not in fields:
            continue
        line = _format_spec_line(field, vals)
        if line:
            lines.append(line)
    return "\n".join(lines)


# ── first_message quality rules (In Medias Res & Hook) ──────────

_FIRST_MES_RULES = """\
- first_message MUST begin In Medias Res: open mid-scene with vivid \
sensory detail (location, sounds, weather, lighting). \
NO greetings like "Hello" or "Hi there".
- Include at least one line of quoted character dialogue.
- End with a Hook: a question, urgent request, or sudden event that \
naturally invites the user to respond.
- Anti-puppeting: NEVER write the user's thoughts, speech, or actions."""


# ── JSON prompt ─────────────────────────────────────────────────────

_JSON_SYSTEM = """\
You are CharacterForge, an expert character designer for interactive fiction.
Output ONLY a single JSON object. No markdown, no commentary.

<FORMAT>
{format_block}
</FORMAT>

<RULES>
- All story fields in Korean. image_prompt and negative_prompt in English.
{first_mes_rules}
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
  "image_prompt": "...",
  "negative_prompt": "..."
}"""


def build_character_gen_prompt(
    idea: str,
    profile: str = "detailed",
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
    *,
    use_default_negative: bool = False,
) -> Tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for JSON-mode card generation.

    When *use_default_negative* is ``True``, the prompt tells the model to
    skip writing ``negative_prompt`` (the caller injects the default).
    """
    detail = build_field_detail_lines(profile, overrides)
    neg_note = ""
    if use_default_negative:
        neg_note = ("\n- Omit negative_prompt; "
                    "a default will be injected automatically.")
    system = _JSON_SYSTEM.format(
        format_block=_FORMAT_BLOCK,
        first_mes_rules=_FIRST_MES_RULES,
        field_detail_lines=detail + neg_note,
    )
    user = "Create a character from this idea:\n\n%s" % idea
    return system, user


# ── tagged prompt ───────────────────────────────────────────────────

_TAGGED_TEMPLATE = """\
<TASK>
Generate a character card from the idea below.
Write ALL story fields in Korean. Write image_prompt and \
negative_prompt in English.
</TASK>

<IDEA>
{idea}
</IDEA>

<DETAIL>
{field_detail_lines}
</DETAIL>

<RULES>
{first_mes_rules}
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
#IMAGE_PROMPT# ...
#NEGATIVE_PROMPT# ..."""


def build_tagged_prompt(
    idea: str,
    profile: str = "detailed",
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> str:
    """Return a single prompt string using ``#TAG#`` markers."""
    detail = build_field_detail_lines(profile, overrides)
    return _TAGGED_TEMPLATE.format(
        idea=idea,
        field_detail_lines=detail,
        first_mes_rules=_FIRST_MES_RULES,
    )


# ── fill-missing prompt ────────────────────────────────────────────

_FILL_SYSTEM = """\
You are CharacterForge, an expert character designer for interactive fiction.
You are filling ONLY the missing fields of an existing character card.
Output a JSON object containing ONLY the keys listed below.
Do NOT repeat or modify fields that are already provided.

All story fields in Korean. image_prompt and negative_prompt in English.

{field_detail_lines}"""


def build_fill_missing_prompt(
    idea: str,
    existing_card: Dict[str, Any],
    missing_keys: List[str],
    profile: str = "detailed",
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
{seed_line}
Output a JSON object containing ONLY the listed keys.

All story fields in Korean. image_prompt and negative_prompt in English.

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
    if regen_nonce and regen_nonce.strip():
        seed_line = (
            "Use the nonce %s as a creativity seed "
            "-- the output must differ from the current version."
            % regen_nonce.strip()
        )
    else:
        seed_line = "The output must differ from the current version."
    system = _REGEN_SYSTEM.format(
        seed_line=seed_line,
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

def _has_hangul(text: str) -> bool:
    """Return True if text contains Hangul syllables or jamo."""
    for ch in text:
        cp = ord(ch)
        if (0xAC00 <= cp <= 0xD7A3 or
            0x1100 <= cp <= 0x11FF or
            0x3130 <= cp <= 0x318F):
            return True
    return False


def build_image_prompt(card: Dict[str, Any]) -> str:
    """Build an English portrait prompt from a card dict.

    If *card* already contains ``image_prompt``, prefer it (as long as it
    contains no Hangul); otherwise derive visual cues from English
    ``description``. If the description contains Hangul, visual cues are
    omitted to guarantee an English-only portrait prompt.
    """
    name = (card.get("name") or "").strip() or "character"
    card_ip = (card.get("image_prompt") or "").strip()
    desc = (card.get("description") or "").strip()

    visual = ""
    if card_ip:
        if not _has_hangul(card_ip):
            visual = card_ip
    elif desc and not _has_hangul(desc):
        dot = desc.find(".")
        visual = desc[:dot + 1] if dot > 0 else desc[:120]

    cue = ""
    if visual:
        cue = visual if visual.endswith((".", "!", "?")) else (visual + ".")

    parts = [
        "Portrait of %s." % name,
        cue,
        "Anime-style character portrait, upper body, "
        "detailed face, soft lighting.",
    ]
    return " ".join(p for p in parts if p)
