"""A director hands work outside its role to the director that owns it (HANDOFF_v1, docs/plans/director-handoff.md
dir/E-G, D-3, D-4, D-11).

Every character is a director of its roles. In conversation, work that is not its own goes to the owner with the
`dialog` tool's `handoff` action (a role or a character, the task, when it is done). The receiver works it in its own
work session -- the operator keeps talking to whoever they are with -- and uses its provider's subagents for reading
and checking (adapter `subagents`); a code change still goes into a `delegate` plan that waits for the operator's
go (D-2, D-3). When the receiver's turn ends, its answer goes back to the sender as a dm and the sender tells the
operator in a line or two.

Store: `<data>/handoffs.jsonl`, append-only rows; a handoff's state is its rows folded in order (the tool server
writes `sent`, the chat host `running`, `done`, `failed`; appending keeps the two processes from overwriting each
other). Limits (D-4): a chain started by one request hands off at most MAX_HOPS times; a director has at most one open
handoff. The receiving turn is a host turn (notice), so it runs on the notice budget (loop_guard.tighten).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

MAX_HOPS = 2
OPEN = ("sent", "running")
RESULT_MAX = 1500
_LOCK = threading.Lock()
_UNANSWERED: Dict[int, float] = {}   # handoff id -> when its ended turn first showed no answer (looked at again once)

PROMPT = ("[Handoff #{id} from {sender} -- the user did not write this] {task}\n"
          "Done when: {done_when}\n"
          "This is your role's work: direct it now. Your subagents{hint} do the reading, searching and checking, "
          "and they must not change files; use your role's skills. Read narrowly: search first, then only the lines you need -- the "
          "turn stops past its budget. A code change goes into a `delegate` plan, which waits for the "
          "operator's go; do not edit repo files yourself. If this is not your role's work, say so in one line and "
          "stop. End with a short result for {sender}: what you did, what is left, what the operator must decide.")
REPORT = ("{receiver} finished handoff #{id} ({outcome}). Their result is in your dm with them: {result}\n"
          "Tell the user in one or two short lines, in character. Do not use tools and do not start any work.")


class HandoffError(ValueError):
    pass


def _path() -> Path:
    from host_config import DATA
    return Path(os.environ.get("CHATBOT_HANDOFFS_FILE") or (Path(DATA) / "handoffs.jsonl"))


def _append(row: Dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def all_handoffs() -> Dict[int, Dict]:
    """{id: the handoff, its rows folded in order}."""
    out: Dict[int, Dict] = {}
    try:
        lines = _path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
            out.setdefault(int(row["id"]), {}).update(row)
        except (ValueError, KeyError, TypeError):
            continue
    return out


def open_to(cid: str) -> List[Dict]:
    return [h for h in all_handoffs().values() if h.get("to") == cid and h.get("state") in OPEN]


def running_in(sid: str) -> Optional[Dict]:
    return next((h for h in all_handoffs().values() if h.get("state") == "running" and h.get("sid") == sid), None)


def create(sender: str, sender_sid: str, to: str, role: str, task: str, done_when: str = "") -> Dict:
    """Record a handoff from the calling session's character to `to`; refuses past the limits."""
    task, done_when = str(task or "").strip(), str(done_when or "").strip()
    if not task:
        raise HandoffError("handoff: say what to do (text)")
    if not to or to == sender:
        raise HandoffError("handoff: hand it to another director (a role or a character), not yourself")
    parent = running_in(sender_sid)
    hops = int(parent.get("hops", 1)) + 1 if parent else 1
    if hops > MAX_HOPS:
        raise HandoffError("handoff: this work was already handed on %d times; do it yourself or tell the user what is "
                           "stuck" % MAX_HOPS)
    busy = open_to(to)
    if busy:
        raise HandoffError("handoff: that director is still on handoff #%d; tell the user, or wait for its result"
                           % busy[0]["id"])
    with _LOCK:
        hid = max(all_handoffs() or [0]) + 1
    row = {"id": hid, "state": "sent", "at": time.time(), "from": sender, "from_sid": sender_sid, "to": to,
           "role": role, "task": task[:4000], "done_when": done_when[:500], "hops": hops,
           "parent": parent["id"] if parent else None}
    _append(row)
    return row


def ledger(cid: str, limit: int = 10) -> List[Dict]:
    """The handoffs `cid` sent or received, newest first: what a director reads instead of remembering (a later state
    replaces an earlier one; live 2026-10-05 the lead kept reporting a cancelled handoff from memory)."""
    rows = [h for h in all_handoffs().values() if cid in (h.get("from"), h.get("to"))]
    out = []
    for h in sorted(rows, key=lambda x: x["id"], reverse=True)[:limit]:
        line = str(h.get("result") or h.get("reason") or "").strip().splitlines()
        out.append({"id": h["id"], "state": h.get("state"), "direction": "sent" if h.get("from") == cid else "received",
                    "role": h.get("role", ""), "task": str(h.get("task", ""))[:160],
                    "outcome": (line[0] if line else "")[:200]})
    return out


