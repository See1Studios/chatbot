"""The settings a character has (character-settings §2.1), the one list the API and the drawer read. Each entry: the
dot-path key, the drawer's tab, the type, the source it lives in and where inside it, whether the drawer may edit it,
whether it is sensitive (folded until opened). Labels are catalog keys `charset.<key>`; the page says them in its
language. A new setting is one line here.

Sources: card (card.json `data`), display (card.json `data.extensions.chatbot.display`), brain (brain-override.json,
one entry per mode; null = the card's default), team (team.json roles), state (state.json), file (a text file next to
the card).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

TYPES = ("text", "longtext", "list", "bool", "select", "brain", "roles")
THRESHOLD = ("off", "mood", "gist")   # threshold.STRENGTHS

# (key, tab, type, source, where, editable, sensitive)
FIELDS: Tuple[Tuple[str, str, str, str, str, bool, bool], ...] = (
    ("card.name", "character", "text", "card", "name", True, False),
    ("display.title", "character", "text", "display", "title", True, False),
    ("display.user_title", "character", "text", "display", "user_title", True, False),
    ("display.voice", "character", "text", "display", "voice", True, False),
    ("card.description", "character", "longtext", "card", "description", True, False),
    ("card.personality", "character", "longtext", "card", "personality", True, False),
    ("card.scenario", "character", "longtext", "card", "scenario", True, False),
    ("card.first_mes", "character", "longtext", "card", "first_mes", True, False),
    ("card.alternate_greetings", "character", "list", "card", "alternate_greetings", True, False),
    ("card.mes_example", "character", "longtext", "card", "mes_example", True, False),
    ("card.tags", "character", "list", "card", "tags", True, False),
    ("file.visual", "character", "longtext", "file", "visual.md", True, False),
    ("file.memory", "relationship", "longtext", "file", "memory.md", True, False),
    ("file.relationship", "relationship", "longtext", "file", "relationship.md", True, True),
    ("file.private_memory", "relationship", "longtext", "file", "private-memory.md", True, True),
    ("state.threshold", "relationship", "select", "state", "threshold", True, False),
    ("state.auto_scene", "relationship", "bool", "state", "auto_scene", True, False),
    ("state.places", "relationship", "list", "state", "places", True, False),
    ("brain.work", "settings", "brain", "brain", "work", True, False),
    ("brain.private", "settings", "brain", "brain", "private", True, False),
    ("team.roles", "settings", "roles", "team", "roles", True, False),
    ("card.system_prompt", "settings", "longtext", "card", "system_prompt", True, False),
    ("card.post_history_instructions", "settings", "longtext", "card", "post_history_instructions", True, False),
    ("card.creator_notes", "settings", "longtext", "card", "creator_notes", True, False),
    ("card.creator", "settings", "text", "card", "creator", True, False),
    ("card.character_version", "settings", "text", "card", "character_version", True, False),
)

OPTIONS: Dict[str, List[str]] = {"state.threshold": list(THRESHOLD)}


def by_key() -> Dict[str, Dict]:
    return {k: {"key": k, "tab": tab, "type": typ, "source": src, "where": where, "editable": ed, "sensitive": sens}
            for k, tab, typ, src, where, ed, sens in FIELDS}
