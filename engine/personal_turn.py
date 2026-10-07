"""PERSONAL_TURN_v1 (docs/plans/private-mode.md §8.3, W1): a work-room turn the chat agent marked as personal
(flirting, affection, private feelings) stays in the chat but never becomes work material.

Core module: standard library only; every path derives from the `sessions` argument (<data>/sessions).
One file per session, `<sid>/personal-turns.jsonl`, one line per marked turn: {"turn": <user message ts>, "ts": ...}.
A turn is keyed by its user message's ts, the same key the host uses to hand a turn to the observation log.

Readers (each closes one path into work material):
- mcp_server `_live_scope`: memory, observation and ticket tools are closed for the rest of a marked turn.
- session `_finish_turn`: a marked turn is not handed to evolution.on_turn_end (no observation candidate).
- workspace tool recall_memory.py: marked turns and their replies are not searchable from work.
- the page (`api`, GET /api/sessions/<sid>/personal-turns): a small lock on marked bubbles in the advanced density.
"""
from __future__ import annotations

import json
import re
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


OFFER_WINDOW_SEC = 1800   # declined moves count within this window
OFFER_MAX = 2             # personal turns in a row that may offer a move; after that, stay quiet


def moved(sessions, sid: str) -> None:
    """Record that the user left this work session for the private room (threshold.py): the move offers reset."""
    d = Path(sessions) / sid
    if d.is_dir():
        with open(d / FILE, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"moved": time.time()}) + "\n")


def offers_left(sessions, sid: str, now: float = 0.0) -> bool:
    """W2b cool-down: may this personal turn offer a move? Not after OFFER_MAX marks with no move in between
    (the user stayed at work each time), within OFFER_WINDOW_SEC."""
    now = now or time.time()
    try:
        rows = [json.loads(x) for x in (Path(sessions) / sid / FILE).read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return True
    since = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        if "moved" in r:
            since = 0
        elif now - float(r.get("ts") or 0) < OFFER_WINDOW_SEC:
            since += 1
    return since <= OFFER_MAX


def tool_call(sessions, busy, active_sid) -> tuple:
    """(ok, message) for the `personal_turn` tool. `busy`: the host's running sessions ({id, mode, turn});
    the running work turn is marked -- the active one when several run."""
    work = [x for x in busy if x.get("mode") != "private"]
    if len(work) > 1:
        work = [x for x in work if x.get("id") == active_sid] or work[:1]
    if not work:
        return False, "no work turn is running"
    sid = str(work[0].get("id") or "")
    if not mark(sessions, sid, work[0].get("turn")):
        return False, "this turn cannot be marked"
    offer = ("Offer the move choice at the end of your reply." if offers_left(sessions, sid)
             else "Do not offer a move now: the user stayed at work the last times.")
    return True, "marked personal: this turn stays out of work memory, observations and tickets. " + offer


_ROUTE = re.compile(r"^/api/sessions/([A-Za-z0-9._-]{1,80})/personal-turns$")


def api(method: str, path: str, body, sessions=None):
    """The page's read of one session's marks: (200, {"turns": [keys]}), or None for another route."""
    m = _ROUTE.match(path or "")
    if method != "GET" or not m:
        return None
    if sessions is None:
        from host_config import SESSIONS as sessions
    return 200, {"turns": sorted(marked(sessions, m.group(1)))}
