"""Per-character relationship continuity (docs/plans/character-memory-adapter.md).

Private sessions only. Four slots: progress, promises, preferences, taboos.
Affection numbers stay in private-mode. The house MEMORY.md is not used.
Durable explicit tags live in characters/<id>/relationship.md (user data, not git).
Untagged private-memory bullets stay one Continuity line. Display hints may
label a bullet; only an explicit tag is written to the slot file.
"""
import os
import re

import platform_compat

SLOT_ORDER = ("progress", "promises", "preferences", "taboos")
LABELS = {
    "progress": "Progress",
    "promises": "Promises",
    "preferences": "Preferences",
    "taboos": "Taboos",
}
_HEADINGS = {label: key for key, label in LABELS.items()}
_TAG_MAP = {
    "progress": "progress",
    "promise": "promises",
    "promises": "promises",
    "pref": "preferences",
    "prefs": "preferences",
    "preference": "preferences",
    "preferences": "preferences",
    "taboo": "taboos",
    "taboos": "taboos",
}
_TAG = re.compile(
    r"^(progress|promise|promises|pref|prefs|preference|preferences|taboo|taboos)\s*[:：]\s*(.+)$",
    re.I,
)
# NO_GUESS_SLOT_v1: a line goes to a slot only by its explicit tag above -- keyword hints (Korean and English words)
# sorted the same line differently by language, so they are gone.
_HINTS = ()
_SECRETISH = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|bearer|sk-[A-Za-z0-9]{8,}|-----BEGIN)",
    re.I,
)
_DATE = re.compile(r"^\[\d{4}-\d{2}-\d{2}\]\s+")
ITEM_MAX = 200
SLOT_SHOWN = 6
NOTES_SHOWN = 24
FILE_CAP = 12


def path(cid, ws=None):
    import characters
    return characters.card_path(cid, ws).parent / "relationship.md"


def _body(line):
    text = re.sub(r"\s+", " ", str(line or "")).strip()
    text = re.sub(r"^[-*]\s+", "", text)
    return text[:ITEM_MAX].strip()


def _undated(text):
    return _DATE.sub("", text).strip()


def classify(line):
    """(slot, display text). Slot is empty when the line is only continuity."""
    body = _body(line)
    tagged = _TAG.match(_undated(body))
    if tagged:
        slot = _TAG_MAP[tagged.group(1).lower()]
        fact = tagged.group(2).strip()[:ITEM_MAX]
        if _DATE.match(body):
            shown = body[: body.find("]") + 1] + " " + fact
        else:
            shown = fact
        return slot, shown.strip()
    low = _undated(body).lower()
    for slot, keys in _HINTS:
        if any(k.lower() in low for k in keys):
            return slot, body
    return "", body


def _empty():
    return {key: [] for key in SLOT_ORDER}


def parse_file(text):
    slots = _empty()
    current = ""
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if stripped.startswith("## "):
            current = _HEADINGS.get(stripped[3:].strip(), "")
            continue
        if not current or not stripped.startswith("- "):
            continue
        item = _body(stripped)
        if item and item.lower() not in {x.lower() for x in slots[current]}:
            slots[current].append(item)
    return slots


def load(cid, ws=None):
    try:
        return parse_file(path(cid, ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()


def _write(dest, slots):
    lines = ["# Relationship", ""]
    for key in SLOT_ORDER:
        items = slots[key]
        if not items:
            continue
        lines.append("## " + LABELS[key])
        lines.extend("- " + item for item in items)
        lines.append("")
    tmp = dest.with_name(".relationship.%d.tmp" % os.getpid())
    platform_compat.write_text(tmp, "\n".join(lines).rstrip() + "\n", encoding="utf-8")
    tmp.replace(dest)


def remember_slots(cid, lines, ws=None):
    """Store explicitly tagged lines. Untagged lines stay in private-memory only."""
    dest = path(cid, ws)
    if not cid or not dest.parent.is_dir():
        return 0
    slots = load(cid, ws)
    added = 0
    for raw in lines or []:
        if _SECRETISH.search(str(raw)):
            continue
        if not _TAG.match(_undated(_body(raw))):
            continue
        slot, shown = classify(raw)
        known = {item.lower() for item in slots[slot]}
        if shown and shown.lower() not in known:
            slots[slot].append(shown)
            added += 1
    if not added:
        return 0
    for key in SLOT_ORDER:
        if len(slots[key]) > FILE_CAP:
            slots[key] = slots[key][-FILE_CAP:]
    _write(dest, slots)
    return added


def injection(cid, ws=None, private_text=""):
    """Dynamic private-bundle block. Empty when this character has nothing to carry."""
    slots = load(cid, ws) if cid else _empty()
    seen = {_undated(item).lower() for key in SLOT_ORDER for item in slots[key]}
    notes = []
    for raw in (private_text or "").splitlines():
        if not raw.strip().startswith("-"):
            continue
        slot, shown = classify(raw)
        key = _undated(shown).lower()
        if not shown or key in seen:
            continue
        if slot:
            slots[slot].append(shown)
        else:
            notes.append(shown)
        seen.add(key)
    rows = []
    for key in SLOT_ORDER:
        items = slots[key][-SLOT_SHOWN:]
        if items:
            rows.append("%s: %s" % (LABELS[key], " · ".join(items)))
    if notes:
        rows.append("Continuity: %s" % " · ".join(notes[-NOTES_SHOWN:]))
    if not rows:
        return ""
    return "\n\n[Private memory]\n[Relationship]\n" + "\n".join(rows)
