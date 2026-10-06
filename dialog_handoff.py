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
OPEN = ("sent", "running", "waiting", "resume")   # waiting: on work it handed on; resume: that work came back
CLOSED = ("done", "partial", "failed", "cancelled")   # partial: it answered after its turn hit the tool-call budget
RESULT_MAX = 1500
_LOCK = threading.Lock()
_BOOT = time.time()   # this host process's start: a turn started before it was cut by a restart
RESTART_RETRIES = 1
START_GRACE_SEC = 120   # HANDOFF_UNSTARTED_v1: a handoff's turn that has not started by then is stuck before its agent
_UNANSWERED: Dict[int, float] = {}   # handoff id -> when its ended turn first showed no answer (looked at again once)

PROMPT = ("[Handoff #{id} from {sender} -- the user did not write this] {task}\n"
          "Done when: {done_when}\n"
          "This is your role's work: direct it now. Your subagents{hint} do the reading, searching and checking, "
          "and they must not change files; use your role's skills. Brief each subagent narrowly: one question, the "
          "folders to look in (the workspace or the engine repo, never the whole home folder), and a limit of about ten "
          "steps, then return what it has. Once you have your answer, stop any subagent still running: your turn stays "
          "open until they end. If part of it belongs to another role, hand that part "
          "on and end your turn: this handoff waits, and you finish it when that result comes back. Read narrowly: search first, then only the lines you need -- the "
          "turn stops past its budget. A code change goes into a `delegate` plan, which waits for the "
          "operator's go; do not edit repo files yourself. If this is not your role's work, say so in one line and "
          "stop. End with a short result for {sender}: what you did, what is left, what the operator must decide.")
RESUME = ("[Handoff #{id} from {sender}, continued -- the user did not write this] The work you handed on for it came "
          "back:\n{children}\nNow finish #{id}: {task}\nDone when: {done_when}\nEnd with the result for {sender}: what you "
          "did, what is left, what the operator must decide.")
REPORT = ("{receiver} finished handoff #{id} ({outcome}). Their result is in your dm with them: {result}\n"
          "Tell the user in one or two short lines, in character -- if it is partial or failed, say so and what is "
          "left. Do not use tools and do not start any work.")


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


HOST_TURN_GAP = 30   # seconds a session just given a host turn is left alone (a reaction or a handoff, not both)


def claim(sess, now: Optional[float] = None) -> bool:
    """HOST_TURN_ONE_v1: take `sess` for one host turn now, or False when one was started there within HOST_TURN_GAP.
    A reaction and a handoff started in the same pass both reached the lead's new session (live #24, 2026-10-05):
    `busy` is set only once the turn's thread runs, the second message queued, and the handoff took the reaction's
    answer for its own. The claim covers that gap only: the sender clears it once the turn is sent (then `busy`)."""
    now = now or time.time()
    if getattr(sess, "busy", False) or abs(now - float(getattr(sess, "_host_turn_at", 0) or 0)) < HOST_TURN_GAP:
        return False
    sess._host_turn_at = now
    return True


def mark(hid: int, state: str, **fields) -> None:
    _append({"id": hid, "state": state, "state_at": time.time(), **fields})


def cancel(hid: int, by: str, reason: str = "") -> Dict:
    """HANDOFF_CANCEL_v1: ask for an open handoff to be cancelled, by its sender or receiver (a character id) or the
    operator ("operator"). The row carries no state -- the host may be moving it on right now -- and the chat host
    acts on it in its next pass (`run_once`): it stops a running turn, then closes it and its open children."""
    h = all_handoffs().get(int(hid))
    if not h:
        raise HandoffError("handoff: there is no #%s; `handoffs` lists yours" % hid)
    if h.get("state") in CLOSED:
        raise HandoffError("handoff: #%d is already %s" % (h["id"], h["state"]))
    if by != "operator" and by not in (h.get("from"), h.get("to")):
        raise HandoffError("handoff: only the director who sent #%d or the one working it can cancel it" % h["id"])
    why = str(reason or "").strip()[:300] or ("the operator cancelled it" if by == "operator"
                                               else "cancelled by the %s director" % _title(by))
    _append({"id": h["id"], "cancel": by, "cancel_reason": why, "cancel_at": time.time()})
    return dict(h, cancel=by, cancel_reason=why)