def mark(hid: int, state: str, **fields) -> None:
    _append({"id": hid, "state": state, "state_at": time.time(), **fields})


# ---- the chat host's side (event_react.loop) --------------------------------------------------------------------

def _title(cid: str, role: str = "") -> str:
    """How a director is named to another agent: its role title, never a persona name as an id."""
    try:
        import characters
        r = role or next(iter(characters.roles_of(cid)), "")
        return characters.role_pack(r).get("title") or r or "a coworker"
    except Exception:  # noqa: BLE001
        return role or "a coworker"


def _last_answer(sess, since: float) -> str:
    for h in reversed(getattr(sess, "history", []) or []):
        if h.get("role") == "assistant" and float(h.get("ts") or 0) >= since:
            return str(h.get("text") or "").strip()
    return ""


def _speak(sess, text: str) -> None:
    try:
        sess._send_direct(text, notice=True, event_type="handoff")
    except Exception:  # noqa: BLE001 -- a turn that cannot start leaves the handoff to time out as failed
        pass


def run_once(reg, now: Optional[float] = None) -> List[Dict]:
    """One pass: finish handoffs whose turn ended (result back to the sender), then start the waiting ones whose
    receiver is free. Returns what changed ({id, state})."""
    now = now or time.time()
    changed = []
    hs = sorted(all_handoffs().values(), key=lambda h: h["id"])
    for h in [x for x in hs if x.get("state") == "running"]:
        sess = reg.peek(h.get("sid", "")) if hasattr(reg, "peek") else None
        if sess is not None and (getattr(sess, "busy", False) or getattr(sess, "_loop_stopping", False)):
            continue   # still working, or between a notice's stop and its resume
        answer = _last_answer(sess, float(h.get("started", 0))) if sess is not None else ""
        why = str(getattr(sess, "_loop_hint", "") or "")[:300]   # a stopped turn leaves its reason for the next one
        if answer and getattr(sess, "_turn_timed_out", False):   # what it said before the wait, not a result
            answer, why = "", "it ran out of time waiting (for a subagent or a long command); what it said: " + answer[:200]
        elif not answer and not why and h["id"] not in _UNANSWERED:
            _UNANSWERED[h["id"]] = now   # the answer may still be on its way into the record (live #6, 2026-10-05)
            continue
        _UNANSWERED.pop(h["id"], None)
        state = "done" if answer else "failed"
        _report(reg, h, state, answer or "(the turn ended without an answer%s)" % (": " + why if why else ""))
        mark(h["id"], state, result=answer[:RESULT_MAX])
        changed.append({"id": h["id"], "state": state})
    for h in [x for x in hs if x.get("state") == "sent"]:
        sess = reg.get_active(h["to"])
        if sess is None or getattr(sess, "busy", False):
            continue
        hint = getattr(getattr(sess, "adapter", None), "subagent_hint", "") \
            if getattr(getattr(sess, "adapter", None), "subagents", False) else ""
        text = PROMPT.format(id=h["id"], sender=_title(h["from"]), task=h["task"],
                             done_when=h.get("done_when") or "(not given: decide it and say it)", hint=hint)
        mark(h["id"], "running", sid=sess.sid, started=now)
        threading.Thread(target=_speak, args=(sess, text), name="handoff", daemon=True).start()
        changed.append({"id": h["id"], "state": "running"})
    return changed


def _show(reg, did: str, msg: Dict) -> None:
    """Draw a dm in both directors' work windows now, as the office route does for a sent one (inbox/E)."""
    import dialog_log
    import route_sessions
    for cid in dialog_log.members(did):
        sess = reg._newest(mode="work", character=cid) if hasattr(reg, "_newest") else None
        if sess is not None:
            other = next(x for x in dialog_log.members(did) if x != cid)
            sess._emit({"event": "office", "msg": route_sessions._office_view(dict(msg, dialog_id=did, other=other), cid)})


def _report(reg, h: Dict, state: str, answer: str) -> None:
    """The receiver's answer as its dm to the sender; the sender, if free, tells the user."""
    try:
        import dialog_log
        did = dialog_log.dm_id(h["to"], h["from"])
        _show(reg, did, dialog_log.append(did, h["to"], "#%d %s" % (h["id"], answer[:RESULT_MAX]), announce=False))
    except Exception:  # noqa: BLE001
        pass
    try:
        back = reg.get_active(h["from"])
        if back is not None and not getattr(back, "busy", False):
            text = REPORT.format(receiver=_title(h["to"], h.get("role", "")), id=h["id"], outcome=state,
                                 result=answer[:300])
            threading.Thread(target=_speak, args=(back, text), name="handoff-report", daemon=True).start()
    except Exception:  # noqa: BLE001
        pass
