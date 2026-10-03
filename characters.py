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
import random
import re
import secrets
import shutil
import time
from pathlib import Path

import platform_compat
from typing import Dict, List, Optional

_FRONT = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def parse_frontmatter(text: str) -> Dict[str, str]:
    """`key: value` lines between two `---` fences at the very top of a file.
    Blank lines and `#` comment lines are skipped, a trailing ` # note` is cut,
    and one pair of matching quotes around a value is removed. No nesting."""
    m = _FRONT.match(text or "")
    if not m:
        return {}
    out: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = re.sub(r"\s+#.*$", "", val).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key.strip()] = val
    return out

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


def lorebook_path(cid: str, ws=None) -> Path:
    return card_path(cid, ws).parent / "lorebook.json"


def new_card(name: str, role: str = "", description: str = "", personality: str = "", **chatbot) -> Dict:
    """A new card. Cards carry no role: who does what is the team roster's (team.json). `role` is only for a
    workspace without a roster, which then derives one from the cards (TEAM_ROLES_v1)."""
    ext = {"role": role} if role else {}
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


def normalize_lorebook(data: Dict) -> Dict:
    """Normalize a SillyTavern or standard lorebook dict to canonical format."""
    if not isinstance(data, dict):
        return {"name": "", "entries": []}
    raw_entries = data.get("entries")
    if isinstance(raw_entries, dict):
        entries_list = list(raw_entries.values())
    elif isinstance(raw_entries, list):
        entries_list = raw_entries
    else:
        entries_list = []

    norm_entries = []
    for idx, raw in enumerate(entries_list):
        if not isinstance(raw, dict):
            continue
        entry = dict(raw)
        # keys
        keys = entry.get("keys")
        if keys is None:
            keys = entry.get("key")
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        elif isinstance(keys, list):
            keys = [str(k).strip() for k in keys if str(k).strip()]
        else:
            keys = []
        entry["keys"] = keys

        # content
        entry["content"] = str(entry.get("content") or "")

        # enabled
        if "enabled" in entry:
            entry["enabled"] = bool(entry["enabled"])
        else:
            entry["enabled"] = not bool(entry.get("disable") or entry.get("disabled"))

        # priority
        if "priority" in entry and entry["priority"] is not None:
            try:
                entry["priority"] = int(entry["priority"])
            except (ValueError, TypeError):
                entry["priority"] = 10
        elif "order" in entry and entry["order"] is not None:
            try:
                entry["priority"] = int(entry["order"])
            except (ValueError, TypeError):
                entry["priority"] = 10
        elif "insertion_order" in entry and entry["insertion_order"] is not None:
            try:
                entry["priority"] = int(entry["insertion_order"])
            except (ValueError, TypeError):
                entry["priority"] = 10
        else:
            entry["priority"] = 10

        # position
        pos = entry.get("position")
        if pos in (0, "0") or (isinstance(pos, str) and "before" in pos.lower()):
            entry["position"] = "before_char"
        elif pos in (1, "1") or (isinstance(pos, str) and "after" in pos.lower()):
            entry["position"] = "after_char"
        elif not pos:
            entry["position"] = "after_char"
        else:
            entry["position"] = str(pos)

        # id
        if "id" not in entry and "uid" in entry:
            entry["id"] = entry["uid"]
        elif "id" not in entry:
            entry["id"] = idx + 1

        norm_entries.append(entry)

    return {
        "name": str(data.get("name") or ""),
        "entries": norm_entries,
    }


def load_lorebook(cid: str, ws=None) -> Optional[Dict]:
    """Load lorebook.json for character cid if it exists, else None."""
    try:
        p = lorebook_path(cid, ws)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return normalize_lorebook(data)
    except (OSError, ValueError, TypeError):
        return None


