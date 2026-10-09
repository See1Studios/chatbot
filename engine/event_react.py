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

import dialog_handoff
import events

CONFIG_NAME = "events.json"
CHOICES = ("work.phase", "host.restart", "msg.new")   # the event types a reaction can be turned on for (E2, inbox D11)
ENDING = ("done", "failed", "gate_failed", "unavailable", "base_broken", "awaiting_merge")   # work phases worth it
DEFAULTS = {"auto": [], "per_hour": 3, "quiet": [0, 8]}
ALWAYS = ("host.incident",)   # the engine's own word to the operator (improvement-layers il/E): no switch turns it off
POLL_SEC = 20
TTL_SEC = 3600                                  # an event older than this is stale news: dropped, not spoken
HEAVY = ("soft", "hard")                        # session weight levels a reaction must not push into
PROMPT = ("[Event -- the user did not write this] {note}\nTell the user about it yourself now, in one or two short "
          "lines, in character, as a message you start. Do not use tools and do not start any work.")
# improvement-layers il/E (D4: the engine catches, the LLM judges, the operator approves): the engine caught it; the
# character judges it from the evidence and the user decides with the buttons the engine adds (engine_choices).
INCIDENT_PROMPT = ("[Incident -- the engine caught this; the user did not write it] {note}\nLook at the evidence yourself, "
                   "read only (`chatbot-ctl.sh logs --fp <fp>` / `--rid <rid>` / `--evt <prefix>`, the code it names). "
                   "Then tell the user in a few short lines: the likely cause, with what you saw; whether it is worth "
                   "fixing; what would change. Change nothing and start no work: the user decides with the buttons.")
# A coworker's dm, shown in this character's window as the coworker's own turn (unified-message-inbox D8, D11)
OFFICE_PROMPT = ("[Office -- the user did not write this] {note}\nThis just happened at your desk, in front of the "
                 "user, who saw it. React now in one or two short lines, in character. Do not use tools and do not "
                 "start any work.")
# The user has just come to the desk and sees what a coworker did there earlier (D11; like the scene line on entering
# or leaving a private talk, private-mode 8.5: the character answers the scene first)
OFFICE_OPEN_PROMPT = ("[Office -- the user did not write this] {note}\nThis happened at your desk while the user was "
                      "away; the user has just come over and can see it. React now in one or two short lines, in "
                      "character. Do not use tools and do not start any work.")


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
    if e["type"] in ALWAYS:
        return True
    if e["type"] not in cfg["auto"]:
        return False
    if events.ALL in e.get("to", []) and character != default:
        return False                            # an event for everyone (a restart): one voice, the default's
    if e["type"] == "msg.new":
        return str(e.get("subject") or "").startswith("dm:")   # a coworker's dm; a meeting room is not reacted to
    return e["type"] != "work.phase" or e["payload"].get("phase") in ENDING


def _speak(sess, text: str) -> None:
    """The reaction turn; a failure is logged, never silent."""
    try:
        from telemetry import obslog
        obslog.event("react.turn", sid=sess.sid)
    except Exception:  # noqa: BLE001
        obslog = None
    try:
        sess._send_direct(text, notice=True)
    except Exception as e:  # noqa: BLE001
        if obslog:
            obslog.exception("react.failed", e, sid=sess.sid)
    finally:
        sess._host_turn_at = 0   # HOST_TURN_ONE_v1: sent; the session's busy flag takes over

    try:
        import push_manager
        cid = getattr(sess, "character", "") or "Companion"
        push_manager.notify(title=cid, body=text[:120], url=f"/?s={sess.sid}", tag=f"react-{sess.sid}")
    except Exception:  # noqa: BLE001
        pass


def _note(evts: List[Dict], character: str) -> str:
    notes = []
    work = [e for e in evts if e["type"] == "work.phase"]
    if work:
        try:
            import delegation
            notes.append(delegation.work_event_note(work, character))
        except Exception:  # noqa: BLE001 -- no delegation in this build
            pass
    incs = [int(e["subject"]) for e in evts if e["type"] == "host.incident" and str(e.get("subject") or "").isdigit()]
    if incs:
        try:
            from health import incidents
            notes.append(incidents.note(incs))
        except Exception:  # noqa: BLE001 -- no health package in this build
            pass
    if any(e["type"] == "host.restart" for e in evts):
        p = [e for e in evts if e["type"] == "host.restart"][-1]["payload"]
        notes.append("The host restarted at %s; landed: %s." % (
            time.strftime("%H:%M", time.localtime(p.get("ts") or 0)), " · ".join(p.get("landed") or []) or "nothing new"))
    return " ".join(n for n in notes if n)


def _office_note(evts: List[Dict], character: str, sid: str):
    """What a coworker just said or did, from the dm records past what this session has seen: (note, {dialog: n})."""
    import dialog_log
    lines, upto = [], {}
    for did in sorted({e["subject"] for e in evts}):
        new = [m for m in dialog_log.history(did, dialog_log.seen(sid, character, did)) if m.get("who") != character]
        if new:
            lines.extend(dialog_log.line(m, did) for m in new[-5:])
            upto[did] = new[-1]["n"]
    return "; ".join(lines), upto


