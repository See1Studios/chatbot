"""Emotion tags in assistant text become one `emotion` SSE event per turn (#251; moved out of server.py, pew/N1c).

parse(text) finds a label in a sentence: `*expression: happy*`, `[emotion: sad]`, a bare `[happy]`, or a known keyword at
the start or end. Tracker follows one SSE stream: fed each event, it returns the label to send at most once per turn
-- as soon as a streamed sentence carries one, else from the final result -- and resets when the turn ends.
Standard library only.
"""
from __future__ import annotations

import re
from typing import Optional

KEYWORDS = (
    "happy", "sad", "angry", "surprised", "neutral",
    "embarrassed", "thinking", "smiling",
)
_BRACKET_EXTRA = ("joy", "shy", "serious", "sorrow", "tired", "smile", "grin")
_KEYWORD_RE = "|".join(KEYWORDS)
_TURN_END = ("result", "error", "stopped", "interrupted", "user_ack")
_TEXT_EVENTS = ("delta", "assistant", "message")


def parse(text: str) -> Optional[str]:
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    # a: *expression: happy* / *emotion: happy* (표정 is the older Korean tag name: records keep it)  l10n-ok
    m = re.search(r"\*\s*(?:표정|emotion|expression)\s*:\s*([a-zA-Z_-]+)\s*\*", s, re.IGNORECASE)   # l10n-ok: a tag name, not a guess
    if m:
        return m.group(1).lower()
    # b: [expression:sad] / [emotion: sad], then a bare [happy]
    m = re.search(r"\[\s*(?:표정|emotion|expression)\s*:\s*([a-zA-Z_-]+)\s*\]", s, re.IGNORECASE)   # l10n-ok: a tag name
    if m:
        return m.group(1).lower()
    for m in re.finditer(r"\[\s*([a-zA-Z_-]+)\s*\]", s):
        val = m.group(1).lower()
        if val in KEYWORDS or val in _BRACKET_EXTRA:
            return val
    # c: a keyword at the very start or end of the text
    m = re.search(r"^\s*(?:[^\w\s]\s*)*\b(" + _KEYWORD_RE + r")\b", s, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    m = re.search(r"\b(" + _KEYWORD_RE + r")\b\s*(?:[^\w\s]\s*)*$", s, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


class Tracker:
    """Per SSE connection. feed(ev) -> label to emit now, or None."""

    def __init__(self) -> None:
        self.sent = False
        self.buf = ""

    def feed(self, ev: dict) -> Optional[str]:
        ev_type = ev.get("event") or ev.get("type") or ""
        if ev_type in _TURN_END:
            label = None
            if not self.sent and ev_type == "result":
                label = parse(str(ev.get("text") or self.buf or ""))
            self.sent, self.buf = False, ""
            return label
        if self.sent or ev_type not in _TEXT_EVENTS:
            return None
        chunk = str(ev.get("text") or ev.get("message") or ev.get("content") or "")
        if not chunk:
            return None
        self.buf += chunk
        parts = re.split(r"(?<=[.!?\n])", self.buf)
        completed, current = parts[:-1], parts[-1]
        label = None
        for s in completed:
            label = parse(s)
            if label:
                break
        if not label and current:
            label = parse(current)
        if label:
            self.sent, self.buf = True, ""
        else:
            self.buf = current
        return label