def save_lorebook(cid: str, lorebook: Dict, ws=None) -> None:
    """Save lorebook.json for character cid atomically."""
    path = lorebook_path(cid, ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".lorebook.%d.tmp" % os.getpid())
    platform_compat.write_text(tmp, json.dumps(lorebook, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


_CARD_INFO_CACHE: Dict[Path, tuple] = {}


def _card_info(cid: str, ws=None) -> Optional[dict]:
    try:
        p = card_path(cid, ws)
        st = p.stat()
    except (OSError, ValueError):
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _CARD_INFO_CACHE.get(p)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        card = json.loads(p.read_text(encoding="utf-8"))
        if card.get("spec") != SPEC or not isinstance(card.get("data"), dict):
            return None
    except (OSError, ValueError):
        return None
    d = card.get("data") or {}
    disp = ext(card).get("display") or {}
    info = {
        "name": str(d.get("name") or "").strip(),
        "title": str(disp.get("title") or "").strip(),
        "user_title": str(disp.get("user_title") or "").strip(),
        "voice": str(disp.get("voice") or "").strip(),
    }
    _CARD_INFO_CACHE[p] = (key, info)
    return info


def name(card_or_id, ws=None) -> str:
    """The character's name (`data.name`), or ''."""
    if isinstance(card_or_id, dict):
        return str((card_or_id.get("data") or {}).get("name") or "").strip()
    cid = str(card_or_id or "").strip()
    if not cid:
        return ""
    info = _card_info(cid, ws)
    if info is not None:
        return info["name"]
    try:
        card = load(cid, ws)
        return str((card.get("data") or {}).get("name") or "").strip()
    except (OSError, ValueError):
        return ""


def title(card_or_id, cid: str = "", ws=None) -> str:
    """The job title shown for a character: its card's `display.title`, else its first role pack's title,
    else fallback to its name."""
    if isinstance(card_or_id, dict):
        card = card_or_id
        disp = ext(card).get("display") or {}
        t = str(disp.get("title") or "").strip()
        if t:
            return t
        cid = cid or ""
        if cid:
            for r in roles_of(cid, ws):
                pack = role_pack(r, ws)
                if pack.get("text") and pack.get("title"):
                    return pack["title"]
        return name(card)
    cid = cid or str(card_or_id or "").strip()
    if not cid:
        return ""
    info = _card_info(cid, ws)
    if info is not None and info["title"]:
        return info["title"]
    if cid:
        for r in roles_of(cid, ws):
            pack = role_pack(r, ws)
            if pack.get("text") and pack.get("title"):
                return pack["title"]
    return name(cid, ws)


def user_title(card_or_id, ws=None) -> str:
    """How the user is addressed by this character (`display.user_title`), or ''."""
    if isinstance(card_or_id, dict):
        card = card_or_id
        disp = ext(card).get("display") or {}
        return str(disp.get("user_title") or "").strip()
    cid = str(card_or_id or "").strip()
    if not cid:
        return ""
    info = _card_info(cid, ws)
    if info is not None:
        return info["user_title"]
    return ""


def save(cid: str, card: Dict, ws=None) -> None:
    path = card_path(cid, ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".card.%d.tmp" % os.getpid())
    platform_compat.write_text(tmp, json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    _CARD_INFO_CACHE.pop(path, None)


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
        out.append({"id": d.name, "name": name(card), "card": card})
    members = load_team(ws, out)["members"]
    for c in out:
        c["roles"] = list(members.get(c["id"]) or [])
        c["role"] = c["roles"][0] if c["roles"] else ""      # the first role, for callers that show one
        c["title"] = title(c["card"], c["id"], ws)
    return out


def by_role(role: str, ws=None) -> Optional[str]:
    """The character who plays this role: the oldest holder other than the default character (work of a role is
    delegated to it), else the default if only it holds the role, else None."""
    holders = [c["id"] for c in listing(ws) if role in c["roles"]]
    default = default_character(ws) if len(holders) > 1 else ""
    return next((h for h in holders if h != default), holders[0] if holders else None)


def resolve(ref: str, ws=None) -> Optional[str]:
    """A character id from an id or a role."""
    if ID_RE.match(ref or ""):
        return ref if card_path(ref, ws).is_file() else None
    return by_role(ref, ws) if _ROLE_RE.match(ref or "") else None


def roles(ws=None) -> List[str]:
    return sorted({r for c in listing(ws) for r in c["roles"]})


def expert_roles(ws=None) -> List[str]:
    """The roles work can be delegated to: those held by any character but the default one (the delegator)."""
    default = default_character(ws)
    return sorted({r for c in listing(ws) if c["id"] != default for r in c["roles"]})


# ------------------------------------------------------------------ team roster and role packs (TEAM_ROLES_v1)
# Every character is equal; a role is a pack of instructions, skills and tool grants (roles/<role>/ROLE.md), and
# the roster (team.json) says who holds which role and whom the app opens with. Cards stay role-free, so a card can
# be shared without our team's arrangement in it.
#   team.json: {"default": "<id>", "members": {"<id>": ["<role>", ...], ...}}
# Role ids are the user's data: the engine knows no role by name. What it needs is one position, the default
# character (the chatbot itself: it plans, confirms and is read every turn); experts are the roles the others hold.
#   roles/<role>/ROLE.md: front matter `title`, `tools` and `skills` (comma-separated), then the instructions.

def team_path(ws=None) -> Path:
    return Path(ws or _default_ws()) / "team.json"


def roles_dir(ws=None) -> Path:
    return Path(ws or _default_ws()) / "roles"


def load_team(ws=None, cards: Optional[List[Dict]] = None) -> Dict:
    """The roster; without team.json, one derived from the cards' old `role` field, the oldest card the default."""
    try:
        team = json.loads(team_path(ws).read_text(encoding="utf-8"))
        if isinstance(team, dict) and isinstance(team.get("members"), dict):
            members = {k: [r for r in v if isinstance(r, str) and _ROLE_RE.match(r)]
                       for k, v in team["members"].items() if ID_RE.match(k) and isinstance(v, list)}
            return {"default": str(team.get("default") or ""), "members": members}
    except (OSError, ValueError):
        pass
    if cards is None:
        cards = [{"id": c["id"], "card": c["card"]} for c in _raw_listing(ws)]
    members = {c["id"]: [ext(c["card"]).get("role")] for c in cards if _ROLE_RE.match(str(ext(c["card"]).get("role") or ""))}
    return {"default": cards[0]["id"] if cards else "", "members": members}


def _raw_listing(ws=None) -> List[Dict]:
    root = characters_dir(ws)
    out = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if ID_RE.match(d.name):
            try:
                out.append({"id": d.name, "card": load(d.name, ws)})
            except (OSError, ValueError):
                continue
    return out


def save_team(team: Dict, ws=None) -> None:
    path = team_path(ws)
    tmp = path.with_name(".team.%d.tmp" % os.getpid())
    platform_compat.write_text(tmp, json.dumps(team, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def default_character(ws=None) -> str:
    """Whom the app opens with: the roster's default if that card exists, else (with a roster) the oldest
    character, else ""."""
    team = load_team(ws)
    if team["default"] and card_path(team["default"], ws).is_file():
        return team["default"]
    first = _raw_listing(ws) if team_path(ws).is_file() else []
    return first[0]["id"] if first else ""


def roles_of(cid: str, ws=None) -> List[str]:
    return list(load_team(ws)["members"].get(cid) or [])


# pew/R: pack files are named like SKILL.md (ROLE.md, PROCEDURE.md); a pack written before keeps working.
PACK_FILES = {"role": ("ROLE.md", "role.md"), "procedure": ("PROCEDURE.md", "procedure.md")}


def pack_file(role: str, kind: str = "role", ws=None) -> Path:
    """The file of a role pack: the new name, or the old one when only that exists (the new name when neither)."""
    names = PACK_FILES[kind]
    d = roles_dir(ws) / role
    found = platform_compat.named_file(d, names)       # as spelled on disk, also where case is ignored (#405)
    return Path(found) if found else d / names[0]


def role_pack(role: str, ws=None) -> Dict:
    """{role, title, tools, skills, text} of roles/<role>/ROLE.md; empty lists and text when there is none."""
    try:
        raw = pack_file(role, "role", ws).read_text(encoding="utf-8") if _ROLE_RE.match(role or "") else ""
    except OSError:
        raw = ""
    fm = parse_frontmatter(raw)
    split = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]  # noqa: E731
    return {"role": role, "title": fm.get("title") or role, "tools": split(fm.get("tools")),
            "skills": split(fm.get("skills")), "text": _FRONT.sub("", raw, count=1).strip()}


def tools_of(cid: str, ws=None) -> List[str]:
    """Tool grants from every role the character holds."""
    return sorted({t for r in roles_of(cid, ws) for t in role_pack(r, ws)["tools"]})


def migrate_team(ws=None) -> bool:
    """Write team.json from the cards' old `role` field and take the field out of the cards. False when a roster
    already exists or there are no cards."""
    if team_path(ws).is_file():
        return False
    cards = _raw_listing(ws)
    if not cards:
        return False
    save_team(load_team(ws, cards), ws)
    for c in cards:
        e = ext(c["card"])
        if "role" in e:
            del e["role"]
            save(c["id"], c["card"], ws)
    return True


def brains(card: Dict, mode: str = "work") -> List[Dict]:
    chain = ((ext(card).get("brains") or {}).get(mode))
    return chain if isinstance(chain, list) else []


def brain_override_path(cid: str, ws=None) -> Path:
    """Per-character user choice of brain. User data, next to the card, never the card itself."""
    return card_path(cid, ws).parent / "brain-override.json"


def read_brain_overrides(cid: str, ws=None) -> Dict:
    """work/private -> a brain dict, or None when that mode was sent back to the card.

    A missing file means nothing was chosen. A null mode means the user pressed reset.
    """
    try:
        raw = json.loads(brain_override_path(cid, ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for mode in ("work", "private"):
        if mode not in raw:
            continue
        row = raw.get(mode)
        if row is None:
            out[mode] = None
        elif isinstance(row, dict) and str(row.get("provider") or "").strip():
            out[mode] = {"provider": str(row["provider"]).strip(),
                         "model": str(row.get("model") or "").strip(),
                         "effort": str(row.get("effort") or "").strip()}
    return out


def write_brain_override(cid: str, mode: str, brain: Optional[Dict], ws=None) -> None:
    """Remember one mode, or store null when brain is empty so the next visit stays on the card."""
    if mode not in ("work", "private"):
        raise ValueError(mode)
    path = brain_override_path(cid, ws)
    cur = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cur = raw
    except (OSError, ValueError):
        cur = {}
    if brain and str(brain.get("provider") or "").strip():
        cur[mode] = {"provider": str(brain["provider"]).strip(),
                     "model": str(brain.get("model") or "").strip(),
                     "effort": str(brain.get("effort") or "").strip()}
    else:
        cur[mode] = None
    kept = {k: cur[k] for k in ("work", "private") if k in cur}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".brain-override.%d.tmp" % os.getpid())
    platform_compat.write_text(tmp, json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def work_text(card: Dict, cid: str = "", ws=None) -> str:
    """What the character brings to a work brief: who it is, how it works, and the role packs it holds (English;
    examples may be Korean)."""
    d, e = card.get("data") or {}, ext(card)
    parts = [d.get("description") or "", ("Voice: " + d["personality"]) if d.get("personality") else "",
             ((e.get("work") or {}).get("instructions") or "")]
    parts += [role_pack(r, ws)["text"] for r in (roles_of(cid, ws) if cid else [])]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


# ------------------------------------------------------------------ rendering a card
# A card is the only source of a character (CARD_ONLY_v1): identity, voice, private rules (`data.system_prompt`) and
# brains (`brains.work`). The house memory is memory/MEMORY.md; each character keeps its own memory in its folder.
# Front matter is cut with _FRONT (top of this file), the same fence parse_frontmatter reads.


def default_card(ws=None) -> Dict:
    """The card of the character the app opens with (team.json `default`), or {}."""
    cid = default_character(ws)
    try:
        return load(cid, ws) if cid else {}
    except (OSError, ValueError):
        return {}


def persona_text(card: Dict) -> str:
    """The card as the instruction bundle shows it: front matter (name, how the user is addressed, voice) + body."""
    d, e = card.get("data") or {}, ext(card)
    disp = e.get("display") or {}
    head = ["---", "persona: %s" % (d.get("name") or "")]
    head += ["%s: %s" % (k, disp[k]) for k in ("title", "user_title", "voice") if disp.get(k)]
    head.append("---")
    body = ["# Persona", "", (d.get("description") or "").strip()]
    if (d.get("personality") or "").strip():
        body += ["", "## Voice", d["personality"].strip()]
    return "\n".join(head) + "\n\n" + "\n".join(body).strip() + "\n"


def private_text(card: Dict) -> str:
    return ((card.get("data") or {}).get("system_prompt") or "").strip()


# ------------------------------------------------------------------ macros (CARD_MACROS_v1)
# Text in cards, lorebooks and role packs names people by macro, resolved from the data when a prompt is rendered
# (the files keep the macro): {{user}} how this character addresses the user and {{char}} its name (SillyTavern and
# the card spec, so imported cards work), {{title}} its job title, {{default}} the default character's name (the one
# who delegates and confirms) and {{role:<id>}} that role pack's title. The engine resolves references in the data;
# it names no role itself. A macro it cannot resolve is left as written.

_MACRO_RE = re.compile(r"\{\{\s*(user|char|title|default|role:[a-z][a-z0-9-]{0,31})\s*\}\}", re.I)


def render_macros(text: str, cid: str = "", ws=None) -> str:
    """`text` with its macros resolved for character `cid` (see above)."""
    if not text or "{{" not in text:
        return text
    cache: Dict[str, str] = {}

    def value(m) -> str:
        key = m.group(1).lower()
        if key not in cache:
            cache[key] = _macro_value(key, cid, ws)
        return cache[key] or m.group(0)
    return _MACRO_RE.sub(value, text)


def _macro_value(key: str, cid: str, ws=None) -> str:
    try:
        card = load(cid, ws) if cid and ID_RE.match(cid) else {}
    except (OSError, ValueError):
        card = {}
    if key == "char":
        return name(card) if card else ""
    if key == "user":
        return (user_title(card) if card else "") or user_title(default_card(ws))
    if key == "title":
        return title(card, cid, ws) if card else ""
    if key == "default":
        return name(default_character(ws), ws)
    pack = role_pack(key[len("role:"):], ws)
    return pack["title"] if pack["text"] else ""


# ------------------------------------------------------------------ private memory (§12, PRIVATE_MEMORY_v1)
# Private talk is remembered, but completely apart from work: `private-memory.md` in the character's folder is read
# only by the character's private session and written when the user leaves it (SESSION_SPLIT_v1); work memory never
# sees it, and it never sees work.

PRIVATE_MEMORY_CAP = 2048
_SECRETISH = re.compile(r"(api[_-]?key|secret|password|passwd|token|bearer|sk-[A-Za-z0-9]{8,}|-----BEGIN)", re.I)


def private_memory_path(cid: str, ws=None) -> Path:
    return card_path(cid, ws).parent / "private-memory.md"


def read_private_memory(cid: str, ws=None) -> str:
    try:
        return private_memory_path(cid, ws).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def remember_private(cid: str, lines: List[str], today: Optional[str] = None, ws=None) -> int:
    """Add lines to the character's private memory: no duplicates, no secret-looking lines, 200 chars each,
    oldest lines dropped past PRIVATE_MEMORY_CAP. Returns the number added."""
    path = private_memory_path(cid, ws)
    if not path.parent.is_dir():
        return 0
    kept = [ln for ln in read_private_memory(cid, ws).splitlines() if ln.startswith("- ")]
    known = {re.sub(r"^- \[[0-9-]+\] ", "", ln).lower() for ln in kept}
    stamp = today or time.strftime("%Y-%m-%d")
    added = 0
    for raw in lines:
        line = re.sub(r"\s+", " ", str(raw)).strip()[:200]
        if line and not _SECRETISH.search(line) and line.lower() not in known:
            kept.append("- [%s] %s" % (stamp, line))
            known.add(line.lower())
            added += 1
    head = "# Private memory\n"
    while kept and len((head + "\n".join(kept) + "\n").encode("utf-8")) > PRIVATE_MEMORY_CAP:
        kept.pop(0)
    tmp = path.with_name(".private-memory.%d.tmp" % os.getpid())
    platform_compat.write_text(tmp, head + "\n".join(kept) + "\n", encoding="utf-8")
    tmp.replace(path)
    return added


def private_segment(history: List[Dict], since: float = 0.0) -> List[Dict]:
    """A private session's user/assistant turns after `since` (the time its talk was last put in memory)."""
    return [h for h in history if h.get("role") in ("user", "assistant") and (h.get("text") or "").strip()
            and not h.get("notice") and float(h.get("ts") or 0) > since]


def private_digest_prompt(segment: List[Dict], user_word: str, name: str) -> str:
    """The one-shot prompt that turns a private conversation into at most three memory lines."""
    talk = "\n".join("%s: %s" % (user_word if h["role"] == "user" else name,
                                 re.sub(r"^\[사적 모드:[^\]]*\]\s*", "", str(h["text"])).strip()[:400])
                     for h in segment[-40:])
    return ("Below is a private (non-work) conversation between %s and %s. List at most three short lines worth "
            "remembering for future private conversations with them: preferences, feelings, promises, shared moments. "
            "Facts only, one per line starting with \"- \" and a slot tag (progress:, promise:, pref:, or taboo:), in Korean. No work topics, no secrets. If nothing is worth "
            "keeping, answer NONE.\n\n%s" % (user_word, name, talk))


def parse_memory_lines(text: str) -> List[str]:
    return [m.group(1).strip() for m in re.finditer(r"^\s*-\s+(.+)$", text or "", re.M)][:3]


# ------------------------------------------------------------------ art (CHARACTER_ART_v1)
# One image format for every character, so image agents can follow it (skill `character-art`). Files live next to
# the card so they travel with it:
#   avatar.webp                  512x512 badge, the base look, face centred, readable as a 56px circle
#   avatar/<provider>.webp       512x512, optional "wig" per brain: same face, only hair colour/cut and outfit change
#   stage.webp, stage/<provider>.webp  1024x1024, optional chat background (per brain, like the wigs)
#   sprites/<framing>/<label>.webp  optional standing sprites for a character-only (desktop) view with speech
#                                bubbles: transparent, one canvas and one anchor per framing, the same scale for every
#                                label so swapping an expression never moves the body. Labels are SillyTavern's
#                                expression-sprite labels; `neutral` is required once a framing exists.
#   visual.md                    the character's visual lock sheet (locks, base look, wig table, rejected)
# A .png of the same name may sit beside any .webp as the master; the page serves the .webp.

ART_SIZE = (512, 512)
ART_MAX_BYTES = 200 * 1024
STAGE_SIZE = (1024, 1024)
STAGE_MAX_BYTES = 300 * 1024
# framing -> (canvas, max bytes, anchor rule for the skill)
FRAMINGS = {
    "bust": ((1024, 1024), 400 * 1024, "shoulder shot: shoulders cut by the bottom edge, top of the head ~8% from the top"),
    "full": ((1024, 2048), 800 * 1024, "full body: feet on a line 2% above the bottom edge, centred"),
}
EXPRESSIONS = ("admiration", "amusement", "anger", "annoyance", "approval", "caring", "confusion", "curiosity",
               "desire", "disappointment", "disapproval", "disgust", "embarrassment", "excitement", "fear",
               "gratitude", "grief", "joy", "love", "nervousness", "neutral", "optimism", "pride", "realization",
               "relief", "remorse", "sadness", "surprise")
_ART_NAME = re.compile(r"^[a-z0-9_-]{1,32}\.(webp|png)$")

# ART_PLACEHOLDER_v1: every art kind resolves to a file -- the character's own (a per-brain variant first), else
# the engine's neutral placeholder -- so the page never guesses what exists and never shows a broken image.
PLACEHOLDER_DIR = Path(__file__).resolve().parent / "static" / "placeholders"
PLACEHOLDERS = {"avatar": "avatar.webp", "stage": "stage.webp", "sprite:bust": "sprite-bust.webp",
                "sprite:full": "sprite-full.webp"}
ART_KINDS = ("avatar", "stage", "sprite")
_SLUG = re.compile(r"^[a-z0-9_-]{1,32}$")


# ART_NAMES_v1 (character-resource-pipeline.md section 10): names are the fallback chain -- no table. SillyTavern's
# rule for several pictures of one expression is a name plus a "." or "-" suffix (joy-1, joy.giggle); read the other
# way, dropping suffixes from the right walks from the most particular picture to the plain one, then to the kind's
# base name (neutral / avatar / stage), then to the engine placeholder. A brain's folder (SillyTavern's folder
# override: an outfit, our wig) is tried before the shared one.
_ART_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9_-]+)*$")
_art_rng = random.Random()


def name_chain(name: str, base: str) -> List[str]:
    """'joy.giggle-2' -> ['joy.giggle-2', 'joy.giggle', 'joy', base]; unusable names are dropped."""
    out, n = [], (name or "").strip().lower()
    while n:
        if len(n) <= 64 and _ART_NAME.match(n):
            out.append(n)
        cut = max(n.rfind("."), n.rfind("-"))
        n = n[:cut] if cut > 0 else ""
    return list(dict.fromkeys(out + [base]))


def _pick(folder: Path, name: str, variants: bool, rng=None) -> Optional[Path]:
    """The picture called `name` in `folder`; with variants, one of name / name-* / name.* at random, the way
    SillyTavern shows one of several pictures of an expression."""
    if not folder.is_dir():
        return None
    own = [folder / ("%s.%s" % (name, e)) for e in ("webp", "png")]
    found = [p for p in own if p.is_file()][:1]
    if variants:
        seen = {p.stem for p in found}
        for p in sorted(folder.glob(name + "[.-]*.webp")) + sorted(folder.glob(name + "[.-]*.png")):
            if p.stem not in seen and _ART_NAME.match(p.stem):
                seen.add(p.stem)
                found.append(p)
    return (rng or _art_rng).choice(found) if found else None


def art_file(cid: str, kind: str, provider: str = "", framing: str = "full", label: str = "neutral",
             ws=None, rng=None) -> "tuple":
    """(path, is_placeholder), by the ART_NAMES_v1 rule.
    sprite: for the asked framing, then the other -- the brain's folder, then the shared one -- the label's
            suffix chain down to neutral ("default" means neutral).
    avatar: avatar/<brain>, then avatar.  stage: stage.<label> chain, then stage, then the old stage/<brain>.
    Anything missing ends at the engine placeholder. Unknown kind: ValueError."""
    if kind not in ART_KINDS:
        raise ValueError("unknown art kind: %s" % kind)
    framing = framing if framing in FRAMINGS else "full"
    brain = provider if _SLUG.match(provider or "") else ""
    if ID_RE.match(cid or ""):
        base = card_path(cid, ws).parent
        if kind == "sprite":
            label = "neutral" if (label or "") in ("", "default") else label
            for f in [framing] + [x for x in FRAMINGS if x != framing]:
                folders = ([base / "sprites" / f / brain] if brain else []) + [base / "sprites" / f]
                for folder in folders:
                    for n in name_chain(label, "neutral"):
                        hit = _pick(folder, n, variants=True, rng=rng)
                        if hit:
                            return hit, False
        elif kind == "avatar":
            for folder, n in ([(base / "avatar", brain)] if brain else []) + [(base, "avatar")]:
                hit = _pick(folder, n, variants=False)
                if hit:
                    return hit, False
        else:
            names = name_chain("stage." + label if label and label not in ("neutral", "default", "main") else "", "stage")
            tries = [(base, n) for n in names] + ([(base / "stage", brain)] if brain else [])
            for folder, n in tries:
                hit = _pick(folder, n, variants=False)
                if hit:
                    return hit, False
    return PLACEHOLDER_DIR / PLACEHOLDERS["sprite:" + framing if kind == "sprite" else kind], True


def sprite_map(cid: str, framing: str = "full", ws=None) -> Dict:
    """{"framing", "sprites": {label: "<framing>/<label>.webp"}} for the first framing the character has
    (the asked one first); empty sprites when it has none (every label then resolves to the placeholder)."""
    framing = framing if framing in FRAMINGS else "full"
    if ID_RE.match(cid or ""):
        root = card_path(cid, ws).parent / "sprites"
        for f in [framing] + [x for x in FRAMINGS if x != framing]:
            files = sorted((root / f).glob("*.webp")) if (root / f).is_dir() else []
            if files:
                return {"framing": f, "sprites": {x.stem: "%s/%s" % (f, x.name) for x in files}}
    return {"framing": framing, "sprites": {}}


def _image_info(path: Path) -> Optional[tuple]:
    """(width, height, has_alpha), or None without Pillow."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size[0], im.size[1], im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    except ImportError:
        return None
    except Exception:  # noqa: BLE001
        return 0, 0, False


_CORNER = 48
_CENTER = 256
_WHITE = 240


def _white_frac(im, box) -> float:
    crop = im.crop(box)
    n = crop.size[0] * crop.size[1]
    if not n:
        return 0.0
    return sum(1 for r, g, b in crop.getdata() if (r + g + b) / 3 > _WHITE) / n


def _empty_corner_padding(path: Path) -> bool:
    """True when the square is an inner badge on empty canvas (a 56px picker crop would hide the face)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            if (w, h) != ART_SIZE:
                return False
            s = _CORNER
            corners = (
                _white_frac(im, (0, 0, s, s)),
                _white_frac(im, (w - s, 0, w, s)),
                _white_frac(im, (0, h - s, s, h)),
                _white_frac(im, (w - s, h - s, w, h)),
            )
            c0, r0 = (w - _CENTER) // 2, (h - _CENTER) // 2
            center = _white_frac(im, (c0, r0, c0 + _CENTER, r0 + _CENTER))
            return all(c >= 0.8 for c in corners) and center < 0.2
    except ImportError:
        return False
    except Exception:  # noqa: BLE001
        return False


def check_art(cid: str, providers=(), ws=None) -> List[str]:
    """Problems with a character's images against the format above ([] = fine). `providers` are the known provider
    ids; a wig for any other name is reported. Sizes and transparency are checked when Pillow is installed."""
    base = card_path(cid, ws).parent
    problems = []
    if not (base / "avatar.webp").is_file():
        problems.append("avatar.webp is missing (the base look)")
    if not (base / "visual.md").is_file():
        problems.append("visual.md is missing (the visual lock sheet)")
    # (file, canvas, max bytes, needs transparency)
    files = [(base / n, ART_SIZE, ART_MAX_BYTES, False) for n in ("avatar.webp", "avatar.png")]
    files += [(base / n, STAGE_SIZE, STAGE_MAX_BYTES, False) for n in ("stage.webp", "stage.png")]
    dirs = [("avatar", set(providers), "provider", ART_SIZE, ART_MAX_BYTES, False),
            ("stage", set(providers), "provider", STAGE_SIZE, STAGE_MAX_BYTES, False)]
    sprites = base / "sprites"
    for d in sorted(sprites.iterdir()) if sprites.is_dir() else []:
        if d.name not in FRAMINGS:
            problems.append("sprites/%s: unknown framing (%s)" % (d.name, ", ".join(FRAMINGS)))
            continue
        canvas, cap, _ = FRAMINGS[d.name]
        dirs.append(("sprites/" + d.name, set(EXPRESSIONS), "expression", canvas, cap, True))
        if not (d / "neutral.webp").is_file():
            problems.append("sprites/%s/neutral.webp is missing (required once a framing exists)" % d.name)
    for sub, allowed, what, canvas, cap, alpha in dirs:
        d = base / sub
        for f in sorted(d.iterdir()) if d.is_dir() else []:
            if f.is_dir() or not _ART_NAME.match(f.name):
                problems.append("%s/%s: name must be <%s>.webp or .png" % (sub, f.name, what))
                continue
            if f.stem not in allowed:
                problems.append("%s/%s: unknown %s %r" % (sub, f.name, what, f.stem))
            files.append((f, canvas, cap, alpha))
    for f, canvas, cap, alpha in files:
        if not f.is_file():
            continue
        rel = f.relative_to(base).as_posix()
        if f.suffix == ".webp" and f.stat().st_size > cap:
            problems.append("%s: %d KB, keep it under %d KB" % (rel, f.stat().st_size // 1024, cap // 1024))
        info = _image_info(f)
        if info is not None:
            if tuple(info[:2]) != canvas:
                problems.append("%s: %sx%s, must be %dx%d" % ((rel,) + tuple(info[:2]) + canvas))
            if alpha and not info[2]:
                problems.append("%s: needs a transparent background" % rel)
        if canvas == ART_SIZE and (rel == "avatar.webp" or rel.startswith("avatar/")) and _empty_corner_padding(f):
            problems.append("%s: empty corner padding; fill the square so the face reads in a 56px circle" % rel)
        if f.suffix == ".png" and not f.with_suffix(".webp").is_file():
            problems.append("%s: a .png master needs its .webp beside it (the page serves .webp)" % rel)
    return problems


import shutil


def dev_delete(cid, body, ws=None, edition=""):
    """Delete one character folder on a developer install. Dialogs, rooms and sessions stay.

    The roster home character (whom the app opens with) is refused. confirm must be JSON true.
    """
    if edition != "dev":
        return 403, {"ok": False, "error": "developer-edition-only"}
    if not isinstance(body, dict) or body.get("confirm") is not True:
        return 400, {"ok": False, "error": "confirm-required"}
    cid = str(cid or "").strip().strip("/")
    if not ID_RE.match(cid):
        return 400, {"ok": False, "error": "not-a-character-id"}
    root = characters_dir(ws)
    folder = root / cid
    if folder.is_symlink() or not folder.is_dir():
        return 404, {"ok": False, "error": "no-such-character"}
    try:
        folder.resolve().relative_to(root.resolve())
    except ValueError:
        return 400, {"ok": False, "error": "not-a-character-folder"}
    if cid == default_character(ws):
        return 409, {"ok": False, "error": "home-character"}
    shutil.rmtree(str(folder))
    _CARD_INFO_CACHE.pop(card_path(cid, ws), None)
    _forget_member(cid, ws)
    return 200, {"ok": True, "id": cid}


def _forget_member(cid, ws):
    """Drop cid from team.json. Never changes who the home character is."""
    if not team_path(ws).is_file():
        return
    team = load_team(ws)
    if team.get("default") == cid or cid not in team["members"]:
        return
    team["members"].pop(cid, None)
    save_team(team, ws)