# ---- the chat host's side (event_react.loop) --------------------------------------------------------------------

def _title(cid: str, role: str = "") -> str:
    """How a director is named to another agent: its role title, never a persona name as an id."""
    try:
        import characters
        r = role or next(iter(characters.roles_of(cid)), "")
        return characters.role_pack(r).get("title") or r or "a coworker"
    except Exception:  # noqa: BLE001
        return role or "a coworker"


def _unread(sess, cid: str) -> str:
    """The receiver's unread dm lines, after the task -- not the whole before-turn note: the restart line went first
    and live #20's turn answered that instead of the task (2026-10-05)."""
    try:
        import dialog_log
        note = dialog_log.turn_note(cid, sess.sid, sess.__dict__.setdefault("_dialog_noted", {}))
    except Exception:  # noqa: BLE001 -- a note is a courtesy
        return ""
    return "\n\nAlso new in your dialogs since you last looked:\n" + note if note else ""


def _last_answer(sess, since: float) -> str:
    for h in reversed(getattr(sess, "history", []) or []):
        if h.get("role") == "assistant" and float(h.get("ts") or 0) >= since:
            return str(h.get("text") or "").strip()
    return ""


def _speak(sess, text: str, event_type: str = "handoff") -> None:
    try:
        sess._send_direct(text, notice=True, event_type=event_type)
    except Exception:  # noqa: BLE001 -- a turn that cannot start leaves the handoff to time out as failed
        pass
    finally:
        sess._host_turn_at = 0   # sent: from here the session's own busy flag keeps the next host turn out


_PASS = threading.Lock()


def run_once(reg, now: Optional[float] = None) -> List[Dict]:
    """One pass: close the cancelled ones, finish handoffs whose turn ended (result back to the sender), then start the
    waiting ones whose receiver is free. Returns what changed ({id, state}). One pass at a time: the reactor's and an
    operator's cancel (route_sessions.handoff_cancel) never act on one handoff twice."""
    with _PASS:
        return _pass(reg, now)


