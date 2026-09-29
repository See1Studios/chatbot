"""PERSONAL_TURN_v1 (docs/plans/private-mode.md §8.3, W1): a work-room turn the chat agent marked as personal
(flirting, affection, private feelings) stays in the chat but never becomes work material.

Core module: standard library only; every path derives from the `sessions` argument (<data>/sessions).
One file per session, `<sid>/personal-turns.jsonl`, one line per marked turn: {"turn": <user message ts>, "ts": ...}.
A turn is keyed by its user message's ts, the same key the host uses to hand a turn to the observation log.

Readers (each closes one path into work material):
- mcp_server `_live_scope`: memory, observation and ticket tools are closed for the rest of a marked turn.
- session `_finish_turn`: a marked turn is not handed to evolution.on_turn_end (no observation candidate).
- workspace tool recall_memory.py: marked turns and their replies are not searchable from work.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Set

FILE = "personal-turns.jsonl"
NAMES = ("personal_turn",)
TOOL_DEFS = [{
    "name": "personal_turn",
    "description": ("Call once, before replying, when the user's current message in a work session is personal rather "
                    "than work: flirting, affection, private feelings. The turn stays in the chat, but it is kept out "
                    "of work memory, observations and tickets, and the work tools (memory, observation, ticket, "
                    "delegate, web) close until the turn ends (PERSONAL_TURN_v1)."),
    "inputSchema": {"type": "object", "properties": {}},
}]


def key(turn) -> str:
    """The mark key of a user message ts ("" when it has none)."""
    try:
        return "%.3f" % float(turn)
    except (TypeError, ValueError):
        return ""


def mark(sessions, sid: str, turn) -> bool:
    """Record that the turn started by the user message stamped `turn` is personal. False when it cannot be keyed."""
    k = key(turn)
    if not k or not sid or "/" in sid or "\\" in sid or sid.startswith("."):
        return False
    d = Path(sessions) / sid
    if not d.is_dir():
        return False
    with open(d / FILE, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"turn": float(k), "ts": time.time()}) + "\n")
    return True


def marked(sessions, sid: str) -> Set[str]:
    """Keys of the marked turns of session `sid` (compare with `key`)."""
    out: Set[str] = set()
    try:
        lines = (Path(sessions) / sid / FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            k = key(json.loads(line).get("turn"))
        except (ValueError, AttributeError):
            continue
        if k:
            out.add(k)
    return out


def is_marked(sessions, sid: str, turn) -> bool:
    k = key(turn)
    return bool(k) and k in marked(sessions, sid)


def running_turn(history):
    """The ts of the newest sent user message: the key of the turn a busy session is running."""
    for h in reversed(history or []):
        if h.get("role") == "user" and not h.get("queued"):
            return h.get("ts")
    return None


def tool_call(sessions, busy, active_sid) -> tuple:
    """(ok, message) for the `personal_turn` tool. `busy`: the host's running sessions ({id, mode, turn});
    the running work turn is marked -- the active one when several run."""
    work = [x for x in busy if x.get("mode") != "private"]
    if len(work) > 1:
        work = [x for x in work if x.get("id") == active_sid] or work[:1]
    if not work:
        return False, "no work turn is running"
    if not mark(sessions, str(work[0].get("id") or ""), work[0].get("turn")):
        return False, "this turn cannot be marked"
    return True, "marked personal: this turn stays out of work memory, observations and tickets"
