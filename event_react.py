"""Characters speak first about events (docs/plans/character-events-and-rooms.md evt/D, decision E2).

An event addressed to a character (events.py) is normally told before the user's next turn. When the operator turns
auto reactions on for its type, the character instead says it first, in its own work session, as a host notice the
user never typed (session._send_direct(notice=True): not a user bubble, not kept as the user's words).

Off by default. Limits: at most `per_hour` reactions per character, none in quiet hours (they wait and go together
in the morning), none while any conversation is running, and an event a character spoke about is not told again.
Settings live in the workspace (`events.json`, user data); the team tab edits them.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import events

CONFIG_NAME = "events.json"
CHOICES = ("work.phase", "host.restart")        # the event types a reaction can be turned on for (E2)
ENDING = ("done", "failed", "gate_failed", "unavailable", "base_broken", "awaiting_merge")   # work phases worth it
DEFAULTS = {"auto": [], "per_hour": 3, "quiet": [0, 8]}
POLL_SEC = 20
TTL_SEC = 3600                                  # an event older than this is stale news: dropped, not spoken
HEAVY = ("soft", "hard")                        # session weight levels a reaction must not push into
PROMPT = ("[Event -- the user did not write this] {note}\nTell the user about it yourself now, in one or two short "
          "lines, in character, as a message you start. Do not use tools and do not start any work.")


def _ws() -> Path:
    from host_config import WORKSPACE
    return Path(WORKSPACE)


def load_config(ws=None) -> Dict:
    try:
        raw = json.loads((Path(ws or _ws()) / CONFIG_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    return clean(raw)


def clean(raw) -> Dict:
    raw = raw if isinstance(raw, dict) else {}
    auto = [t for t in (raw.get("auto") or []) if t in CHOICES]
    try:
        per_hour = max(0, min(20, int(raw.get("per_hour", DEFAULTS["per_hour"]))))
    except (TypeError, ValueError):
        per_hour = DEFAULTS["per_hour"]
    quiet = raw.get("quiet", DEFAULTS["quiet"])
    if not (isinstance(quiet, list) and len(quiet) == 2 and all(isinstance(h, int) and 0 <= h <= 24 for h in quiet)):
        quiet = list(DEFAULTS["quiet"])
    return {"auto": sorted(set(auto)), "per_hour": per_hour, "quiet": quiet}


def save_config(raw, ws=None) -> Dict:
    import platform_compat
    cfg = clean(raw)
    path = Path(ws or _ws()) / CONFIG_NAME
    tmp = path.with_name(".%s.tmp" % CONFIG_NAME)
    platform_compat.write_text(tmp, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return cfg


def _quiet(cfg: Dict, now: float) -> bool:
    start, end = cfg["quiet"]
    h = time.localtime(now).tm_hour
    return start != end and ((start <= h < end) if start < end else (h >= start or h < end))


def _wanted(e: Dict, cfg: Dict, character: str = "", default: str = "") -> bool:
    if e["type"] not in cfg["auto"]:
        return False
    if events.ALL in e.get("to", []) and character != default:
        return False                            # an event for everyone (a restart): one voice, the default's
    return e["type"] != "work.phase" or e["payload"].get("phase") in ENDING


def _speak(sess, text: str) -> None:
    """The reaction turn; a failure is logged, never silent."""
    try:
        import obslog
        obslog.event("react.turn", sid=sess.sid)
    except Exception:  # noqa: BLE001
        obslog = None
    try:
        sess._send_direct(text, notice=True)
    except Exception as e:  # noqa: BLE001
        if obslog:
            obslog.exception("react.failed", e, sid=sess.sid)


def _note(evts: List[Dict], character: str) -> str:
    notes = []
    work = [e for e in evts if e["type"] == "work.phase"]
    if work:
        try:
            import delegation
            notes.append(delegation.work_event_note(work, character))
        except Exception:  # noqa: BLE001 -- no delegation in this build
            pass
    if any(e["type"] == "host.restart" for e in evts):
        p = [e for e in evts if e["type"] == "host.restart"][-1]["payload"]
        notes.append("The host restarted at %s; landed: %s." % (
            time.strftime("%H:%M", time.localtime(p.get("ts") or 0)), " · ".join(p.get("landed") or []) or "nothing new"))
    return " ".join(n for n in notes if n)


def _heavy(sess) -> bool:
    try:
        return (sess.weight() or {}).get("level") in HEAVY
    except Exception:  # noqa: BLE001 -- an unknown weight does not block a reaction
        return False


def _recent_reactions(character: str, now: float) -> int:
    return sum(1 for e in events.recent("react.sent")
               if e["subject"] == character and 0 <= now - e["payload"].get("at", e["ts"]) < 3600)


def react_once(reg, now: Optional[float] = None, cfg: Optional[Dict] = None, characters_list=None) -> List[Dict]:
    """One pass: for each character with wanted events and room to react, its work session speaks first.
    Returns what was sent ({character, sid, events}). Events it may not react to yet stay pending."""
    now = now or time.time()
    cfg = cfg or load_config()
    if not cfg["auto"]:
        return []
    with reg.lock:
        sessions = list(reg.sessions.values())
    if any(getattr(s, "busy", False) for s in sessions) or _quiet(cfg, now):
        why = "quiet_hours" if _quiet(cfg, now) else "conversation_running"
        events._log("react.defer", reason=why, dedup="react.defer:" + why)
        return []
    import characters
    if characters_list is None:
        characters_list = [c["id"] for c in characters.listing(_ws())]
    default = characters.default_character(_ws())
    sent = []
    for cid in characters_list:
        key = "react:" + cid
        if events.cursor(key) is None:              # first sight: react to what comes next, not to history
            events.mark(key, events.last_id())
            continue
        got = events.pending(key, cid, "work")
        if not got:
            continue
        wanted = [e for e in got if _wanted(e, cfg, cid, default)]
        fresh = [e for e in wanted if now - e.get("ts", now) <= TTL_SEC]
        if len(fresh) < len(wanted):
            events._log("react.skip", reason="expired", character=cid, n=len(wanted) - len(fresh))
        wanted = fresh
        if not wanted or _recent_reactions(cid, now) >= cfg["per_hour"]:
            if not wanted:
                events.mark(key, got[-1]["id"])
            else:
                events._log("react.defer", reason="per_hour", character=cid, dedup="react.defer:rate:" + cid)
            continue
        sess = reg._newest(mode="work", character=cid)
        if sess is not None and _heavy(sess):
            events._log("react.skip", reason="session_heavy", character=cid, sid=sess.sid)
            events.mark(key, got[-1]["id"])
            continue
        note = _note(wanted, cid)
        if sess is None or not note:
            events._log("react.skip", reason="no_work_session" if sess is None else "nothing_to_say", character=cid)
            events.mark(key, got[-1]["id"])
            continue
        events.mark(key, got[-1]["id"])
        events.mark(sess.sid, max(e["id"] for e in wanted))   # told now: not again before the next turn
        events.publish("react.sent", [cid], subject=cid, at=now, events=[e["id"] for e in wanted])
        threading.Thread(target=_speak, args=(sess, PROMPT.format(note=note)), name="event-react", daemon=True).start()
        sent.append({"character": cid, "sid": sess.sid, "events": [e["id"] for e in wanted]})
    return sent


def loop(reg, stop: Optional[threading.Event] = None) -> None:
    """The chat server's reactor thread."""
    stop = stop or threading.Event()
    while not stop.wait(POLL_SEC):
        try:
            react_once(reg)
        except Exception:  # noqa: BLE001 -- a bad event must not end the reactor
            pass
