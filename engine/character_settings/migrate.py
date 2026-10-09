"""Move PE's own data out of SillyTavern card fields (#896). A card used `system_prompt` for PE's private-mode rules;
SillyTavern means it as the system prompt of every chat. This moves the rules to `extensions.chatbot.private_rules`
(read first by characters.private_text, which still falls back to `system_prompt` for a card not moved) and empties
the ST field -- through the settings store, so the card's previous version is kept and can be restored.

  python3 engine/character_settings/migrate.py        move every character that still has its rules in system_prompt
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # engine/, when run as a script
import characters  # noqa: E402
from character_settings import store  # noqa: E402


def move_private_rules(cid: str, ws=None) -> List[str]:
    """The keys changed for one character ([] when there was nothing to move)."""
    card = characters.load(cid, ws)
    rules = str((card.get("data") or {}).get("system_prompt") or "").strip()
    if not rules or str(characters.ext(card).get("private_rules") or "").strip():
        return []
    out = store.patch(cid, {"pe.private_rules": rules, "card.system_prompt": ""}, ws)
    return out["changed"]


def move_all(ws=None) -> Dict[str, List[str]]:
    return {c["id"]: changed for c in characters.listing(ws) for changed in [move_private_rules(c["id"], ws)] if changed}


if __name__ == "__main__":
    for cid, keys in move_all().items():
        print(cid, ", ".join(keys))