def _pass(reg, now: Optional[float] = None) -> List[Dict]:
    now = now or time.time()
    changed = []
    for h in sorted(all_handoffs().values(), key=lambda h: h["id"]):
        if h.get("cancel") and h.get("state") in OPEN:
            changed += _close_cancelled(reg, h)
    hs = sorted(all_handoffs().values(), key=lambda h: h["id"])
    for h in [x for x in hs if x.get("state") == "running"]:
        sess = reg.peek(h.get("sid", "")) if hasattr(reg, "peek") else None
        if sess is not None and _unstarted(h, sess, now):
            changed.append(_restart_unstarted(reg, h, sess))
            continue
        if sess is not None and (getattr(sess, "busy", False) or getattr(sess, "_loop_stopping", False)):
            continue   # still working, or between a notice's stop and its resume
        answer = _last_answer(sess, float(h.get("started", 0))) if sess is not None else ""
        why = str(getattr(sess, "_loop_hint", "") or "")[:300]   # a stopped turn leaves its reason for the next one
        if not answer and float(h.get("started", 0) or 0) < _BOOT:   # HANDOFF_RESTART_v1: the host restarted mid-turn
            if int(h.get("retries", 0) or 0) < RESTART_RETRIES:   # its agent was stopped with it: send it again, once
                mark(h["id"], "sent", retries=int(h.get("retries", 0) or 0) + 1,
                     note="the host restarted during its turn; sent again")
                changed.append({"id": h["id"], "state": "sent"})
                continue
            why = why or "the host restarted during its turn, again after it was sent a second time"
        if answer and getattr(sess, "_turn_timed_out", False):   # what it said before the wait, not a result
            answer, why = "", "it ran out of time waiting (for a subagent or a long command); what it said: " + answer[:200]
        elif not answer and not why and h["id"] not in _UNANSWERED:
            _UNANSWERED[h["id"]] = now   # the answer may still be on its way into the record (live #6, 2026-10-05)
            continue
        _UNANSWERED.pop(h["id"], None)
        state = "done" if answer else "failed"
        why = why or ("" if answer else "the turn ended without an answer")
        if answer and float(getattr(sess, "_budget_hit_at", 0) or 0) >= float(h.get("started", 0) or 0):
            state, why = "partial", "its turn hit the tool-call budget and wrapped up; what is left is in the result"
        if state in ("done", "partial") and _chained(h, now):   # HANDOFF_CHAIN_v1: it handed work on; it is not done yet
            continue
        parent = all_handoffs().get(h.get("parent")) if h.get("parent") else None
        if parent is not None and parent.get("state") == "waiting":   # the one who asked finishes its own work next
            _report(reg, h, state, answer or "(the turn ended without an answer%s)" % (": " + why if why else ""),
                    tell=False)
            mark(h["id"], state, result=answer[:RESULT_MAX], **({"reason": why} if state in ("failed", "partial") and why else {}))
            if not [c for c in _children(parent["id"]) if c.get("state") in OPEN]:
                mark(parent["id"], "resume")
            changed.append({"id": h["id"], "state": state})
            continue
        _report(reg, h, state, answer or "(the turn ended without an answer%s)" % (": " + why if why else ""))
        mark(h["id"], state, result=answer[:RESULT_MAX], **({"reason": why} if state in ("failed", "partial") and why else {}))
        changed.append({"id": h["id"], "state": state})
    hs = sorted(all_handoffs().values(), key=lambda h: h["id"])
    for h in [x for x in hs if x.get("state") in ("sent", "resume")]:
        sess = reg.get_active(h["to"])
        if sess is None or not claim(sess, now):   # HOST_TURN_ONE_v1: one host turn at a time
            continue
        hint = getattr(getattr(sess, "adapter", None), "subagent_hint", "") \
            if getattr(getattr(sess, "adapter", None), "subagents", False) else ""
        done_when = h.get("done_when") or "(not given: decide it and say it)"
        if h.get("state") == "resume":
            kids = "\n".join("#%d (%s): %s" % (c["id"], c.get("state"), str(c.get("result") or c.get("reason") or "")[:600])
                             for c in _children(h["id"]))
            text = RESUME.format(id=h["id"], sender=_title(h["from"]), children=kids, task=h["task"], done_when=done_when)
        else:
            text = PROMPT.format(id=h["id"], sender=_title(h["from"]), task=h["task"], done_when=done_when, hint=hint)
        text += _unread(sess, h["to"])
        mark(h["id"], "running", sid=sess.sid, started=now,
             **({"delivered": [c["id"] for c in _children(h["id"])]} if h.get("state") == "resume" else {}))
        threading.Thread(target=_speak, args=(sess, text), name="handoff", daemon=True).start()
        changed.append({"id": h["id"], "state": "running"})
    return changed


def _show(reg, did: str, msg: Dict, only: str = "") -> None:
    """Draw a dm in the directors' work windows now, as the office route does for a sent one (inbox/E); `only` limits
    it to one of them (a result: the receiver's window already shows it as its own turn -- drawn there again it came
    out a second time as a "-> sender: ..." stage line, live 2026-10-05)."""
    import dialog_log
    import route_sessions
    for cid in dialog_log.members(did):
        if only and cid != only:
            continue
        sess = reg._newest(mode="work", character=cid) if hasattr(reg, "_newest") else None
        if sess is not None:
            other = next(x for x in dialog_log.members(did) if x != cid)
            sess._emit({"event": "office", "msg": route_sessions._office_view(dict(msg, dialog_id=did, other=other), cid)})


