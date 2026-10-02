"""Host-side instruction bundle (docs/plans/instruction-architecture.md, P2).

One text, assembled by the host, that every provider gets the same way
(AgentSession._send_direct() prepends it to the first turn; the HTTP adapter
sends it as the system message). Providers' own cwd/ancestor auto-discovery
of AGENTS.md / CLAUDE.md / skills differs per CLI and is NOT relied on --
the bundle is the one channel that is identical everywhere.

Layers (L0 = always injected):
  rules   AGENTS.md + the character's card  (static, hashed)
  skills  workspace skill index              (static, hashed)
  memory  MEMORY.md snapshot, if it has facts (dynamic, not hashed)
  status  open observations / last review    (dynamic, not hashed)

`hash` covers only the static layers, so editing memory never re-injects
the bundle; editing the rules/persona/skills does.
"""
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from host_config import WORKSPACE

try:  # the candidate count is a convenience; a missing core module must not stop the bundle
    import observations
except Exception:  # noqa: BLE001
    observations = None

RULE_BUNDLE_FILES = ["AGENTS.md"]
WS_SKILLS_DIR = WORKSPACE / ".agents" / "skills"
MEMORY_FILE = WORKSPACE / "memory" / "MEMORY.md"
OBS_DIR = WORKSPACE / "skill-observations" / "observation-log"
LAST_REVIEW_FILE = WORKSPACE / "skill-observations" / "last-review-date.txt"

_FACT_LINE = re.compile(r"^\s*(?:[-*]\s+\S|\[\d{4}-\d{2}-\d{2}\])")
_SKILL_DESC_MAX = 80


def extract_yaml_desc(txt: str) -> str:
    """Parse a SKILL.md frontmatter `description:` field, handling both inline
    values and YAML folded/literal block scalars (`description: >` / `|`)."""
    m = re.search(r"^description:\s*(.*)$", txt, re.MULTILINE)
    if not m:
        return ""
    first = m.group(1).strip()
    if first in (">", "|", ">-", "|-", ">+", "|+", ""):
        block = []
        for line in txt[m.end():].splitlines():
            if not line.strip():
                if first.startswith("|"):
                    block.append("")
                continue
            if line[:1] in (" ", "\t"):
                block.append(line.strip())
            else:
                break
        return ("\n".join(block) if first.startswith("|") else " ".join(block)).strip()
    if len(first) >= 2 and first[0] == first[-1] and first[0] in ('"', "'"):
        first = first[1:-1]
    return first


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def skill_index() -> List[Tuple[str, str]]:
    """(name, one-line description) for enabled workspace skills. A leading
    underscore disables a skill (same rule as the host's skill listing)."""
    out: List[Tuple[str, str]] = []
    if not WS_SKILLS_DIR.exists():
        return out
    for p in sorted(WS_SKILLS_DIR.iterdir()):
        if not p.is_dir() or p.name.startswith((".", "_")):
            continue
        sm = p / "SKILL.md"
        if not sm.exists():
            continue
        desc = extract_yaml_desc(_read(sm)[:2000])
        desc = re.sub(r"\s+", " ", desc).strip()
        if len(desc) > _SKILL_DESC_MAX:
            desc = desc[: _SKILL_DESC_MAX - 1].rstrip() + "…"
        out.append((p.name, desc))
    return out


def _cid(character: str = "") -> str:
    """The character a bundle is for: the given id or role, else the team's default character (TEAM_ROLES_v1)."""
    try:
        import characters
        if character:
            return characters.resolve(character, WORKSPACE) or character
        return characters.default_character(WORKSPACE)
    except Exception:  # noqa: BLE001
        return character or ""


def character_identity(character: str = "") -> Dict[str, str]:
    """The identity fields {name, persona, title, user_title, voice} for the specified character,
    or the default character if empty."""
    card = _card(character)
    if not card:
        return {"name": "", "persona": "", "title": "", "user_title": "", "voice": ""}
    import characters
    cid = _cid(character)
    char_name = characters.name(card)
    char_title = characters.title(card, cid, WORKSPACE)
    return {
        "name": char_name or char_title,
        "persona": char_name,
        "title": char_title,
        "user_title": characters.user_title(card, WORKSPACE),
        "voice": str((characters.ext(card).get("display") or {}).get("voice") or "").strip(),
    }


