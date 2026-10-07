"""card_parse – dual parser and fallback machine for character card LLM output.

Clean port of ST-CardGen ``domain/character/parse.ts`` with the following
differences from the original:

* **Renamed tags**: ``EXAMPLE_MESSAGES`` → ``MESSAGE_EXAMPLES`` (matches the
  prompt template field order used in card_prompt.py).
* **PE extension tags**: ``SYSTEM_PROMPT``, ``ALTERNATE_GREETINGS`` — not
  present in the original; added for Private Engine card generation.
* **No JSON normalisation on the happy path**: when the JSON parse succeeds
  and all required fields are present the dict is returned as-is; the
  original applies field-level coercion/defaults.

Pure stdlib — no third-party dependencies.

Pipeline:
  1. ``try_parse_json`` — markdown ```json block, then raw ``json.loads``.
  2. ``parse_tagged_sections`` — ``#TAG#`` line-by-line state machine.
  3. ``classify_raw_failure`` — truncated / invalid_json / schema_mismatch.
  4. ``build_character_from_tagged`` — section map → character dict.
  5. ``parse_character_response`` — JSON → tagged fallback orchestrator.

See docs/plans/archive/2026/character-generation-system.md §1.3 for the design.
"""

import json
import re
from typing import Any, Dict, List, Optional, Sequence

# ── tag registry ────────────────────────────────────────────────────
# ST-CardGen original tags + PE extensions (SYSTEM_PROMPT,
# ALTERNATE_GREETINGS).  Order follows the tagged-prompt template
# in card_prompt.py.

TAGS: List[str] = [
    "NAME",
    "DESCRIPTION",
    "PERSONALITY",
    "FIRST_MESSAGE",
    "SCENARIO",
    "SYSTEM_PROMPT",          # PE extension
    "CREATOR_NOTES",
    "MESSAGE_EXAMPLES",       # ST original: EXAMPLE_MESSAGES (renamed)
    "ALTERNATE_GREETINGS",    # PE extension
    "TAGS",
    "IMAGE_PROMPT",
    "NEGATIVE_PROMPT",
]

_TAG_SET = frozenset(TAGS)

_TAG_RE = re.compile(r"^#([A-Z_]+)#$")

# ── JSON extraction ─────────────────────────────────────────────────

_JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_block(raw: str) -> Optional[str]:
    """Extract content from a ````json ... ```` markdown fence."""
    m = _JSON_BLOCK_RE.search(raw)
    return m.group(1).strip() if m else None


def try_parse_json(raw: str) -> Any:
    """Try to parse *raw* as JSON.

    Attempts, in order:
      1. Content inside a ````json … ```` markdown fence.
      2. The whole string, stripped.

    Returns the parsed object or ``None``.
    """
    candidates: List[str] = []
    block = extract_json_block(raw)
    if block:
        candidates.append(block)
    candidates.append(raw.strip())

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ── failure classification ──────────────────────────────────────────

def classify_raw_failure(
    raw: str,
    parsed: Optional[Any] = None,
) -> str:
    """Classify why *raw* could not produce a valid character card.

    Returns one of:
      - ``"schema_mismatch"``: valid JSON/object but missing required fields.
      - ``"truncated"``: JSON or markdown code fence cut off before completion.
      - ``"invalid_json"``: unparseable syntax or non-JSON output.
    """
    if parsed is None:
        parsed = try_parse_json(raw)
    if isinstance(parsed, dict):
        return "schema_mismatch"

    t = raw.strip()
    if t.startswith("```"):
        if not t.endswith("```") or t.count("```") < 2:
            return "truncated"
        inner = extract_json_block(raw)
        if inner and inner.startswith("{") and not inner.endswith("}"):
            return "truncated"

    # If the string starts with a valid, completed JSON object/array but has
    # trailing prose, classify as invalid_json (not truncated).
    if t.startswith(("{", "[")):
        try:
            _, idx = json.JSONDecoder().raw_decode(t)
            if idx < len(t):
                return "invalid_json"
        except (json.JSONDecodeError, ValueError):
            pass

    if t.startswith("{") and not t.endswith("}"):
        return "truncated"
    if t.startswith("[") and not t.endswith("]"):
        return "truncated"
    return "invalid_json"


# ── tagged-section state machine ────────────────────────────────────