def _close_cancelled(reg, h: Dict, why: str = "") -> List[Dict]:
    """HANDOFF_CANCEL_v1: stop the turn working `h`, close it as cancelled, then its open children (their work was for
    it); the one who asked for it reads why in the dm. A parent left waiting on it goes on with what came back."""
    if h.get("state") not in OPEN:
        return []
    why = why or str(h.get("cancel_reason") or "cancelled")
    if h.get("state") == "running":
        sess = reg.peek(h.get("sid", "")) if hasattr(reg, "peek") else None
        if sess is not None and getattr(sess, "busy", False):
            try:
                sess.stop()
            except Exception:  # noqa: BLE001 -- closed in the ledger all the same
                pass
    mark(h["id"], "cancelled", reason=why)
    _report(reg, h, "cancelled", "(cancelled: %s)" % why, tell=False)
    out = [{"id": h["id"], "state": "cancelled"}]
    for c in _children(h["id"]):
        out += _close_cancelled(reg, all_handoffs().get(c["id"], c), "its parent #%d was cancelled" % h["id"])
    parent = all_handoffs().get(h.get("parent")) if h.get("parent") else None
    if parent is not None and parent.get("state") == "waiting" and not [
            c for c in _children(parent["id"]) if c.get("state") in OPEN]:
        mark(parent["id"], "resume")
    return out


def _unstarted(h: Dict, sess, now: float) -> bool:
    """HANDOFF_UNSTARTED_v1: its turn has not started (the session's last turn began before the handoff did) and the
    grace is over -- stuck before its agent ran (a drill rerun under load, 2026-10-06: running for 10 minutes)."""
    started = float(h.get("started", 0) or 0)
    return now - started > START_GRACE_SEC and float(getattr(sess, "turn_started_at", 0) or 0) < started


def _restart_unstarted(reg, h: Dict, sess) -> Dict:
    """Stop whatever holds the session and send the handoff again, once; then fail it saying why."""
    try:
        sess.stop()
    except Exception:  # noqa: BLE001 -- closed or resent in the ledger all the same
        pass
    tries = int(h.get("start_retries", 0) or 0)
    if tries < RESTART_RETRIES:
        mark(h["id"], "sent", start_retries=tries + 1, note="its turn had not started after %ds; sent again" % START_GRACE_SEC)
        return {"id": h["id"], "state": "sent"}
    why = "its turn never started (twice, %ds each)" % START_GRACE_SEC
    _report(reg, h, "failed", "(the turn ended without an answer: %s)" % why)
    mark(h["id"], "failed", reason=why)
    return {"id": h["id"], "state": "failed"}


def _children(hid: int) -> List[Dict]:
    return [c for c in sorted(all_handoffs().values(), key=lambda x: x["id"]) if c.get("parent") == hid]


def _chained(h: Dict, now: float) -> bool:
    """HANDOFF_CHAIN_v1: a turn that handed work on (a child handoff) leaves its own handoff open -- waiting while a
    child is open, back for its director to finish when they all came back meanwhile (live #27/#28, 2026-10-05: #27
    closed as done on "I handed it to art", and art's result then only reached a tell-the-user turn)."""
    kids = [c for c in _children(h["id"]) if c["id"] not in (h.get("delivered") or [])]   # not yet brought back to it
    if not kids:
        return False
    mark(h["id"], "waiting" if [c for c in kids if c.get("state") in OPEN] else "resume")
    return True


def _report(reg, h: Dict, state: str, answer: str, tell: bool = True) -> None:
    """The receiver's answer as its dm to the sender; the sender, if free, tells the user (unless `tell` is off: a
    director waiting on this result finishes its own work with it instead)."""
    try:
        import dialog_log
        did = dialog_log.dm_id(h["to"], h["from"])
        _show(reg, did, dialog_log.append(did, h["to"], "#%d %s" % (h["id"], answer[:RESULT_MAX]), announce=False),
              only=h["from"])
    except Exception:  # noqa: BLE001
        pass
    try:
        back = reg.get_active(h["from"]) if tell else None
        if back is not None and claim(back):
            text = REPORT.format(receiver=_title(h["to"], h.get("role", "")), id=h["id"], outcome=state,
                                 result=answer[:300])
            threading.Thread(target=_speak, args=(back, text, ""), name="handoff-report", daemon=True).start()
    except Exception:  # noqa: BLE001
        pass
