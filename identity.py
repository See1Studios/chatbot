"""Chatbot identity, read from this instance's own instruction files
(docs/plans/chatbot-host-portability.md, Phase 3).

Every identity fact comes from the instructions the model itself is given, so
what the model reads and what the host shows/prompts can never disagree, and no
name is hardcoded here or in the UI:

  the default character's card (characters/<id>/card.json, CARD_ONLY_v1):
    data.name                           persona: the character's name (optional)
    extensions.chatbot.display          user_title (how the user is addressed), voice, title (the job title)
    description / personality           the personality and tone themselves
    data.system_prompt                  the private-mode rules

Other characters (docs/plans/multi-agent-worktree-delegation.md §12) live in
`characters/<id>/card.json` (Character Card V2, characters.py). Asked by role or
character id, never by name: the name (`data.name`) and the title/voice under
`extensions.chatbot.display` are display only. A job title is a name the user
gives (TITLE_DISPLAY_v1): the card's `display.title`, else the title of the first
role pack the character holds. What the character does is the role pack's text,
never its title.

Always read from `WORKSPACE` at call time (never a module constant), so a second
chatbot with its own workspace has its own identity. Anything missing or broken
falls back to neutral defaults. The files are editable user data, so every value
is length-capped and stripped of control characters before use.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Dict, Optional

from host_config import ROOT, WORKSPACE

DEFAULTS = {"title": "Assistant", "persona": "", "user_title": "사용자", "voice": ""}
_LIMITS = {"title": 60, "persona": 40, "user_title": 20, "voice": 120}

_ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_BODY_LIMIT = 4000

_FRONT = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")

_lock = threading.Lock()
_cache: Dict[str, tuple] = {}  # path -> ((mtime_ns, size), front matter dict)


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


def _clean(value: str, limit: int) -> str:
    return _CTRL.sub(" ", value or "").strip()[:limit].strip()


def _front(path: Path) -> Dict[str, str]:
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    with _lock:
        hit = _cache.get(str(path))
        if hit and hit[0] == key:
            return hit[1]
    try:
        fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        fm = {}
    with _lock:
        _cache[str(path)] = (key, fm)
    return fm


def _pd() -> Dict:
    try:
        import characters
        return characters.default_card(WORKSPACE)
    except (ImportError, OSError, ValueError):
        return {}


def persona_file(role: str = "") -> Path:
    """The card of the default character, or of another character by role or id; a path under `_missing` when
    there is none."""
    if not role:
        import characters
        cid = characters.default_character(WORKSPACE)
        return characters.card_path(cid, WORKSPACE) if cid else WORKSPACE / "characters" / "_missing" / "card.json"
    if not (_ROLE_RE.match(role) or role.startswith("char_")):
        raise ValueError("role must be a lowercase id, got %r" % role[:40])
    import characters
    cid = characters.resolve(role, WORKSPACE)
    return characters.card_path(cid, WORKSPACE) if cid else WORKSPACE / "characters" / "_missing" / "card.json"


def _character(role: str) -> Dict:
    try:
        import characters
        return characters.load(characters.resolve(role, WORKSPACE) or "", WORKSPACE)
    except (OSError, ValueError, ImportError):
        return {}


def _title(cid: str, card: Dict) -> str:
    """The job title shown for a character: its card's `display.title`, else its first role pack's title."""
    import characters
    title = (characters.ext(card).get("display") or {}).get("title", "")
    for role in ([] if title or not cid else characters.roles_of(cid, WORKSPACE)):
        pack = characters.role_pack(role, WORKSPACE)
        title = pack.get("title", "") if pack.get("text") else ""       # only a pack that exists names a title
        if title:
            break
    return title


def _own_values() -> Dict[str, str]:
    """The default character's persona, user_title, voice and title."""
    card = _pd()
    if not card:
        return {"persona": "", "user_title": "", "voice": "", "title": ""}
    import characters
    disp = characters.ext(card).get("display") or {}
    return {"persona": (card.get("data") or {}).get("name", ""), "user_title": disp.get("user_title", ""),
            "voice": disp.get("voice", ""), "title": _title(characters.default_character(WORKSPACE), card)}


def get_identity(role: str = "") -> Dict[str, str]:
    """{title, persona, user_title, voice, name}. `name` is what to call the
    chatbot in running text: the persona if there is one, else the title.
    With `role` (a role or a character id), that character: its own name and
    voice; title and the user's form of address fall back to the chatbot's."""
    base = _own_values()
    if role:
        persona_file(role)                       # validates the role / id
        card = _character(role)
        import characters
        disp = characters.ext(card).get("display") or {} if card else {}
        vals = {"persona": (card.get("data") or {}).get("name", "") if card else "", "voice": disp.get("voice", ""),
                "title": (_title(characters.resolve(role, WORKSPACE) or "", card) if card else "") or base["title"],
                "user_title": disp.get("user_title", "") or base["user_title"]}
    else:
        vals = base
    ident = {k: _clean(vals.get(k, ""), _LIMITS[k]) or default for k, default in DEFAULTS.items()}
    ident["name"] = ident["persona"] or ident["title"]
    return ident


def persona_body(role: str = "") -> str:
    """The personality text: the default character's card, or another character's work text (identity, voice,
    instructions)."""
    if role:
        persona_file(role)
        card = _character(role)
        if not card:
            return ""
        import characters
        return characters.work_text(card, characters.resolve(role, WORKSPACE) or "", WORKSPACE)[:_BODY_LIMIT]
    card = _pd()
    if not card:
        return ""
    import characters
    return _FRONT.sub("", characters.persona_text(card), count=1).strip()[:_BODY_LIMIT]


def private_rules() -> str:
    """The default character's private-mode rules (its card's system prompt)."""
    card = _pd()
    if not card:
        return ""
    import characters
    return characters.private_text(card)


def user_title() -> str:
    return get_identity()["user_title"]


def display_name() -> str:
    """The name to put on the chatbot's own lines: persona if any, else title."""
    return get_identity()["name"]


def self_label(role: str = "") -> str:
    """How a host-built prompt introduces the chatbot: '<title> <persona>' when
    both exist and differ (title, then name), else whichever there is."""
    i = get_identity(role)
    if i["persona"] and i["persona"] != i["title"]:
        return f"{i['title']} {i['persona']}"
    return i["name"]


def voice_phrase(suffix: str = "로") -> str:
    """The tone hint as a clause ('친근한 반말로'), or '' when none is set."""
    v = get_identity()["voice"]
    return f"{v}{suffix}" if v else ""


def script_json(ident: Optional[Dict[str, str]] = None) -> str:
    """Identity as JSON that is safe inside an inline <script> (the values come
    from editable files): `<`, `>`, `&` and the JS line separators are escaped."""
    raw = json.dumps(ident or get_identity(), ensure_ascii=False)
    return (raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def seed_workspace_files(templates_dir: Optional[Path] = None, workspace: Optional[Path] = None) -> list:
    """New install: the neutral card template becomes the first character, the team's default, holding no role --
    roles are the user's data, given when a premade pack is chosen (CARD_ONLY_v1, workspace manifest). A workspace
    that already has a character is never touched. Returns what was made."""
    import characters
    src = (templates_dir or (ROOT / "templates")) / "character.json"
    dst_dir = workspace or WORKSPACE
    if characters.default_character(dst_dir) or characters.listing(dst_dir) or not src.is_file():
        return []
    card = json.loads(src.read_text(encoding="utf-8"))
    cid = characters.new_id()
    characters.save(cid, card, dst_dir)
    characters.save_team({"default": cid, "members": {cid: []}}, dst_dir)
    return ["card"]