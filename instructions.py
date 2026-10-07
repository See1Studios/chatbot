"""Host-side instruction bundle (docs/plans/instruction-architecture.md, P2).

One text, assembled by the host, that every provider gets the same way
(AgentSession._send_direct() prepends it to the first turn; the HTTP adapter
sends it as the system message). Providers' own cwd/ancestor auto-discovery
of AGENTS.md / CLAUDE.md / skills differs per CLI and is NOT relied on --
the bundle is the one channel that is identical everywhere.

Layers: LAYERS below is the one list (CONTEXT_LAYERS_v1, docs/plans/archive/2026/layered-context-architecture.md lca/A) -- each
layer's id, kind and modes; `layer_texts` builds the ones a mode takes and `build_instruction_bundle` joins them.
  rules    charter, lore, card, role packs / private rules  (static, hashed; joined with --- and macros resolved)
  index    skill index                                     (static, hashed)
  dynamic  memories, name changes, status                  (not hashed)

`hash` covers only the static layers, so editing memory never re-injects
the bundle; editing the rules/persona/skills does.
"""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from host_config import WORKSPACE

try:  # the candidate count is a convenience; a missing core module must not stop the bundle
    import observations
except Exception:  # noqa: BLE001
    observations = None

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



def _persona_text(character: str = "") -> str:
    """The character's card as the bundle shows it (characters.persona_text) + its own work instructions; "" when
    there is no card (CARD_ONLY_v1)."""
    card = _card(character)
    if card:
        import characters
        work = ((characters.ext(card).get("work") or {}).get("instructions") or "").strip()
        return characters.persona_text(card).strip() + ("\n\n## How you work\n" + work if work else "")
    return ""


