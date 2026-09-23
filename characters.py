"""Characters: the unit of this app (docs/plans/multi-agent-worktree-delegation.md §12, CHARACTERS_v1).

A character is someone the user works with and relates to. Each lives in its own folder,
`<workspace>/characters/<id>/`, holding a Character Card V2 (`card.json`, the community standard used by
SillyTavern-style tools) and its memory (`memory.md`, kept outside the card: a card is shareable, a memory is not).

- The id is an identity, not a role and not a name: a TypeID (`char_` + UUIDv7 in Crockford base32, see
  https://github.com/jetify-com/typeid/tree/main/spec). It never changes; the name (`data.name`) and the role may.
- The card's own fields are the character's identity and relationship side; the work side lives under
  `data.extensions.chatbot`: `role` (e.g. pd, staff), `display` (title, voice, user_title), `work.instructions`,
  `brains.work` / `brains.private` (ordered provider/model lists, plan doc §11).
- Code finds characters by role or id, never by name (NAME_NEUTRAL_v1: names are display values).

Standard library only; the workspace is an argument (defaults to this instance's).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Dict, List, Optional

SPEC = "chara_card_v2"
SPEC_VERSION = "2.0"
EXT = "chatbot"
PREFIX = "char"
_B32 = "0123456789abcdefghjkmnpqrstvwxyz"   # TypeID / Crockford base32, lowercase
ID_RE = re.compile(r"^%s_[0-7][%s]{25}$" % (PREFIX, _B32))
_ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def _default_ws() -> Path:
    from host_config import WORKSPACE
    return WORKSPACE


# ------------------------------------------------------------------------ ids

def uuid7(now_ms: Optional[int] = None, rand: Optional[int] = None) -> int:
    """A UUIDv7 as a 128-bit int (RFC 9562): 48-bit Unix ms, version 7, variant 10, 74 random bits."""
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    r = secrets.randbits(74) if rand is None else rand
    rand_a, rand_b = (r >> 62) & 0xFFF, r & ((1 << 62) - 1)
    return (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b


def encode(n: int) -> str:
    """A 128-bit UUID as the 26-character TypeID suffix (the first character is 0-7)."""
    return "".join(_B32[(n >> (5 * (25 - i))) & 31] for i in range(26))


def new_id(prefix: str = PREFIX, now_ms: Optional[int] = None, rand: Optional[int] = None) -> str:
    """A TypeID: `<prefix>_` + a UUIDv7 in base32."""
    return "%s_%s" % (prefix, encode(uuid7(now_ms, rand)))


# ---------------------------------------------------------------------- cards

def characters_dir(ws=None) -> Path:
    return Path(ws or _default_ws()) / "characters"


def card_path(cid: str, ws=None) -> Path:
    if not ID_RE.match(cid or ""):
        raise ValueError("not a character id: %r" % (cid or "")[:60])
    return characters_dir(ws) / cid / "card.json"


def memory_path(cid: str, ws=None) -> Path:
    return card_path(cid, ws).parent / "memory.md"


def new_card(name: str, role: str, description: str = "", personality: str = "", **chatbot) -> Dict:
    ext = {"role": role}
    ext.update({k: v for k, v in chatbot.items() if v not in (None, "", {}, [])})
    return {"spec": SPEC, "spec_version": SPEC_VERSION,
            "data": {"name": name, "description": description, "personality": personality, "scenario": "",
                     "first_mes": "", "mes_example": "", "creator_notes": "", "system_prompt": "",
                     "post_history_instructions": "", "alternate_greetings": [], "tags": [], "creator": "",
                     "character_version": "", "extensions": {EXT: ext}}}


def ext(card: Dict) -> Dict:
    """The work side of a card (`data.extensions.chatbot`); an empty dict when a foreign card has none."""
    e = ((card.get("data") or {}).get("extensions") or {}).get(EXT)
    return e if isinstance(e, dict) else {}


def load(cid: str, ws=None) -> Dict:
    card = json.loads(card_path(cid, ws).read_text(encoding="utf-8"))
    if card.get("spec") != SPEC or not isinstance(card.get("data"), dict):
        raise ValueError("%s is not a Character Card V2" % cid)
    return card


def save(cid: str, card: Dict, ws=None) -> None:
    path = card_path(cid, ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".card.%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def listing(ws=None) -> List[Dict]:
    """Every readable character, oldest first (TypeIDs sort by creation time)."""
    out = []
    root = characters_dir(ws)
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if not ID_RE.match(d.name):
            continue
        try:
            card = load(d.name, ws)
        except (OSError, ValueError):
            continue
        e = ext(card)
        out.append({"id": d.name, "name": str(card["data"].get("name") or ""), "role": str(e.get("role") or ""),
                    "card": card})
    return out


def by_role(role: str, ws=None) -> Optional[str]:
    """The first (oldest) character with this role, or None."""
    return next((c["id"] for c in listing(ws) if c["role"] == role), None)


def resolve(ref: str, ws=None) -> Optional[str]:
    """A character id from an id or a role."""
    if ID_RE.match(ref or ""):
        return ref if card_path(ref, ws).is_file() else None
    return by_role(ref, ws) if _ROLE_RE.match(ref or "") else None


def roles(ws=None) -> List[str]:
    return sorted({c["role"] for c in listing(ws) if c["role"]})


def brains(card: Dict, mode: str = "work") -> List[Dict]:
    chain = ((ext(card).get("brains") or {}).get(mode))
    return chain if isinstance(chain, list) else []


def work_text(card: Dict) -> str:
    """What the character brings to a work brief: who it is and how it works (English; examples may be Korean)."""
    d, e = card.get("data") or {}, ext(card)
    parts = [d.get("description") or "", ("Voice: " + d["personality"]) if d.get("personality") else "",
             ((e.get("work") or {}).get("instructions") or "")]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


# ------------------------------------------------------------------ migration

def migrate_experts(ws=None) -> List[str]:
    """experts/<role>/{expert.md, brain.json, memory.md} (plan doc §11) -> characters/<id>/. Returns new ids.
    The expert.md body becomes the description (a person can split it into description / personality / work
    instructions afterwards); the old folder is removed once the character is saved."""
    import shutil
    from identity import parse_frontmatter
    ws = Path(ws or _default_ws())
    made = []
    for f in sorted((ws / "experts").glob("*/expert.md")):
        role = f.parent.name
        if not _ROLE_RE.match(role) or by_role(role, ws):
            continue
        text = f.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        body = re.sub(r"\A﻿?---.*?\n---[ \t]*\n?", "", text, count=1, flags=re.S).strip()
        try:
            chain = json.loads((f.parent / "brain.json").read_text(encoding="utf-8")).get("chain") or []
        except (OSError, ValueError, AttributeError):
            chain = []
        cid = new_id()
        card = new_card(fm.get("persona") or role, role, description=body,
                        display={k: fm[k] for k in ("title", "voice") if fm.get(k)},
                        brains={"work": chain} if chain else {})
        save(cid, card, ws)
        if (f.parent / "memory.md").is_file():
            (f.parent / "memory.md").replace(memory_path(cid, ws))
        shutil.rmtree(f.parent)
        made.append(cid)
    return made
