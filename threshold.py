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
SCENE_FILE = "scene.json"   # where this private visit went, for the way back
WAIT_SEC = 12               # the first private turn waits this long for a gist still being written
REPEAT_SEC = 30             # a second switch request this soon is the same move (a re-tap, another tab): no new scene
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


def _read(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(sessions: Path, sid: str, note: dict, name: str = FILE) -> None:
    d = Path(sessions) / sid
    if d.is_dir():
        import platform_compat
        platform_compat.write_text(d / name, json.dumps(note, ensure_ascii=False), encoding="utf-8")


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


def _scene_in(place: str, during_work: bool) -> str:
    where = ("잠깐 함께 %s에 왔다" % place) if place else "잠깐 둘만 있을 곳으로 함께 자리를 옮겼다"   # l10n-ok
    return "(" + ("업무 도중 " if during_work else "") + where + ")"   # l10n-ok


def _scene_out(place: str) -> str:
    return ("(함께 %s에서 사무실로 돌아왔다)" % place) if place else "(둘만의 시간을 보내고 함께 사무실로 돌아왔다)"   # l10n-ok


def auto_scene(state_path: Path) -> bool:
    """SCENE_v1: does a room switch send a scene line so the character speaks first? (state.json `auto_scene`)"""
    try:
        return json.loads(Path(state_path).read_text(encoding="utf-8")).get("auto_scene", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def _state(sessions: Path, cid: str) -> Path:
    return Path(sessions).parent / "workspace" / "characters" / (cid or "_") / "state.json"


def announce(source, target, client_mid: str = "") -> None:
    """ROOM_SYNC_v1 (2026-09-30): tell every page still on `source` that the room moved to `target`, so a second
    window follows instead of offering the old room's move again. The page that asked knows its own client_mid."""
    if target is not None and target.sid != source.sid:
        source._emit({"event": "room_moved", "to": target.sid, "mode": getattr(target, "mode", "work"),
                      "character": getattr(target, "character", ""), "client_mid": client_mid})


def just_switched(session, stamp: str) -> bool:
    """True when `session` was switched into less than REPEAT_SEC ago (the host keeps sessions in memory)."""
    return time.time() - float(getattr(session, stamp, 0) or 0) < REPEAT_SEC


_DIGESTING = {}   # character id -> Event, set when that character's private digest has finished
_FRESH = {}       # character id -> the memory lines the last digest added, for the next visit's first turn


def digest_later(sess) -> None:
    """Put a private session's new talk into the character's private memory, in the background (SESSION_SPLIT_v1).
    Only the character's private memory is written; the work side never sees it. The next visit's first turn waits
    for a digest still running (take) and hears what it added, so leaving and coming right back loses nothing."""
    import characters
    cid = _cid(sess)
    done = threading.Event()
    _DIGESTING[cid] = done

    def run():
        import identity
        import obslog
        from session import _oneshot
        try:
            with sess.lock:
                history = list(sess.history)
            since = float(getattr(sess, "private_digested_ts", 0) or 0)
            seg = characters.private_segment(history, since)
            if not seg:
                return
            card = characters.load(cid) if cid else {}
            name = (card.get("data") or {}).get("name") or identity.self_label()
            res = _oneshot(characters.private_digest_prompt(seg, identity.user_title(), name), 60) or {}
            if not res.get("text"):
                obslog.event("private.digest_failed", session=sess.sid, error=str(res.get("error") or "no text"))
                return
            lines = characters.parse_memory_lines(res["text"])
            added = characters.remember_private(cid, lines) if cid else 0
            if added:
                _FRESH[cid] = lines
            sess.private_digested_ts = max(float(h.get("ts") or 0) for h in seg)
            sess.save_meta()
            obslog.event("private.digested", session=sess.sid, character=cid, added=added)
        except Exception as e:  # noqa: BLE001
            obslog.exception("private.digest_exception", e, session=sess.sid)
        finally:
            done.set()
            if _DIGESTING.get(cid) is done:
                del _DIGESTING[cid]
    threading.Thread(target=run, name="private-digest", daemon=True).start()


def _cid(session) -> str:
    """The session's character id ("" in a session means the team's default character)."""
    try:
        import characters
        return getattr(session, "character", "") or characters.default_character()
    except Exception:  # noqa: BLE001
        return getattr(session, "character", "") or ""


def left_private(sess) -> None:
    """A private session left some other way than /private off (switching characters in private mode): digest it."""
    if sess is not None and getattr(sess, "is_private", False):
        digest_later(sess)


def _fresh_memory(cid: str, wait: float) -> list:
    """What the last private digest of `cid` added, once; waits up to `wait` seconds for one still running."""
    running = _DIGESTING.get(cid)
    if running is not None:
        running.wait(wait)
    return _FRESH.pop(cid, [])


def pop_scene(session) -> str:
    """The scene line a switch left for the page to send as an action ("" when none)."""
    line = getattr(session, "scene_action", "") or ""
    session.scene_action = ""
    return line


def enter(work, priv, text: str = "", sessions: Optional[Path] = None, oneshot=None, names=None):
    """Called when `work` switches to its private session `priv`; returns `priv`. Never raises."""
    try:
        import obslog
        import personal_turn
        if just_switched(priv, "visit_started"):
            obslog.event("private.switch_repeat", session=priv.sid, way="in")
            return priv
        priv.visit_started = time.time()
        sessions = Path(sessions or work.meta_path.parent.parent)
        personal_turn.moved(sessions, work.sid)   # W2b: the move offers start over
        state = _state(sessions, priv.character or work.character)
        how = strength(state)
        place = place_hint(text)
        with work.lock:
            history = list(work.history)
        last = personal_turn.running_turn(history)
        age = time.time() - float(last or 0)
        if auto_scene(state):
            priv.scene_action = _scene_in(place, age < GIST_SEC)
        _write(sessions, priv.sid, {"kind": "visit", "place": place, "ts": time.time()}, SCENE_FILE)
        if how == "off":
            if place:
                _write(sessions, priv.sid, {"kind": "place", "text": "", "place": place, "ts": time.time()})
            return priv
        if age < BRINK_SEC and personal_turn.is_marked(sessions, work.sid, last):
            _write(sessions, priv.sid, {"kind": "brink", "text": "", "place": place, "ts": time.time()})
            obslog.event("private.threshold", session=priv.sid, kind="brink", chars=0, place=bool(place))
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
        _write(sessions, priv.sid, {"kind": "pending", "place": place, "ts": time.time()})

        def run():
            try:
                ask = oneshot
                if ask is None:
                    from session import _oneshot as ask
                res = ask(gist_prompt(rows, user_word, name, how), 45) or {}
                note = clean(res.get("text") or "")
                if _read(sessions / priv.sid / FILE).get("kind") != "pending":
                    obslog.event("private.threshold", session=priv.sid, kind=how, chars=len(note), late=True)
                    return   # the first turn stopped waiting: a late note would land on a later turn
                _write(sessions, priv.sid, {"kind": how, "text": note, "place": place, "ts": time.time()})
                obslog.event("private.threshold", session=priv.sid, kind=how, chars=len(note), place=bool(place))
            except Exception as e:  # noqa: BLE001
                obslog.exception("private.threshold_exception", e, session=priv.sid)
        threading.Thread(target=run, name="private-threshold", daemon=True).start()
    except Exception as e:  # noqa: BLE001 -- a missing note never blocks the switch, but it is logged
        import obslog
        obslog.exception("private.threshold_exception", e, session=getattr(priv, "sid", ""))
    return priv


def leave(priv, work, digest=None):
    """Called when the private session `priv` switches back to `work`; returns `work`. Runs `digest(priv)` (the
    private memory), and leaves the return scene line -- only where they went, never what happened."""
    try:
        if just_switched(work, "return_started"):
            import obslog
            obslog.event("private.switch_repeat", session=work.sid, way="out")
            return work
        work.return_started = time.time()
        if digest:
            digest(priv)
        sessions = Path(priv.meta_path).parent.parent
        visit = _read(sessions / priv.sid / SCENE_FILE)
        try:
            (sessions / priv.sid / SCENE_FILE).unlink()
        except OSError:
            pass
        if auto_scene(_state(sessions, work.character or priv.character)):
            work.scene_action = _scene_out(str(visit.get("place") or ""))
    except Exception as e:  # noqa: BLE001
        import obslog
        obslog.exception("private.leave_exception", e, session=getattr(priv, "sid", ""))
    return work


def take(session: Any, user_word: str = "the user") -> str:
    """The note for a private session's turn, once (the file is removed), as context; "" when none waits.
    A "brink" note raises the session's tension stage by one. What the last visit's digest just added to the private
    memory rides along once, even without a note."""
    try:
        path = Path(session.meta_path).parent / FILE
    except (TypeError, AttributeError):
        return ""
    note, until = _read(path), time.time() + WAIT_SEC
    while note.get("kind") == "pending" and time.time() < until:
        time.sleep(0.3)
        note = _read(path)
    try:
        path.unlink()
    except OSError:
        pass
    kind, text, place = note.get("kind"), str(note.get("text") or ""), str(note.get("place") or "")
    lines = ["[Threshold -- use once, in character; never quote or mention this note]"]
    fresh = _fresh_memory(_cid(session), WAIT_SEC)
    if fresh:
        lines.append("From your last time together, still fresh: " + " / ".join(fresh))
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