def parse_tagged_sections(raw: str) -> Dict[str, str]:
    """Parse ``#TAG#`` delimited sections with a line-by-line state machine.

    Only tags in the ``TAGS`` registry are recognised; unknown markers
    are treated as plain text inside the current section.  Escaped
    quotes and broken newlines are handled naturally because the parser
    never interprets content — it only looks for marker lines.

    Returns ``{TAG_NAME: section_body, …}`` with body text trimmed.
    """
    sections: Dict[str, str] = {}
    current: Optional[str] = None
    buffer: List[str] = []

    def _flush() -> None:
        nonlocal current, buffer
        if current is not None:
            sections[current] = "\n".join(buffer).strip()
        buffer = []

    for line in re.split(r"\r?\n", raw):
        trimmed = line.strip()
        m = _TAG_RE.match(trimmed)
        if m and m.group(1) in _TAG_SET:
            _flush()
            current = m.group(1)
            continue
        if current is not None:
            buffer.append(line)

    _flush()
    return sections


# ── tagged sections → character dict ────────────────────────────────

def _parse_tag_list(value: str) -> List[str]:
    """Split a comma- or newline-separated tag string."""
    return [t.strip() for t in re.split(r"[,\n]", value) if t.strip()]


def build_character_from_tagged(
    sections: Dict[str, str],
) -> Dict[str, Any]:
    """Convert a section map from ``parse_tagged_sections`` into a
    character card dict keyed by canonical field names.

    Tag names map to card fields:

    ===================  ==================
    Tag                  Card field
    ===================  ==================
    NAME                 name
    DESCRIPTION          description
    PERSONALITY          personality
    FIRST_MESSAGE        first_message
    SCENARIO             scenario
    SYSTEM_PROMPT        system_prompt
    CREATOR_NOTES        creator_notes
    MESSAGE_EXAMPLES     message_examples
    ALTERNATE_GREETINGS  alternate_greetings
    TAGS                 tags
    IMAGE_PROMPT         image_prompt
    NEGATIVE_PROMPT      negative_prompt
    ===================  ==================
    """

    def _get(key: str) -> str:
        return (sections.get(key) or "").strip()

    result: Dict[str, Any] = {
        "name": _get("NAME"),
        "description": _get("DESCRIPTION"),
        "personality": _get("PERSONALITY"),
        "first_message": _get("FIRST_MESSAGE"),
        "scenario": _get("SCENARIO"),
        "system_prompt": _get("SYSTEM_PROMPT"),
        "creator_notes": _get("CREATOR_NOTES"),
        "message_examples": _get("MESSAGE_EXAMPLES"),
        "alternate_greetings": _get("ALTERNATE_GREETINGS"),
        "tags": _parse_tag_list(sections.get("TAGS", "")),
        "image_prompt": _get("IMAGE_PROMPT"),
        "negative_prompt": _get("NEGATIVE_PROMPT"),
    }

    return result


# ── top-level orchestrator ──────────────────────────────────────────

# Required fields that must be non-empty for a card to be considered
# valid (mirrors CharacterGenSchema required strings).
_REQUIRED_FIELDS: Sequence[str] = (
    "name", "description", "personality", "first_message", "scenario",
)


def parse_character_response(raw: str) -> Dict[str, Any]:
    """Parse an LLM response into a character card dict.

    Tries JSON first, then falls back to ``#TAG#`` sections.
    Raises ``ValueError`` with a failure class
    (``truncated``, ``invalid_json``, or ``schema_mismatch``)
    if neither parse succeeds or the result is missing required fields.
    """
    # ── 1st pass: JSON ──────────────────────────────────────────
    parsed = try_parse_json(raw)
    if isinstance(parsed, dict):
        # Minimal schema check: required string fields present.
        if all(parsed.get(f) for f in _REQUIRED_FIELDS):
            return parsed

    # ── 2nd pass: tagged sections ───────────────────────────────
    sections = parse_tagged_sections(raw)
    if not sections:
        failure = classify_raw_failure(raw, parsed)
        raise ValueError(
            f"Unable to parse LLM response as JSON or tagged sections "
            f"(failure class: {failure})"
        )

    result = build_character_from_tagged(sections)

    # Light validation.
    missing = [f for f in _REQUIRED_FIELDS if not result.get(f)]
    if missing:
        raise ValueError(
            f"Tagged response missing required fields: {missing} "
            f"(failure class: schema_mismatch)"
        )

    return result
