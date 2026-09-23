"""Host-side instruction bundle (docs/plans/instruction-architecture.md, P2).

One text, assembled by the host, that every provider gets the same way
(AgentSession._send_direct() prepends it to the first turn; the HTTP adapter
sends it as the system message). Providers' own cwd/ancestor auto-discovery
of AGENTS.md / CLAUDE.md / skills differs per CLI and is NOT relied on --
the bundle is the one channel that is identical everywhere.

Layers (L0 = always injected):
  rules   AGENTS.md + the chatbot's card     (static, hashed; PERSONA.md before the move, §12)
  skills  workspace skill index              (static, hashed)
  memory  MEMORY.md snapshot, if it has facts (dynamic, not hashed)
  status  open observations / last review    (dynamic, not hashed)

`hash` covers only the static layers, so editing memory never re-injects
the bundle; editing the rules/persona/skills does.
"""
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Tuple

from host_config import WORKSPACE

try:  # the candidate count is a convenience; a missing core module must not stop the bundle
    import observations
except Exception:  # noqa: BLE001
    observations = None

RULE_BUNDLE_FILES = ["AGENTS.md", "PERSONA.md"]
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


def _persona_text() -> str:
    """The chatbot's character card rendered as it used to read (characters.persona_text); PERSONA.md before the
    move (plan doc §12 step 2)."""
    try:
        import characters
        card = characters.pd_card(WORKSPACE)
    except Exception:  # noqa: BLE001
        card = {}
    return characters.persona_text(card).strip() if card else _read(WORKSPACE / "PERSONA.md")


def _rules_text() -> str:
    parts = [t for t in (_read(WORKSPACE / "AGENTS.md"), _persona_text()) if t]
    return "\n\n---\n\n".join(parts)


def _skills_text() -> str:
    idx = skill_index()
    if not idx:
        return ""
    lines = ["[스킬 색인] 필요할 때 `~/services/chatbot/data/workspace/.agents/skills/<이름>/SKILL.md`를 읽어 절차를 따른다."]
    lines += [f"- {name} — {desc}" if desc else f"- {name}" for name, desc in idx]
    return "\n".join(lines)


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
        return characters.load(character, WORKSPACE) if character else characters.pd_card(WORKSPACE)
    except Exception:  # noqa: BLE001
        return {}


PRIVATE_SESSION_NOTE = ("[Private session] This is a private conversation, kept apart from work. Work tools, tickets, "
                        "delegation and work memory are closed here; do not do work or bring up work memory. Follow "
                        "the private rules below.")


def _private_bundle(character: str) -> Dict[str, str]:
    import characters
    card = _card(character)
    if not card:
        return {"text": "", "hash": ""}
    rules = characters.private_text(card)
    static = "\n\n---\n\n".join(t for t in (_read(WORKSPACE / "AGENTS.md"), characters.persona_text(card).strip(),
                                            PRIVATE_SESSION_NOTE + ("\n\n" + rules if rules else "")) if t)
    cid = character or characters.by_role("pd", WORKSPACE) or ""
    memory = characters.read_private_memory(cid, WORKSPACE) if cid else ""
    text = static + ("\n\n[Private memory]\n" + memory if "- " in memory else "")
    return {"text": text, "hash": hashlib.sha256(static.encode("utf-8")).hexdigest()[:16]}


def build_instruction_bundle(mode: str = "work", character: str = "") -> Dict[str, str]:
    """{"text": full bundle, "hash": digest of the static layers}. Empty text
    when there are no rule files at all (caller then injects nothing).
    A private session (SESSION_SPLIT_v1) gets the character's private rules and private memory instead of skills,
    work memory and the status badge."""
    if mode == "private":
        return _private_bundle(character)
    static = "\n\n".join(t for t in (_rules_text(), _skills_text()) if t)
    if not static:
        return {"text": "", "hash": ""}
    dynamic = [t for t in (_memory_text(), _status_text()) if t]
    text = "\n\n".join([static] + dynamic)
    return {"text": text, "hash": hashlib.sha256(static.encode("utf-8")).hexdigest()[:16]}
