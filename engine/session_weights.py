"""Session weight, token accounting, inquiry classification, and prompt templates.

Extracted from session.py during modular refactoring.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import i18n
from host_config import (
    HARD_CHARS,
    HARD_DB_BYTES,
    HARD_TOKENS,
    HARD_TURNS,
    HOME,
    SOFT_CHARS,
    SOFT_DB_BYTES,
    SOFT_TOKENS,
    SOFT_TURNS,
)
from identity import self_label, user_title, voice_phrase


def _conversation_db_path(cid: Optional[str]) -> Optional[Path]:
    if not cid:
        return None
    return HOME / ".gemini" / "antigravity-cli" / "conversations" / f"{cid}.db"


def _conversation_db_size(cid: Optional[str]) -> int:
    p = _conversation_db_path(cid)
    if not p:
        return 0
    try:
        return p.stat().st_size if p.exists() else 0
    except OSError:
        return 0


def _hist_stats(history: List[dict]) -> tuple:
    turns = 0
    chars = 0
    for h in history or []:
        if h.get("role") not in ("user", "assistant"):
            continue
        turns += 1
        chars += len(str(h.get("text") or ""))
    return turns, chars


def _turn_billed(u: dict) -> int:
    """This request's billed tokens. `total_tokens` is already in+out on every
    adapter we store; do not subtract cache_read — that counter is often a
    CLI lifetime/session cache and is larger than this turn's input."""
    tot = int(u.get("total_tokens") or 0)
    if tot:
        return tot
    return int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)


def _current_context_tokens(history: List[dict]) -> int:
    """Occupancy of the last request: the last model call's prompt when the adapter recorded it (`context_tokens`,
    CONTEXT_METRIC_v1 -- agy's turn usage sums every call of the turn: a 60k context with eight tool steps read as
    480k), else that turn's `input_tokens` (prompt size).

    Not a sum across turns, and not `total_tokens` (that includes output).
    Not `input - cache_read` — cache_read is not a subset of this turn's input
    (agy first turns: input ~75k, cache_read millions)."""
    for h in reversed(history or []):
        u = h.get("usage")
        if not isinstance(u, dict):
            continue
        if int(u.get("context_tokens") or 0):
            return int(u["context_tokens"])
        inp = int(u.get("input_tokens") or 0)
        if inp:
            return inp
        tot = int(u.get("total_tokens") or 0)
        if tot:
            return tot
    return 0


def _billed_tokens(history: List[dict]) -> int:
    s = 0
    for h in history or []:
        u = h.get("usage")
        if isinstance(u, dict):
            s += _turn_billed(u)
    return s


def _session_weight(
    history: List[dict],
    conversation_id: Optional[str],
    soft_tokens: int = SOFT_TOKENS,
    hard_tokens: int = HARD_TOKENS,
) -> dict:
    """soft_tokens/hard_tokens default to agy's own constants but are meant to
    be passed explicitly by the caller (AgentSession.weight() -> this session's
    adapter.soft_hard_tokens(model)) -- Multi-Provider plan Phase 0.5. claude's
    real 200k context window makes agy's 400k HARD_TOKENS meaningless for a
    claude session (never trips, or trips too late relative to that window)."""
    turns, chars = _hist_stats(history)
    db_bytes = _conversation_db_size(conversation_id)
    context_tokens = _current_context_tokens(history)
    billed_tokens = _billed_tokens(history)
    level = "ok"
    if turns >= HARD_TURNS or chars >= HARD_CHARS or db_bytes >= HARD_DB_BYTES or context_tokens >= hard_tokens:
        level = "hard"
    elif turns >= SOFT_TURNS or chars >= SOFT_CHARS or db_bytes >= SOFT_DB_BYTES or context_tokens >= soft_tokens:
        level = "soft"
    return {
        "level": level,
        "turns": turns,
        "chars": chars,
        "db_bytes": db_bytes,
        "total_tokens": context_tokens,
        "context_tokens": context_tokens,
        "billed_tokens": billed_tokens,
        "soft_turns": SOFT_TURNS,
        "hard_turns": HARD_TURNS,
        "soft_tokens": soft_tokens,
        "hard_tokens": hard_tokens,
        **(i18n.field("message", "srv.session_heavy") if level != "ok" else {}),
    }


def _is_inquiry(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("/btw ") or t.startswith("/btw\n") or t == "/btw":
        return True
    if t.startswith("/q ") or t.startswith("/queue ") or t.startswith("/next "):
        return False
    # NO_GUESS_BTW_v1: only an explicit /btw goes aside -- question marks, endings and question words guessed per
    # language (they matched Korean and English only), so the same message steered in one language and went aside in
    # another
    return False


def _btw_prompt(query: str, is_active: bool, context_snippets: List[str], is_silent: bool = False) -> str:
    """Prompt for a /btw side question (agent-facing: English). Who the chatbot is, who the user is and the tone all
    come from the instruction files (identity.py) -- no name lives here. It answers in the question's language."""
    ut = user_title()
    voice = voice_phrase()
    tone = f"in 2-3 sentences, {voice}" if voice else "in 2-3 sentences"
    return (
        f"You are {self_label()}. (The user: {ut})\n"
        + ("A side question (/btw) that came in while the main work runs in the background.\n" if is_active
           else "A question that came in while nothing is running.\n")
        + ("\n".join(context_snippets) + "\n" if context_snippets else "")
        + f"{ut}'s question: {query}\n\n"
        + (f"Answer at once, briefly {tone}, with only what matters, without disturbing the main work."
           + (" The main work has been silent for a while: say plainly it may be delayed or stuck; do not claim it is "
              "going fine." if is_silent else "") if is_active
           else f"Say plainly where things stand (waiting, finished, stopped, delayed or stuck) and answer {ut}'s "
                f"question briefly {tone}. Nothing is running in the background: never claim the work is going fine.")
        + " Answer in the language of the question."
    )


def _handoff_prompt(dialogue_blob: str) -> str:
    """Prompt for the handoff summariser (agent-facing: English; identity from identity.py). The summary is in the
    talk's own language, since the next session carries the same talk on."""
    return (
        f"You summarize a handover for {self_label()}.\n"
        "From the talk below, write the key context to hand to a new session, in about 3-4 lines, in the language "
        "the talk is in.\n\n"
        "[Talk]\n"
        f"{dialogue_blob}\n\n"
        "[Format]\n"
        "- Main topic in progress:\n"
        "- Settled points and files:\n"
        f"- {user_title()}'s latest requests:"
    )
