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
        out.append({"id": d.name, "name": str(card["data"].get("name") or ""), "card": card})
    members = load_team(ws, out)["members"]
    for c in out:
        c["roles"] = list(members.get(c["id"]) or [])
        c["role"] = c["roles"][0] if c["roles"] else ""      # the first role, for callers that show one
    return out


def by_role(role: str, ws=None) -> Optional[str]:
    """The first (oldest) character holding this role in the team roster, or None."""
    return next((c["id"] for c in listing(ws) if role in c["roles"]), None)


def resolve(ref: str, ws=None) -> Optional[str]:
    """A character id from an id or a role."""
    if ID_RE.match(ref or ""):
        return ref if card_path(ref, ws).is_file() else None
    return by_role(ref, ws) if _ROLE_RE.match(ref or "") else None


def roles(ws=None) -> List[str]:
    return sorted({r for c in listing(ws) for r in c["roles"]})


# ------------------------------------------------------------------ team roster and role packs (TEAM_ROLES_v1)
# Every character is equal; a role is a pack of instructions, skills and tool grants (roles/<role>/role.md), and
# the roster (team.json) says who holds which role and whom the app opens with. Cards stay role-free, so a card can
# be shared without our team's arrangement in it.
#   team.json: {"default": "<id>", "members": {"<id>": ["pd"], "<id>": ["staff"]}}
#   roles/<role>/role.md: front matter `title`, `tools` and `skills` (comma-separated), then the instructions.

def team_path(ws=None) -> Path:
    return Path(ws or _default_ws()) / "team.json"


def roles_dir(ws=None) -> Path:
    return Path(ws or _default_ws()) / "roles"


