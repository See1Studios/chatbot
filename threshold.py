"""THRESHOLD_v1 (docs/plans/private-mode.md §8.4, W2): entering the private room from the work room hands one short,
character-voiced note across, used once on the private room's first turn.

Direction is one way, work -> private; nothing goes back. What crosses is never the work transcript:
- "brink": the work turn that led here was marked personal (PERSONAL_TURN_v1) -- the note says so, no content, and
  the private tension starts one stage higher.
- "gist": otherwise, 1-3 sentences from the character's point of view about how the user seemed and what just
  happened (a one-shot model call in the background), stripped of paths, links and code.
- "mood": one short phrase instead of the gist. "off": nothing.
The strength is the character's `threshold` in characters/<id>/state.json (default "gist").
A place hint (`/private on <place>`, the move choice of W2b) rides along as the first scene's place.

The note waits in <data>/sessions/<private sid>/threshold.json; private_engine.turn_context takes it once.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

FILE = "threshold.json"
STRENGTHS = ("off", "mood", "gist")
DEFAULT = "gist"
MAX_NOTE = 300
MAX_PLACE = 30
BRINK_SEC = 1800   # a personal moment older than this is not "just now"
GIST_SEC = 7200    # nor is work older than this
_UNSAFE = re.compile(r"[/\\`<>{}]|https?:|www\.|\.(?:py|js|md|json|sh)\b", re.I)


def place_hint(text: str) -> str:
    """The place after `/private on`, if any ("" otherwise)."""
    m = re.match(r"^\s*/private\s+on\s+(.+)$", text or "", re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:MAX_PLACE] if m else ""


def strength(state_path: Path) -> str:
    try:
        v = str(json.loads(Path(state_path).read_text(encoding="utf-8")).get("threshold") or DEFAULT)
    except (OSError, ValueError, AttributeError):
        return DEFAULT
    return v if v in STRENGTHS else DEFAULT


def clean(text: str) -> str:
    """At most three sentences of plain words: any sentence carrying a path, link or code is dropped."""
    parts = re.split(r"(?<=[.!?。…])\s+|\n+", (text or "").strip())
    kept = [p.strip(" -*\"'") for p in parts if p.strip() and not _UNSAFE.search(p)]
    return " ".join(kept[:3])[:MAX_NOTE].strip()


def _write(sessions: Path, sid: str, note: dict) -> None:
    d = Path(sessions) / sid
    if d.is_dir():
        import platform_compat
        platform_compat.write_text(d / FILE, json.dumps(note, ensure_ascii=False), encoding="utf-8")


def gist_prompt(rows, user_word: str, name: str, kind: str) -> str:
    talk = "\n".join("%s: %s" % (user_word if h.get("role") == "user" else name, str(h.get("text") or "").strip()[:300])
                     for h in rows)
    want = ("one short phrase naming how %s seemed (for example: tired, excited, stuck)" % user_word if kind == "mood"
            else "one to three short sentences, from %s's point of view, about how %s seemed and what just happened, "
                 "as a feeling %s carries into a private moment" % (name, user_word, name))
    return ("Below is the end of a work conversation between %s and %s. Write %s. Plain words in Korean only: no file "
            "names, paths, links, code, numbers or secrets, and no quotes from the conversation.\n\n%s"
            % (user_word, name, want, talk))


def _names(cid: str) -> tuple:
    """(the persona's word for the user, the character's name) -- display values, only for the prompt."""
    try:
        import characters
        import identity
        card = characters.load(cid) if cid else {}
        return identity.user_title(), (card.get("data") or {}).get("name") or identity.self_label()
    except Exception:  # noqa: BLE001
        return "user", "character"


def enter(work, priv, text: str = "", sessions: Optional[Path] = None, oneshot=None, names=None):
    """Called when `work` switches to its private session `priv`; returns `priv`. Never raises."""
    try:
        import personal_turn
        sessions = Path(sessions or work.meta_path.parent.parent)
        personal_turn.moved(sessions, work.sid)   # W2b: the move offers start over
        state = sessions.parent / "workspace" / "characters" / (priv.character or work.character or "_") / "state.json"
        how = strength(state)
        place = place_hint(text)
        if how == "off":
            if place:
                _write(sessions, priv.sid, {"kind": "place", "text": "", "place": place, "ts": time.time()})
            return priv
        with work.lock:
            history = list(work.history)
        last = personal_turn.running_turn(history)
        age = time.time() - float(last or 0)
        if age < BRINK_SEC and personal_turn.is_marked(sessions, work.sid, last):
            _write(sessions, priv.sid, {"kind": "brink", "text": "", "place": place, "ts": time.time()})
            return priv
        marked = personal_turn.marked(sessions, work.sid)
        rows, skip = [], False
        for h in history:
            if h.get("role") == "user":
                skip = personal_turn.key(h.get("ts")) in marked
            if h.get("role") in ("user", "assistant") and not skip and str(h.get("text") or "").strip():
                rows.append(h)
        rows = rows[-6:]
        if not rows or age >= GIST_SEC:
            if place:
                _write(sessions, priv.sid, {"kind": "place", "text": "", "place": place, "ts": time.time()})
            return priv
        user_word, name = names() if names else _names(priv.character or work.character)

        def run():
            import obslog
            try:
                ask = oneshot
                if ask is None:
                    from session import _oneshot as ask
                res = ask(gist_prompt(rows, user_word, name, how), 45) or {}
                note = clean(res.get("text") or "")
                if note or place:
                    _write(sessions, priv.sid, {"kind": how, "text": note, "place": place, "ts": time.time()})
                obslog.event("private.threshold", session=priv.sid, kind=how, chars=len(note), place=bool(place))
            except Exception as e:  # noqa: BLE001
                obslog.exception("private.threshold_exception", e, session=priv.sid)
        threading.Thread(target=run, name="private-threshold", daemon=True).start()
    except Exception as e:  # noqa: BLE001 -- a missing note never blocks the switch, but it is logged
        import obslog
        obslog.exception("private.threshold_exception", e, session=getattr(priv, "sid", ""))
    return priv


def take(session: Any, user_word: str = "the user") -> str:
    """The note for a private session's turn, once (the file is removed), as context; "" when none waits.
    A "brink" note raises the session's tension stage by one."""
    try:
        path = Path(session.meta_path).parent / FILE
        note = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
    except (OSError, ValueError, AttributeError):
        return ""
    kind, text, place = note.get("kind"), str(note.get("text") or ""), str(note.get("place") or "")
    lines = ["[Threshold -- use once, in character; never quote or mention this note]"]
    if kind == "brink":
        import private_engine
        session.tension_stage = min(private_engine.TENSION_MAX, int(getattr(session, "tension_stage", 1) or 1) + 1)
        lines.append("Just now in the office, where the others could see, %s got personal with you and you could not "
                     "quite answer there. You slipped away together; you are both still a little flustered. Open the "
                     "scene reacting to that." % user_word)
    elif kind == "gist" and text:
        lines.append("You both just came from the office. What you felt there: %s Let it colour how you open the "
                     "scene, lightly." % text)
    elif kind == "mood" and text:
        lines.append("You both just came from the office; %s seemed: %s. Let it colour your first words." % (user_word, text))
    if place:
        lines.append("Where you are now: %s." % place)
    return "\n".join(lines) if len(lines) > 1 else ""
