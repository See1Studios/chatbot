"""The settings a character has (character-settings §2.1), the one list the API and the drawer read. Each entry: the
dot-path key, the drawer's tab, the type, the source it lives in and where inside it, whether the drawer may edit it,
whether it is sensitive (folded until opened). Labels are catalog keys `charset.<key>`; the page says them in its
language. A new setting is one line here.

Sources: card (card.json `data`), display (card.json `data.extensions.chatbot.display`), ext (a PE field under
`data.extensions.chatbot`, a dotted path), brain (brain-override.json,
one entry per mode; null = the card's default), team (team.json roles), state (state.json), file (a text file next to
the card).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

TYPES = ("text", "longtext", "list", "bool", "select", "brain", "roles", "focal")
THRESHOLD = ("off", "mood", "gist")   # threshold.STRENGTHS

# (key, tab, type, source, where, editable, sensitive)
FIELDS: Tuple[Tuple[str, str, str, str, str, bool, bool], ...] = (
    # Character: everything of the SillyTavern card (V2/V3 `data`) -- the operator, 2026-10-09
    ("card.name", "character", "text", "card", "name", True, False),
    ("card.description", "character", "longtext", "card", "description", True, False),
    ("card.personality", "character", "longtext", "card", "personality", True, False),
    ("card.scenario", "character", "longtext", "card", "scenario", True, False),
    ("card.first_mes", "character", "longtext", "card", "first_mes", True, False),
    ("card.alternate_greetings", "character", "list", "card", "alternate_greetings", True, False),
    ("card.mes_example", "character", "longtext", "card", "mes_example", True, False),
    ("card.tags", "character", "list", "card", "tags", True, False),
    ("card.system_prompt", "character", "longtext", "card", "system_prompt", True, False),
    ("card.post_history_instructions", "character", "longtext", "card", "post_history_instructions", True, False),
    ("card.creator_notes", "character", "longtext", "card", "creator_notes", True, False),
    ("card.creator", "character", "text", "card", "creator", True, False),
    ("card.character_version", "character", "text", "card", "character_version", True, False),
    # Relationship: what PE adds to a character and keeps up -- display, look sheet, memory, the private room
    ("display.title", "relationship", "text", "display", "title", True, False),
    ("display.user_title", "relationship", "text", "display", "user_title", True, False),
    ("display.voice", "relationship", "text", "display", "voice", True, False),
    ("display.focal", "relationship", "focal", "display", "focal", True, False),   # the face crop; its own editor
    ("pe.private_rules", "relationship", "longtext", "ext", "private_rules", True, True),   # #896: was system_prompt
    ("file.visual", "relationship", "longtext", "file", "visual.md", True, False),
    ("file.memory", "relationship", "longtext", "file", "memory.md", True, False),
    ("file.relationship", "relationship", "longtext", "file", "relationship.md", True, True),
    ("file.private_memory", "relationship", "longtext", "file", "private-memory.md", True, True),
    ("state.threshold", "relationship", "select", "state", "threshold", True, False),
    ("state.auto_scene", "relationship", "bool", "state", "auto_scene", True, False),
    ("state.places", "relationship", "list", "state", "places", True, False),
    # Settings: the mechanics -- brains, roles
    ("pe.work_instructions", "settings", "longtext", "ext", "work.instructions", True, False),   # #896
    ("brain.work", "settings", "brain", "brain", "work", True, False),
    ("brain.private", "settings", "brain", "brain", "private", True, False),
    ("team.roles", "settings", "roles", "team", "roles", True, False),
)

# Shown under "more" until opened: the card's less-used fields (the operator: fold what matters less)
FOLDED = frozenset(("card.system_prompt", "card.post_history_instructions", "card.creator_notes", "card.creator",
                    "card.character_version"))

OPTIONS: Dict[str, List[str]] = {"state.threshold": list(THRESHOLD)}


def by_key() -> Dict[str, Dict]:
    return {k: {"key": k, "tab": tab, "type": typ, "source": src, "where": where, "editable": ed, "sensitive": sens}
            for k, tab, typ, src, where, ed, sens in FIELDS}
