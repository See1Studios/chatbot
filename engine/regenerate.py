"""REGENERATE_v1 (docs/plans/regenerate-swipe.md, R1-R3): another take on the companion's last answer, and a pick among
the takes. The engine settles every part of it:

- Only the last answer (D1), only when its turn did nothing that cannot be undone -- a tool call other than a read
  (D3; `effects`, stamped at the turn's end) -- and at most MAX_ALTS takes (D5, the oldest goes).
- The brain's own way (D2): a brain whose adapter rebuilds the context from the history every call gets the same
  question again with the old answer taken out; a brain that keeps its own conversation (it has seen the answer and
  cannot forget it) gets one host note asking for a different reply. Neither is stored or shown as the user's words.
- The takes live on the answer's own history item (`alts`, `pick`); its `text` is always the picked take, so memory,
  handover and the next context see only that one. Tension and affection are left alone (D4).
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import i18n

MAX_ALTS = 5
READ_ACTIONS = ("show", "search", "list", "get", "recent")   # an engine tool's actions that only read
ANOTHER_TAKE = ("[Host note] The user asked for another take on your last answer. Answer their last message again: "
                "the same character and moment, a different reply in wording and direction. Do not mention this note "
                "or the earlier answer.")


class RegenError(Exception):
    """A short reason the page shows (an i18n key)."""


def _last_answer(history: list) -> Optional[int]:
    """Index of the last item when it is a companion's answer (not a notice), with a user turn before it."""
    if not history:
        return None
    i = len(history) - 1
    h = history[i]
    if h.get("role") != "assistant" or h.get("notice") or h.get("system") or not str(h.get("text") or "").strip():
        return None
    if not any(x.get("role") == "user" for x in history[:i]):
        return None
    return i


def _take(item: dict) -> dict:
    return {k: item[k] for k in ("text", "ts", "choices", "usage", "served_model") if k in item}


def start(sess) -> None:
    """Begin another take of `sess`'s last answer, or raise RegenError."""
    with sess.lock:
        if sess._is_busy():
            raise RegenError("regen.busy")
        i = _last_answer(sess.history)
        if i is None:
            raise RegenError("regen.no_answer")
        item = sess.history[i]
        if item.get("effects"):
            raise RegenError("regen.effects")
        alts = list(item.get("alts") or [_take(item)])[-(MAX_ALTS - 1):]
        rebuild = bool(sess.adapter.rebuilds_context())
        user_text = next(h.get("text") for h in reversed(sess.history[:i]) if h.get("role") == "user")
        if rebuild:
            sess.history.pop(i)   # the next call's context ends at the user's question again
        sess._regen = {"item": item, "alts": alts, "popped": rebuild, "at": time.time()}
        sess._turn_effects = False
    _think_harder(sess)
    sess._emit({"event": "regen_start", "ts": item.get("ts")})
    try:
        sess._send_direct(user_text if rebuild else ANOTHER_TAKE, notice=True, event_type="regen")
    except Exception:
        finish(sess, "error")
        raise


def _think_harder(sess) -> None:
    """D5 (#883): chat runs on a quick brain that now and then misses; asking for another take is the user's own word
    that it did, so this one take runs on the same brain thinking harder (adapter.stronger_model) and the next message
    goes back (session_turn.send). The engine never judges the answer's words."""
    model = getattr(sess, "model", "") or ""
    stronger = getattr(sess.adapter, "stronger_model", lambda m: "")(model)
    swap = getattr(sess, "maybe_swap_model", None)
    if not stronger or stronger == model or swap is None:
        return
    sess._regen_restore = model
    swap(stronger, remember=False)
    sess._emit({"event": "system", **i18n.msg("regen.stronger", model=stronger)})


def finish(sess, outcome: str) -> None:
    """The take's turn ended. With a new answer: it becomes the item's picked take (the item takes its time stamp, so
    the bubble the page streamed is that item). Without one (failed, stopped): the item stays, or goes back where it
    was -- before any notice the failed turn left."""
    r = getattr(sess, "_regen", None)
    if not r:
        return
    sess._regen = None
    old, alts = r["item"], r["alts"]
    with sess.lock:
        j = _last_answer(sess.history) if outcome == "result" else None
        new = sess.history.pop(j) if j is not None and sess.history[j] is not old else None
        if new is not None:
            alts.append(_take(new))
            for k in ("text", "ts", "choices", "usage", "served_model"):
                if k in new:
                    old[k] = new[k]
                else:
                    old.pop(k, None)
            old["effects"] = bool(new.get("effects"))
            old["alts"], old["pick"] = alts, len(alts) - 1
            if old in sess.history:
                sess.history.remove(old)
            sess.history.append(old)
        elif r["popped"] and old not in sess.history:
            at = len(sess.history)
            while at and sess.history[at - 1].get("notice") and float(sess.history[at - 1].get("ts") or 0) >= r["at"]:
                at -= 1
            sess.history.insert(at, old)
        sess.save_meta()
    if new is not None:
        sess._emit({"event": "alts", **view(old)})


def after_turn(sess, outcome: str) -> None:
    """Every turn's end (session._finish_turn): an answer this turn left is marked when the turn did something a read
    does not (D3) -- only an answer from this turn, never an earlier one -- then a pending take is merged. What the
    turn did is counted until it leaves an answer (a loop notice's resumed part adds to it). Never raises."""
    try:
        with sess.lock:
            i = _last_answer(sess.history)
            fresh = i is not None and float(sess.history[i].get("ts") or 0) >= float(getattr(sess, "turn_started_at", 0) or 0)
            if fresh and getattr(sess, "_turn_effects", False):
                sess.history[i]["effects"] = True
            if fresh and outcome == "result":
                sess._turn_effects = False
        finish(sess, outcome)
    except Exception:  # noqa: BLE001 -- the turn's own end must not depend on this
        pass


def view(item: dict) -> Dict:
    """What the page draws under the answer: how many takes, which one, and the shown text."""
    alts = item.get("alts") or []
    return {"ts": item.get("ts"), "count": len(alts), "pick": int(item.get("pick") or 0), "text": item.get("text", ""),
            "choices": item.get("choices") or []}


def pick(sess, n: int) -> Dict:
    """Show take `n` of the last answer: it becomes what the companion said."""
    with sess.lock:
        if sess._is_busy():
            raise RegenError("regen.busy")
        i = _last_answer(sess.history)
        item = sess.history[i] if i is not None else None
        alts = (item or {}).get("alts") or []
        if not item or not (0 <= int(n) < len(alts)):
            raise RegenError("regen.no_answer")
        take = alts[int(n)]
        for k in ("text", "choices", "usage", "served_model"):
            if k in take:
                item[k] = take[k]
            else:
                item.pop(k, None)
        item["pick"] = int(n)
        sess.save_meta()
    out = view(item)
    sess._emit({"event": "alts", **out})
    return out


def refusal(e: RegenError) -> Dict:
    return {"ok": False, **i18n.field("error", str(e))}