def _persona_text(character: str = "") -> str:
    """The character's card as the bundle shows it (characters.persona_text) + its own work instructions; "" when
    there is no card (CARD_ONLY_v1)."""
    card = _card(character)
    if card:
        import characters
        work = ((characters.ext(card).get("work") or {}).get("instructions") or "").strip()
        return characters.persona_text(card).strip() + ("\n\n## How you work\n" + work if work else "")
    return ""


NO_ROLE_NOTE = ("[No role] You hold no role in the team: talk and help, but plans and delegation are {{default}}'s, and "
                "the house memory is read-only for you.")


def _roles_text(character: str = "") -> str:
    """The every-turn part of each role pack the character holds (roles/<role>/ROLE.md)."""
    try:
        import characters
        cid = _cid(character)
        packs = [characters.role_pack(r, WORKSPACE) for r in characters.roles_of(cid, WORKSPACE)] if cid else []
    except Exception:  # noqa: BLE001
        return ""
    if not cid:
        return ""
    if not packs:
        return NO_ROLE_NOTE
    return "\n\n".join(p["text"] for p in packs if p["text"])


LOREBOOK_SCAN_DEPTH = 5
LOREBOOK_MAX_ENTRIES = 3
LOREBOOK_MAX_ENTRY_CHARS = 500


def match_lorebook_entries(
    lorebook: Optional[Dict],
    history: Optional[Union[List, str]],
    max_entries: int = LOREBOOK_MAX_ENTRIES,
    scan_depth: int = LOREBOOK_SCAN_DEPTH,
    max_chars: int = LOREBOOK_MAX_ENTRY_CHARS,
) -> List[Dict]:
    """Find matching lorebook entries from recent history messages.

    - Scans last `scan_depth` messages in history
    - Matches if any entry key appears in history text (case-insensitive) or entry is constant
    - Filters to enabled entries only
    - Orders by priority descending
    - Limits to `max_entries` (default 3)
    - Truncates each entry content to `max_chars` (default 500)
    """
    if not lorebook or not isinstance(lorebook, dict):
        return []

    entries = lorebook.get("entries")
    if isinstance(entries, dict):
        entries = list(entries.values())
    if not isinstance(entries, list) or not entries:
        return []

    # Extract text from the last `scan_depth` messages
    scan_text = ""
    if history:
        if isinstance(history, str):
            scan_text = history
        elif isinstance(history, list):
            recent = history[-scan_depth:] if scan_depth > 0 else history
            parts = []
            for item in recent:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    txt = item.get("text") or item.get("content") or item.get("message") or ""
                    if txt:
                        parts.append(str(txt))
            scan_text = " ".join(parts)

    scan_lower = scan_text.lower()

    matched = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        # enabled check
        is_enabled = raw.get("enabled")
        if is_enabled is None:
            is_enabled = not bool(raw.get("disable") or raw.get("disabled"))
        if not is_enabled:
            continue

        # keys
        keys = raw.get("keys")
        if keys is None:
            keys = raw.get("key")
        if isinstance(keys, str):
            key_list = [k.strip() for k in keys.split(",") if k.strip()]
        elif isinstance(keys, list):
            key_list = [str(k).strip() for k in keys if str(k).strip()]
        else:
            key_list = []

        is_constant = bool(raw.get("constant"))
        hit = is_constant
        if not hit and scan_lower and key_list:
            for k in key_list:
                if k.lower() in scan_lower:
                    hit = True
                    break

        if hit:
            # priority
            try:
                prio = int(raw.get("priority") if raw.get("priority") is not None
                           else raw.get("order") if raw.get("order") is not None
                           else raw.get("insertion_order") if raw.get("insertion_order") is not None
                           else 10)
            except (ValueError, TypeError):
                prio = 10

            # position
            pos = raw.get("position")
            if pos in (0, "0") or (isinstance(pos, str) and "before" in pos.lower()):
                pos_str = "before_char"
            else:
                pos_str = "after_char"

            content = str(raw.get("content") or "").strip()
            if max_chars > 0 and len(content) > max_chars:
                content = content[:max_chars]

            entry_copy = dict(raw)
            entry_copy["priority"] = prio
            entry_copy["position"] = pos_str
            entry_copy["content"] = content
            matched.append(entry_copy)

    # Sort by priority descending (stable sort preserves original ordering on ties)
    matched.sort(key=lambda e: e["priority"], reverse=True)

    if max_entries > 0:
        matched = matched[:max_entries]

    return matched


