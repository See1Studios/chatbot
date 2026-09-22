"""Session weight, token accounting, inquiry classification, and prompt templates.

Extracted from session.py during modular refactoring.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

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
    """Occupancy of the last request: that turn's `input_tokens` (prompt size).

    Not a sum across turns, and not `total_tokens` (that includes output).
    Not `input - cache_read` — cache_read is not a subset of this turn's input
    (agy first turns: input ~75k, cache_read millions)."""
    for h in reversed(history or []):
        u = h.get("usage")
        if not isinstance(u, dict):
            continue
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
    be passed explicitly by the caller (AgySession.weight() -> this session's
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
        "message_ko": (
            "세션이 길어져서 느려질 수 있어요. 새 채팅을 권장합니다"
            if level != "ok"
            else ""
        ),
    }


def _is_inquiry(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("/btw ") or t.startswith("/btw\n") or t == "/btw":
        return True
    if t.startswith("/q ") or t.startswith("/queue ") or t.startswith("/next "):
        return False
    if re.search(r"[\?？]\s*$", t):
        return True
    if re.match(r"^(what|why|how|where|when|who|is|are|can|could)\b", t, re.I):
        return True
    q_endings = (
        "인가", "인가요", "는가", "는가요", "은가", "은가요",
        "나요", "나", "니", "냐", "냐고", "니까", "까", "까요",
        "는지", "은지", "는지요", "지요", "죠", "건가", "건가요",
        "어때", "어때요", "뭐해", "뭐하니", "뭐야", "을까", "ㄹ까",
    )
    clean_end = re.sub(r"[.!~^;\s]+$", "", t)
    for qe in q_endings:
        if clean_end.endswith(qe):
            return True
    if len(t) <= 40:
        q_words = ("어디", "어떻게", "얼마나", "언제", "왜", "무슨", "무엇", "몇", "진행상황", "진행 상태", "현재 상태")
        for qw in q_words:
            if qw in t:
                return True
    return False


def _btw_prompt(query: str, is_active: bool, context_snippets: List[str]) -> str:
    """Prompt for a /btw side question. Who the chatbot is, who the user is and the
    tone all come from the instruction files (identity.py) -- no name lives here."""
    ut = user_title()
    voice = voice_phrase()
    tone = f"2~3문장의 {voice} " if voice else "2~3문장으로 "
    return (
        f"Sphere DiskStation {self_label()}입니다. (사용자: {ut})\n"
        + ("백그라운드 메인 작업 진행 중 들어온 샛길 질문(/btw)입니다.\n" if is_active else "현재 대기 중인 상태에서 들어온 질문입니다.\n")
        + ("\n".join(context_snippets) + "\n" if context_snippets else "")
        + f"{ut} 질문: {query}\n\n"
        + (f"메인 작업을 방해하지 않는 핵심만 {tone}간결하게 즉답하세요." if is_active
           else f"현재 상태(작업 대기/완료/중단)를 사실대로 알리고 {ut}의 질문에 {tone}간결하게 답하세요. 백그라운드에서 작업 중이 아니므로 절대 거짓으로 진행 중이라고 꾸며내지 마세요.")
    )


def _handoff_prompt(dialogue_blob: str) -> str:
    """Prompt for the handoff summariser (same rule: identity from identity.py)."""
    return (
        f"Sphere DiskStation {self_label()} 챗봇 인계 요약기입니다.\n"
        "다음 대화 내역을 바탕으로 새 세션에 전달할 핵심 맥락을 3~4줄 내외로 한국어로 간결하게 요약하세요.\n\n"
        "[대화 내역]\n"
        f"{dialogue_blob}\n\n"
        "[작성 양식]\n"
        "- 진행 중인 핵심 주제:\n"
        "- 확인/결정된 사항 및 파일:\n"
        f"- {user_title()}의 최근 요구사항:"
    )