NO_ROLE_NOTE = ("[No role] You hold no role in the team: talk and help, but plans and handing out work are {{default}}'s, and "
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
    seen, texts = set(), []   # ROLE_LINES_ONCE_v1: a line two held packs share (the handoff line) is shown once
    for p in packs:
        lines = [l for l in (p["text"] or "").split("\n") if not (l.strip() and l in seen)]
        seen.update(l for l in lines if l.strip())
        if "\n".join(lines).strip():
            texts.append("\n".join(lines))
    return "\n\n".join(texts)


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


def lore_matches(character: str = "", history: Optional[Union[List, str]] = None) -> str:
    """LORE_TURN_v1 (layered-context-architecture lca/D): the keyword entries the recent talk matches, joined -- not the
    constant ones, which the bundle already carries. A CLI session's bundle is built without the talk, so these reach
    it as a per-turn block instead (session_turn._context_lore)."""
    if not history:
        return ""
    try:
        import characters
        cid = _cid(character)
        lb = characters.load_lorebook(cid, WORKSPACE) if cid else None
    except Exception:  # noqa: BLE001
        return ""
    found = [e for e in match_lorebook_entries(lb, history) if not e.get("constant") and e.get("content")]
    return "\n\n".join(e["content"] for e in found)


def _skills_text(character: str = "") -> str:
    """Enabled skills; a skill a held role's pack lists is shown only to that role's holders. DEFAULT_ROLE_v1: a skill
    no held role claims (a newly installed one, or one whose role nobody holds) is the default character's -- the one
    the team opens with and who hands work out -- not everyone's (operator 2026-10-06: "when unsure, to the lead first")."""
    idx = skill_index()
    try:
        import characters
        cid = _cid(character)
        claimed = {sk: r for r in characters.roles(WORKSPACE) for sk in characters.role_pack(r, WORKSPACE)["skills"]}
        mine = set(characters.roles_of(cid, WORKSPACE))
        default = cid == characters.default_character(WORKSPACE)
        idx = [(n, d) for n, d in idx if (claimed[n] in mine if n in claimed else default)]
    except Exception:  # noqa: BLE001
        pass
    if not idx:
        return ""
    # the live workspace (uds/F: ~/.pe), never the repo's data/ -- a stale copy there lacks newer skills
    lines = ["[Skill index] When needed, read `%s/.agents/skills/<name>/SKILL.md` and follow its steps." % WORKSPACE]
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
    return "[Long-term memory snapshot]\n" + text


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
    return f"[Self-improvement status] {n_open} open observations · {n_cand} unreviewed candidates · last review {last}"


def _card(character: str) -> Dict:
    """The character's card; "" = the chatbot itself (the character with role pd)."""
    try:
        import characters
        cid = _cid(character)
        return characters.load(cid, WORKSPACE) if cid else {}
    except Exception:  # noqa: BLE001
        return {}


PRIVATE_SESSION_NOTE = ("[Private session] A private conversation, kept apart from work. Work tools and work memory "
                        "are closed; do not work or bring up work. The host keeps what is "
                        "worth remembering in your private memory when the session closes. The user switches with "
                        "`/private on|off` or the heart button; asked for work, ask them to switch with `/private off`. "
                        "Follow the character's private rules below.")
# PRIVATE_BUDGET_v1: a private session gets the charter's preamble and these sections only. The rest is work
# procedure it cannot use, and "## Memory" would point it at the work memory tool.
PRIVATE_CHARTER_SECTIONS = ("Scope",)


def _dev_charter() -> str:
    """DEV_SPLIT_v1 (prop/G): the dev build's own rules, a layer apart from the charter -- the two never share a file.
    Only the dev build takes it (host_config.EDITION, read at call time): a shipped install never does, whatever files
    its workspace holds."""
    import host_config
    return _read(WORKSPACE / "DEV-CHARTER.md") if host_config.EDITION == "dev" else ""


def _private_charter() -> str:
    text = re.sub(r"\A---\n.*?\n---\n*", "", _read(WORKSPACE / "AGENTS.md"), flags=re.S)
    parts = re.split(r"(?m)^(?=## )", text)
    keep = [parts[0].strip()] + [x.strip() for x in parts[1:] if x[3:].split("\n", 1)[0].strip() in PRIVATE_CHARTER_SECTIONS]
    return "\n\n".join(t for t in keep if t)


WORK, PRIVATE = ("work",), ("private",)
BOTH = WORK + PRIVATE


@dataclass(frozen=True)
class Layer:
    id: str
    kind: str                # "rules" (static, joined with --- under macros) | "index" (static) | "dynamic" | "turn"
    modes: Tuple[str, ...]   # the session modes that take it (D-6: a private session never takes a work layer)
    text: Callable           # (ctx) -> str
    required: bool = False   # empty -> a context alert (CONTEXT_ALERT_v1)


def _ctx(mode: str, character: str, history) -> Dict:
    cid = _cid(character)
    return {"mode": mode, "character": character, "cid": cid, "card": _card(character), "history": history,
            "lore": lorebook_context(character, history)}


def _private_rules(c: Dict) -> str:
    import characters
    rules = characters.private_text(c["card"])
    return PRIVATE_SESSION_NOTE + ("\n\n" + rules if rules else "")


def _private_protocol(c: Dict) -> str:
    import private_engine
    return private_engine.render_protocol_text(c["card"])


def _private_persona(c: Dict) -> str:
    import characters
    return characters.persona_text(c["card"]).strip()


def _private_memory(c: Dict) -> str:
    import characters
    import memory_relationship
    memory = characters.read_private_memory(c["cid"], WORKSPACE) if c["cid"] else ""
    return memory_relationship.injection(c["cid"], WORKSPACE, memory)


# The order is the bundle's order. A new layer is one row here: its kind decides how it joins and whether the hash
# covers it, its modes decide where it goes.
LAYERS: Tuple[Layer, ...] = (
    Layer("charter", "rules", WORK, lambda c: _read(WORKSPACE / "AGENTS.md"), required=True),
    Layer("dev_charter", "rules", WORK, lambda c: _dev_charter()),
    Layer("private_charter", "rules", PRIVATE, lambda c: _private_charter(), required=True),
    Layer("lore_before", "rules", BOTH, lambda c: c["lore"]["before_char"]),
    Layer("persona", "rules", WORK, lambda c: _persona_text(c["character"]), required=True),
    Layer("private_persona", "rules", PRIVATE, _private_persona, required=True),
    Layer("lore_after", "rules", BOTH, lambda c: c["lore"]["after_char"]),
    Layer("roles", "rules", WORK, lambda c: _roles_text(c["character"])),
    Layer("private_rules", "rules", PRIVATE, _private_rules),
    Layer("private_protocol", "rules", PRIVATE, _private_protocol),
    Layer("skills", "index", WORK, lambda c: _skills_text(c["character"])),
    Layer("house_memory", "dynamic", WORK, lambda c: _memory_text()),
    Layer("own_memory", "dynamic", WORK, lambda c: _own_memory_text(c["character"])),
    Layer("private_memory", "dynamic", PRIVATE, _private_memory),
    Layer("names", "dynamic", BOTH, lambda c: _names_text()),
    Layer("status", "dynamic", WORK, lambda c: _status_text()),
    # per turn, never in the bundle: what the talk just matched (a CLI session's bundle is built without the talk)
    Layer("lore_match", "turn", BOTH, lambda c: lore_matches(c["character"], c.get("history"))),
)


def layer_texts(mode: str = "work", character: str = "", history: Optional[Union[List, str]] = None
                ) -> List[Tuple[Layer, str]]:
    """The layers a session of `mode` takes, each with its text ("" when it has nothing), in bundle order. A rules
    layer comes with its macros resolved."""
    import characters
    c = _ctx(mode, character, history)
    out = []
    for layer in LAYERS:
        if mode not in layer.modes:
            continue
        text = layer.text(c) or ""
        if layer.kind == "rules":
            text = characters.render_macros(text, c["cid"], WORKSPACE)   # CARD_MACROS_v1
        out.append((layer, text))
    return out


def _rules_text(character: str = "", history: Optional[Union[List, str]] = None) -> str:
    """The work bundle's rules layers joined (charter, lore, card, role packs): what the budget guard measures."""
    return "\n\n---\n\n".join(t for layer, t in layer_texts("work", character, history) if layer.kind == "rules" and t)


def build_instruction_bundle(mode: str = "work", character: str = "", history: Optional[Union[List, str]] = None) -> Dict[str, str]:
    """{"text": full bundle, "hash": digest of the static layers, "layers": what each non-empty layer gave (id, kind,
    chars, hash) for the injection record (CONTEXT_LOG_v1)}. Empty text
    when there are no rule files at all (caller then injects nothing).
    A private session (SESSION_SPLIT_v1) gets the character's private rules and private memory instead of skills,
    work memory and the status badge; it needs the character's card."""
    mode = "private" if mode == "private" else "work"
    if mode == "private" and not _card(character):
        return {"text": "", "hash": ""}
    got = layer_texts(mode, character, history)
    rules = "\n\n---\n\n".join(t for layer, t in got if layer.kind == "rules" and t)   # = _rules_text for work
    static = "\n\n".join(t for t in [rules] + [t for layer, t in got if layer.kind == "index"] if t)
    if not static:
        return {"text": "", "hash": ""}
    dynamic = [(layer.id, t) for layer, t in got if layer.kind == "dynamic" and t]
    if mode == "private":   # the relationship block carries its own spacing; the rest follow a blank line
        text = static + "".join(t if lid == "private_memory" else "\n\n" + t for lid, t in dynamic)
    else:
        text = "\n\n".join([static] + [t for _lid, t in dynamic])
    return {"text": text, "hash": hashlib.sha256(static.encode("utf-8")).hexdigest()[:16], "mode": mode,
            "static_bytes": len(static.encode("utf-8")),
            "layers": [{"id": layer.id, "kind": layer.kind, "chars": len(t),
                        "hash": hashlib.sha256(t.encode("utf-8")).hexdigest()[:8]} for layer, t in got
                       if t and layer.kind != "turn"]}


def _budget() -> int:
    """bundle_budget.json's static_max_bytes (the operator's number); 0 when it cannot be read."""
    try:
        import json
        return int(json.loads((Path(__file__).resolve().parent / "bundle_budget.json").read_text(encoding="utf-8"))
                   ["static_max_bytes"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def context_alerts(bundle: Dict, character: str = "") -> List[Dict]:
    """CONTEXT_ALERT_v1 (layered-context-architecture lca/F): what is wrong with a bundle about to go in --
    over_budget (its static layers past bundle_budget.json), missing (a required layer empty), leak (a private bundle
    holding a work-only layer's text). [] when it is fine."""
    out: List[Dict] = []
    mode = bundle.get("mode") or "work"
    limit = _budget()
    if limit and int(bundle.get("static_bytes") or 0) > limit:
        out.append({"kind": "over_budget", "static_bytes": bundle["static_bytes"], "limit": limit})
    have = {x["id"] for x in bundle.get("layers") or []}
    missing = [layer.id for layer in LAYERS if layer.required and mode in layer.modes and layer.id not in have]
    if missing:
        out.append({"kind": "missing", "layers": missing})
    if mode == "private":
        text = bundle.get("text") or ""
        own = {t.strip() for _layer, t in layer_texts("private", character)}
        leaked = [layer.id for layer, t in layer_texts("work", character)
                  if "private" not in layer.modes and len(t.strip()) > 20 and t.strip() not in own and t.strip() in text]
        if leaked:
            out.append({"kind": "leak", "layers": leaked})
    return out