def _heavy(sess, visit: bool = False) -> bool:
    """Whether a reaction would push the session too far. A coworker's visit the user is watching (D11) is one or two
    lines, so it waits only at "hard"; every other reaction already waits at "soft" (live 2026-10-02: soft is reached
    after a while of talk and kept every visit unanswered)."""
    try:
        level = (sess.weight() or {}).get("level")
    except Exception:  # noqa: BLE001 -- an unknown weight does not block a reaction
        return False
    return level == "hard" if visit else level in HEAVY


def _recent_reactions(character: str, now: float) -> int:
    return sum(1 for e in events.recent("react.sent")
               if e["subject"] == character and 0 <= now - e["payload"].get("at", e["ts"]) < 3600)


def react_once(reg, now: Optional[float] = None, cfg: Optional[Dict] = None, characters_list=None) -> List[Dict]:
    """One pass: for each character with wanted events and room to react, its work session speaks first.
    Returns what was sent ({character, sid, events}). Events it may not react to yet stay pending."""
    now = now or time.time()
    cfg = cfg or load_config()
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
        if sess is not None and _heavy(sess) and not _heavy(sess, visit=True) \
                and any(e["type"] == "msg.new" for e in wanted):
            wanted = [e for e in wanted if e["type"] == "msg.new"]   # soft: only a coworker's visit (D11)
        elif sess is not None and _heavy(sess):
            events._log("react.skip", reason="session_heavy", character=cid, sid=sess.sid)
            events.mark(key, got[-1]["id"])
            continue
        talk = [e for e in wanted if e["type"] == "msg.new"]
        if talk and not getattr(sess, "subscribers", None):     # D11: only in front of the user; else the turn line
            events._log("react.skip", reason="not_watching", character=cid, n=len(talk))
            wanted, talk = [e for e in wanted if e["type"] != "msg.new"], []
        office, upto = _office_note(talk, cid, sess.sid) if talk else ("", {})
        rest = [e for e in wanted if e["type"] != "msg.new"]
        note = " ".join(x for x in (office, _note(rest, cid) if rest else "") if x)
        if sess is None or not note:
            events._log("react.skip", reason="no_work_session" if sess is None else "nothing_to_say", character=cid)
            events.mark(key, got[-1]["id"])
            continue
        if not dialog_handoff.claim(sess, now):   # a host turn just started there: these events wait for the next pass
            events._log("react.defer", reason="host_turn", character=cid, dedup="react.defer:host:" + cid)
            continue
        events.mark(key, got[-1]["id"])
        events.mark(sess.sid, max(e["id"] for e in wanted))   # told now: not again before the next turn
        events.publish("react.sent", [cid], subject=cid, at=now, events=[e["id"] for e in wanted])
        if upto:
            import dialog_log
            for did, n in upto.items():
                dialog_log.saw(cid, sess.sid, did, n)            # heard in front of the user: read
        incs = [int(e["subject"]) for e in rest if e["type"] == "host.incident" and str(e["subject"]).isdigit()]
        sess._incident_offer = incs   # engine_choices adds [ticket] / [ignore] to this answer (il/E)
        text = (OFFICE_PROMPT if office else INCIDENT_PROMPT if incs else PROMPT).format(note=note)
        threading.Thread(target=_speak, args=(sess, text), name="event-react", daemon=True).start()
        sent.append({"character": cid, "sid": sess.sid, "events": [e["id"] for e in wanted]})
    return sent


def react_on_open(reg, character: str, now: Optional[float] = None, cfg: Optional[Dict] = None) -> Optional[Dict]:
    """The user just opened `character`'s work window (D11): if a coworker's dm there is still unheard by that
    session, it reacts once now. Same switch (msg.new) and limits as react_once; nothing when nothing is unheard."""
    now = now or time.time()
    cfg = cfg or load_config()
    if "msg.new" not in cfg["auto"] or _quiet(cfg, now):
        return None
    with reg.lock:
        sessions = list(reg.sessions.values())
    if any(getattr(s, "busy", False) for s in sessions):
        events._log("react.defer", reason="conversation_running", dedup="react.defer:conversation_running")
        return None
    sess = reg._newest(mode="work", character=character)
    if sess is None or _heavy(sess, visit=True) or not dialog_handoff.claim(sess, now):
        return None
    import dialog_log
    dms = [{"subject": d} for d in dialog_log.dialogs_of(character) if dialog_log.is_dm(d)]
    note, upto = _office_note(dms, character, sess.sid)
    if not note:
        return None
    if _recent_reactions(character, now) >= cfg["per_hour"]:
        events._log("react.defer", reason="per_hour", character=character, dedup="react.defer:rate:" + character)
        return None
    events.publish("react.sent", [character], subject=character, at=now, events=[])
    for did, n in upto.items():
        dialog_log.saw(character, sess.sid, did, n)
    threading.Thread(target=_speak, args=(sess, OFFICE_OPEN_PROMPT.format(note=note)), name="office-open",
                     daemon=True).start()
    return {"character": character, "sid": sess.sid}


def loop(reg, stop: Optional[threading.Event] = None) -> None:
    """The chat server's reactor thread."""
    stop = stop or threading.Event()
    while not stop.wait(POLL_SEC):
        try:
            react_once(reg)
        except Exception:  # noqa: BLE001 -- a bad event must not end the reactor
            pass
        try:   # HANDOFF_v1: work handed between directors starts and reports on its own, whatever `auto` says
            dialog_handoff.run_once(reg)
        except Exception:  # noqa: BLE001
            pass