def load_team(ws=None, cards: Optional[List[Dict]] = None) -> Dict:
    """The roster; without team.json, one derived from the cards' old `role` field (the first pd is the default)."""
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
    default = next((cid for cid, rs in members.items() if "pd" in rs), "")   # no roster: only a pd card was "the chatbot"
    return {"default": default, "members": members}


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
    tmp.write_text(json.dumps(team, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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


def role_pack(role: str, ws=None) -> Dict:
    """{role, title, tools, skills, text} of roles/<role>/role.md; empty lists and text when there is none."""
    from identity import parse_frontmatter
    try:
        raw = (roles_dir(ws) / role / "role.md").read_text(encoding="utf-8") if _ROLE_RE.match(role or "") else ""
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


def work_text(card: Dict, cid: str = "", ws=None) -> str:
    """What the character brings to a work brief: who it is, how it works, and the role packs it holds (English;
    examples may be Korean)."""
    d, e = card.get("data") or {}, ext(card)
    parts = [d.get("description") or "", ("Voice: " + d["personality"]) if d.get("personality") else "",
             ((e.get("work") or {}).get("instructions") or "")]
    parts += [role_pack(r, ws)["text"] for r in (roles_of(cid, ws) if cid else [])]
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


# ------------------------------------------------------------------ the PD's card (§12 step 2)
# The chatbot's own persona is the character with role `pd`. Its card replaces PERSONA.md (identity, voice),
# PRIVATE.md (the private-mode rules, in `data.system_prompt`) and pd-brain.json (`brains.work`). Its memory stays
# in memory/MEMORY.md for now (the memory tool's lock and file); other characters keep theirs in their folder.

_FRONT = re.compile(r"\A﻿?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_VOICE = re.compile(r"^##\s+Voice\s*$", re.M | re.I)


def default_card(ws=None) -> Dict:
    """The card of the character the app opens with (team.json `default`), or {}."""
    cid = default_character(ws)
    try:
        return load(cid, ws) if cid else {}
    except (OSError, ValueError):
        return {}


def pd_card(ws=None) -> Dict:
    cid = by_role("pd", ws)
    try:
        return load(cid, ws) if cid else {}
    except (OSError, ValueError):
        return {}


def persona_text(card: Dict) -> str:
    """The card rendered the way PERSONA.md used to read (front matter + body), for the instruction bundle."""
    d, e = card.get("data") or {}, ext(card)
    disp = e.get("display") or {}
    head = ["---", "persona: %s" % d.get("name", "")]
    head += ["%s: %s" % (k, disp[k]) for k in ("user_title", "voice") if disp.get(k)]
    head.append("---")
    body = ["# Persona", "", (d.get("description") or "").strip()]
    if (d.get("personality") or "").strip():
        body += ["", "## Voice", d["personality"].strip()]
    return "\n".join(head) + "\n\n" + "\n".join(body).strip() + "\n"


def private_text(card: Dict) -> str:
    return ((card.get("data") or {}).get("system_prompt") or "").strip()


def card_from_persona(persona_md: str, private_md: str = "", chain: Optional[List] = None) -> Dict:
    """A PD card from PERSONA.md (+ PRIVATE.md, + the PD's confirmation brains)."""
    from identity import parse_frontmatter
    fm = parse_frontmatter(persona_md)
    body = _FRONT.sub("", persona_md, count=1).strip()
    body = re.sub(r"\A#\s+[^\n]*\n+", "", body)               # the "# Persona" heading is re-added on render
    m = _VOICE.search(body)
    personality = ""
    if m:
        nxt = re.search(r"^##\s", body[m.end():], re.M)
        end = m.end() + nxt.start() if nxt else len(body)
        personality = body[m.end():end].strip()
        body = (body[:m.start()] + body[end:]).strip()
    card = new_card(fm.get("persona") or "", "pd", description=body, personality=personality,
                    display={k: fm[k] for k in ("user_title", "voice") if fm.get(k)},
                    brains={"work": chain} if chain else {})
    card["data"]["system_prompt"] = _FRONT.sub("", private_md or "", count=1).strip()
    return card


def migrate_pd(ws=None) -> Optional[str]:
    """PERSONA.md, PRIVATE.md, pd-brain.json -> the PD's card; the old files are removed. None if there is nothing
    to move or a PD character already exists."""
    ws = Path(ws or _default_ws())
    persona = ws / "PERSONA.md"
    if by_role("pd", ws) or not persona.is_file():
        return None
    private = ws / "PRIVATE.md"
    brain = ws / "pd-brain.json"
    try:
        chain = json.loads(brain.read_text(encoding="utf-8")).get("chain") or []
    except (OSError, ValueError, AttributeError):
        chain = []
    card = card_from_persona(persona.read_text(encoding="utf-8"),
                             private.read_text(encoding="utf-8") if private.is_file() else "", chain)
    cid = new_id()
    save(cid, card, ws)
    for f in (persona, private, brain):
        if f.is_file():
            f.unlink()
    return cid


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
    tmp.write_text(head + "\n".join(kept) + "\n", encoding="utf-8")
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
            "Facts only, one per line starting with \"- \", in Korean. No work topics, no secrets. If nothing is worth "
            "keeping, answer NONE.\n\n%s" % (user_word, name, talk))


def parse_memory_lines(text: str) -> List[str]:
    return [m.group(1).strip() for m in re.finditer(r"^\s*-\s+(.+)$", text or "", re.M)][:3]


# ------------------------------------------------------------------ art (CHARACTER_ART_v1)
# One image format for every character, so image agents can follow it (skill `character-art`). Files live next to
# the card so they travel with it:
#   avatar.webp                  512x512 badge, the base look, face centred, readable as a 56px circle
#   avatar/<provider>.webp       512x512, optional "wig" per brain: same face, only hair colour/cut and outfit change
#   sprites/<framing>/<label>.webp  optional standing sprites for a character-only (desktop) view with speech
#                                bubbles: transparent, one canvas and one anchor per framing, the same scale for every
#                                label so swapping an expression never moves the body. Labels are SillyTavern's
#                                expression-sprite labels; `neutral` is required once a framing exists.
#   visual.md                    the character's visual lock sheet (locks, base look, wig table, rejected)
# A .png of the same name may sit beside any .webp as the master; the page serves the .webp.

ART_SIZE = (512, 512)
ART_MAX_BYTES = 200 * 1024
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
    dirs = [("avatar", set(providers), "provider", ART_SIZE, ART_MAX_BYTES, False)]
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
        if f.suffix == ".png" and not f.with_suffix(".webp").is_file():
            problems.append("%s: a .png master needs its .webp beside it (the page serves .webp)" % rel)
    return problems