def lorebook_context(
    character: str = "",
    history: Optional[Union[List, str]] = None,
    ws=None,
    max_entries: int = LOREBOOK_MAX_ENTRIES,
    scan_depth: int = LOREBOOK_SCAN_DEPTH,
    max_chars: int = LOREBOOK_MAX_ENTRY_CHARS,
) -> Dict[str, str]:
    """Return {'before_char': '...', 'after_char': '...'} containing matched lorebook content."""
    target_ws = ws or WORKSPACE
    try:
        import characters
        cid = _cid(character)
        lb = characters.load_lorebook(cid, target_ws) if cid else None
    except Exception:  # noqa: BLE001
        return {"before_char": "", "after_char": ""}

    if not lb:
        return {"before_char": "", "after_char": ""}

    matched = match_lorebook_entries(lb, history, max_entries=max_entries, scan_depth=scan_depth, max_chars=max_chars)
    before_parts = [e["content"] for e in matched if e.get("position") == "before_char" and e.get("content")]
    after_parts = [e["content"] for e in matched if e.get("position") == "after_char" and e.get("content")]

    return {
        "before_char": "\n\n".join(before_parts),
        "after_char": "\n\n".join(after_parts),
    }


def _rules_text(character: str = "", history: Optional[Union[List, str]] = None) -> str:
    lore = lorebook_context(character, history)
    parts = [t for t in (_read(WORKSPACE / "AGENTS.md"), lore["before_char"], _persona_text(character), lore["after_char"], _roles_text(character)) if t]
    import characters
    return characters.render_macros("\n\n---\n\n".join(parts), _cid(character), WORKSPACE)   # CARD_MACROS_v1


def _skills_text(character: str = "") -> str:
    """Enabled skills; a skill a role pack lists is shown only to that role's holders."""
    idx = skill_index()
    try:
        import characters
        claimed = {sk: r for r in characters.roles(WORKSPACE) for sk in characters.role_pack(r, WORKSPACE)["skills"]}
        mine = set(characters.roles_of(_cid(character), WORKSPACE))
        idx = [(n, d) for n, d in idx if n not in claimed or claimed[n] in mine]
    except Exception:  # noqa: BLE001
        pass
    if not idx:
        return ""
    lines = ["[스킬 색인] 필요할 때 `~/services/chatbot/data/workspace/.agents/skills/<이름>/SKILL.md`를 읽어 절차를 따른다."]
    lines += [f"- {name} — {desc}" if desc else f"- {name}" for name, desc in idx]
    return "\n".join(lines)


def _own_memory_text(character: str = "") -> str:
    try:
        import characters
        cid = _cid(character)
        text = _read(characters.memory_path(cid, WORKSPACE)) if cid else ""
    except Exception:  # noqa: BLE001
        return ""
    return "[Your own memory]\n" + text if any(_FACT_LINE.match(l) for l in text.splitlines()) else ""


def _names_text() -> str:
    """The name changes, so older notes and memories read right (dynamic: never part of the static budget)."""
    try:
        import character_names
        return character_names.note(WORKSPACE)
    except Exception:  # noqa: BLE001
        return ""


def _memory_text() -> str:
    text = _read(MEMORY_FILE)
    if not text or not any(_FACT_LINE.match(l) for l in text.splitlines()):
        return ""
    return "[장기 기억 스냅샷]\n" + text


def _status_text() -> str:
    n_open = 0
    if OBS_DIR.exists():
        for f in OBS_DIR.glob("*.md"):
            if re.search(r"status:\s*open", _read(f)[:400]):
                n_open += 1
    last = _read(LAST_REVIEW_FILE) or "never"
    n_cand = 0
    if observations is not None:
        try:
            n_cand = len(observations.unreviewed_candidates(OBS_DIR.parent))
        except Exception:  # noqa: BLE001
            pass
    return f"[자기개선 상태] 열린 관찰 {n_open}건 · 미검토 후보 {n_cand}건 · 마지막 리뷰 {last}"


def _card(character: str) -> Dict:
    """The character's card; "" = the chatbot itself (the character with role pd)."""
    try:
        import characters
        cid = _cid(character)
        return characters.load(cid, WORKSPACE) if cid else {}
    except Exception:  # noqa: BLE001
        return {}


PRIVATE_SESSION_NOTE = ("[Private session] A private conversation, kept apart from work. Work tools, tickets, "
                        "delegation and work memory are closed; do not work or bring up work. The host keeps what is "
                        "worth remembering in your private memory when the session closes. The user switches with "
                        "`/private on|off` or the heart button; asked for work, ask them to switch with `/private off`. "
                        "Follow the character's private rules below.")
# PRIVATE_BUDGET_v1: a private session gets the charter's preamble and these sections only. The rest is work
# procedure it cannot use, and "## Memory" would point it at the work memory tool.
PRIVATE_CHARTER_SECTIONS = ("Scope",)


def _private_charter() -> str:
    text = re.sub(r"\A---\n.*?\n---\n*", "", _read(WORKSPACE / "AGENTS.md"), flags=re.S)
    parts = re.split(r"(?m)^(?=## )", text)
    keep = [parts[0].strip()] + [x.strip() for x in parts[1:] if x[3:].split("\n", 1)[0].strip() in PRIVATE_CHARTER_SECTIONS]
    return "\n\n".join(t for t in keep if t)


def _private_bundle(character: str, history: Optional[Union[List, str]] = None) -> Dict[str, str]:
    import characters
    import private_engine
    card = _card(character)
    if not card:
        return {"text": "", "hash": ""}
    rules = characters.private_text(card)
    lore = lorebook_context(character, history)
    static = "\n\n---\n\n".join(t for t in (_private_charter(), lore["before_char"], characters.persona_text(card).strip(),
                                            lore["after_char"],
                                            PRIVATE_SESSION_NOTE + ("\n\n" + rules if rules else ""),
                                            private_engine.render_protocol_text(card)) if t)
    cid = _cid(character)
    static = characters.render_macros(static, cid, WORKSPACE)   # CARD_MACROS_v1
    memory = characters.read_private_memory(cid, WORKSPACE) if cid else ""
    text = static + ("\n\n[Private memory]\n" + memory if "- " in memory else "")
    names = _names_text()
    text += ("\n\n" + names) if names else ""
    return {"text": text, "hash": hashlib.sha256(static.encode("utf-8")).hexdigest()[:16]}


def build_instruction_bundle(mode: str = "work", character: str = "", history: Optional[Union[List, str]] = None) -> Dict[str, str]:
    """{"text": full bundle, "hash": digest of the static layers}. Empty text
    when there are no rule files at all (caller then injects nothing).
    A private session (SESSION_SPLIT_v1) gets the character's private rules and private memory instead of skills,
    work memory and the status badge."""
    if mode == "private":
        return _private_bundle(character, history=history)
    # every character alike (TEAM_ROLES_v1): charter + card + held role packs + skills; house memory, own memory,
    # status
    static = "\n\n".join(t for t in (_rules_text(character, history=history), _skills_text(character)) if t)
    if not static:
        return {"text": "", "hash": ""}
    dynamic = [t for t in (_memory_text(), _own_memory_text(character), _names_text(), _status_text()) if t]
    text = "\n\n".join([static] + dynamic)
    return {"text": text, "hash": hashlib.sha256(static.encode("utf-8")).hexdigest()[:16]}
