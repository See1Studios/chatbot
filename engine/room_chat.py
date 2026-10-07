"""Group rooms (docs/plans/character-events-and-rooms.md evt/E): several characters and the user in one chat.

A room is a name, a mode and its members; its talk is one record. Each member speaks from its own hidden session
(mode "room": the character's own brain, card, roles and work memory, never its private memory, and never taken for
its one-to-one chat). When the user says something, the room picks who answers -- SillyTavern's group activation
names: `natural` (whoever is @mentioned first, then each member by its talkativeness), `list` (in member order),
`manual` (only who is mentioned) -- and each speaker gets what was said since it last spoke. A reply may @mention
another member, who then answers too, within the limits (decision E4): at most MAX_REPLIES answers per user
message, of which at most MAX_CHAIN come from characters calling each other. Then it is the user's turn.

This first step is work rooms. Private play rooms (their own room memory, E7) come next.

  create(name, members, strategy="natural") -> room     say(rid, text) -> the user's message (answers follow)
  rooms() / room(rid) / messages(rid, after=0)          api(method, path, body) -- /api/rooms
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

import dialog_log
import platform_compat


def _log(evt: str, **fields) -> None:
    """Metadata into the engine log (OBSLOG_v1): who, when, how long, how many -- never what was said."""
    try:
        import obslog
        obslog.event(evt, **fields)
    except Exception:  # noqa: BLE001
        pass

STRATEGIES = ("natural", "list", "manual")
MODES = ("work",)                       # "private" (play rooms) is the next step
MAX_REPLIES = 6                          # E4: answers per user message
MAX_CHAIN = 4                            # E4: of those, answers to another character's @mention
TALKATIVENESS = 0.5                      # SillyTavern's default
REPLY_TIMEOUT = 240
MAX_TEXT = 4000
_RID = re.compile(r"^room_[0-9a-f]{12}$")
_MENTION = re.compile(r"@([^\s@,.!?:;()\[\]{}\"']{1,40})")
_WORD = re.compile(r"\w")                 # a name mentioned ends where a word does
_busy: Dict[str, bool] = {}
_speaking: Dict[str, str] = {}   # room id -> the member answering right now (the page shows it typing)


def _dir() -> Path:
    from host_config import DATA
    return Path(DATA) / "rooms"


def _room_path(rid: str) -> Path:
    return _dir() / ("%s.json" % rid)


def _log_path(rid: str) -> Path:
    return _dir() / ("%s.log.jsonl" % rid)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    platform_compat.write_text(tmp, json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _names(members: List[str]) -> Dict[str, str]:
    import characters
    return {cid: characters.name(cid) or cid for cid in members}


# ------------------------------------------------------------------------------------------------ rooms

def create(name: str, members: List[str], strategy: str = "natural", mode: str = "work") -> Dict:
    import characters
    members = [m for m in dict.fromkeys(members or []) if characters.ID_RE.match(m or "") and characters.card_path(m).is_file()]
    if len(members) < 2:
        raise ValueError("a room needs at least two characters")
    if strategy not in STRATEGIES or mode not in MODES:
        raise ValueError("unknown strategy or mode")
    room = {"id": "room_" + uuid.uuid4().hex[:12], "name": (name or "").strip()[:60] or "Group room",   # the page fills its own word; a tool call without one gets this
            "mode": mode, "members": members, "strategy": strategy, "seats": {}, "seen": {}, "created": time.time()}
    _write_json(_room_path(room["id"]), room)
    _log("room.create", room=room["id"], members=len(members), strategy=strategy, mode=mode)
    return room


def room(rid: str) -> Optional[Dict]:
    if not _RID.match(rid or ""):
        return None
    try:
        data = json.loads(_room_path(rid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    import characters
    members = data.get("members") or []
    alive = [m for m in members if characters.ID_RE.match(m or "") and characters.card_path(m).is_file()]
    if alive != members:
        data["members"] = alive
        for m in [cid for cid in members if cid not in alive]:
            data.get("seats", {}).pop(m, None)
            data.get("seen", {}).pop(m, None)
        try:
            _write_json(_room_path(rid), data)
        except OSError:
            pass
    return data


def update(rid: str, name: Optional[str] = None, strategy: Optional[str] = None,
           members: Optional[List[str]] = None, add_member: Optional[str] = None,
           remove_member: Optional[str] = None) -> Dict:
    """Update room details or members. Enforces minimum 2 valid characters."""
    r = room(rid)
    if not r:
        raise ValueError("no such room")
    import characters
    cur_members = list(r.get("members") or [])
    if members is not None:
        cur_members = list(members)
    if add_member and add_member not in cur_members:
        cur_members.append(add_member)
    if remove_member and remove_member in cur_members:
        cur_members.remove(remove_member)
    valid_members = [m for m in dict.fromkeys(cur_members) if characters.ID_RE.match(m or "") and characters.card_path(m).is_file()]
    if len(valid_members) < 2:
        raise ValueError("a room needs at least two characters")
    if strategy is not None:
        if strategy not in STRATEGIES:
            raise ValueError("unknown strategy")
        r["strategy"] = strategy
    if name is not None:
        clean_name = name.strip()[:60]
        if clean_name:
            r["name"] = clean_name
    r["members"] = valid_members
    # Clean up seats and seen for removed members
    for m in list(r.get("seats", {})):
        if m not in valid_members:
            r["seats"].pop(m, None)
    for m in list(r.get("seen", {})):
        if m not in valid_members:
            r["seen"].pop(m, None)
    _write_json(_room_path(rid), r)
    _log("room.update", room=rid, members=len(valid_members), strategy=r["strategy"])
    return r


def rooms() -> List[Dict]:
    out = []
    for p in sorted(_dir().glob("room_*.json")) if _dir().is_dir() else []:
        r = room(p.stem)
        if r:
            last = (messages(r["id"]) or [None])[-1]   # for the talk list (ux/S1): who spoke last, when, one line
            out.append(dict({k: r[k] for k in ("id", "name", "mode", "members", "strategy", "created")},
                            last=last and {"at": last["ts"], "who": last["who"], "text": str(last["text"])[:80]}))
    return sorted(out, key=lambda r: -r["created"])


def messages(rid: str, after: int = 0) -> List[Dict]:
    return dialog_log.history(rid, after)


def _append(rid: str, who: str, text: str, mentions: List[str]) -> Dict:
    return dialog_log.append(rid, who, text, mentions)



def _named_now(m: Dict) -> Dict:
    """A room message as shown: from before a rename, with today's names (NAME_CHANGE_v1); the record is kept."""
    import character_names
    text = character_names.as_of(m.get("text") or "", m.get("ts"))
    return m if text == m.get("text") else dict(m, text=text)

def _writers(rid: str) -> List[str]:
    r = room(rid)
    return list(r["members"]) + [dialog_log.USER] if r else []


def _rooms_of(cid: str) -> List[str]:
    out = []
    for p in sorted(_dir().glob("room_*.json")) if _dir().is_dir() else []:
        r = room(p.stem)
        if r and cid in r["members"]:
            out.append(r["id"])
    return out


def _start(cid: str, rid: str) -> int:
    """A member's read position before any was kept: where it last spoke (the room's own `seen`)."""
    r = room(rid)
    return int((r or {}).get("seen", {}).get(cid, 0))


# A room is a kind of dialog (unified-message-inbox inbox/A-B): its record is a dialog's, kept in its own file.
dialog_log.register(lambda did: bool(_RID.match(did)), _writers, lambda did: _log_path(did), _rooms_of, _start,
                    lambda did: (room(did) or {}).get("name") or did)


def mentions(text: str, members: List[str], names: Optional[Dict[str, str]] = None) -> List[str]:
    """Members @mentioned in `text`, in order, by name (or id). Names may hold spaces ("@Yae Miko"): at each "@" the
    longest member name that follows, as a whole word, wins; otherwise the single word there may be a member id."""
    names = names if names is not None else _names(members)
    # Compared at the positions of the text as written: lower-casing can change a string's length ("İ" becomes two
    # code points), so positions taken from `text` do not hold in `text.lower()` (review of #526).
    longest = sorted(((v, k) for k, v in names.items() if v), key=lambda x: -len(x[0]))
    text, out = text or "", []
    for m in _MENTION.finditer(text):
        at = m.start(1)
        cid = next((k for v, k in longest if text[at:at + len(v)].lower() == v.lower() and not _WORD.match(text, at + len(v))),
                   None) or (m.group(1) if m.group(1) in members else None)
        if cid and cid not in out:
            out.append(cid)
    return out


def pick(r: Dict, mentioned: List[str], last: str = "", rng=random, talk: Optional[Dict[str, float]] = None) -> List[str]:
    """Who answers a message, in order (SillyTavern activation)."""
    members, talk = r["members"], talk or {}
    first = [m for m in mentioned if m in members]
    if r["strategy"] == "manual":
        return first
    if r["strategy"] == "list":
        return first + [m for m in members if m not in first and m != last]
    rest = [m for m in members if m not in first and m != last and rng.random() < talk.get(m, TALKATIVENESS)]
    if not first and not rest:
        pool = [m for m in members if m != last] or members
        rest = [rng.choice(pool)]
    return first + rest


# ------------------------------------------------------------------------------------------------ talking

def _seat(r: Dict, cid: str):
    """The member's hidden room session, made on first use from its first work brain."""
    from session import REG
    sid = r["seats"].get(cid)
    if sid:
        sess = REG.get(sid)
        if getattr(sess, "mode", "") == "room":
            return sess
    import characters
    brain = (characters.brains(characters.load(cid), "work") or [{}])[0]
    like = REG.get_active(cid)
    sess = REG.create(model=brain.get("model") or like.model, provider=brain.get("provider") or like.provider,
                      character=cid, mode="room")
    r["seats"][cid] = sess.sid
    _write_json(_room_path(r["id"]), r)
    return sess


def _prompt(r: Dict, cid: str, names: Dict[str, str], user_title: str) -> str:
    """What the member hears: the room's talk since it last spoke, and that it is its turn."""
    since = int(r["seen"].get(cid, 0))
    lines = [("%s: %s" % (user_title if m["who"] == "user" else names.get(m["who"], m["who"]), m["text"]))
             for m in messages(r["id"], since)[-30:]]
    others = ", ".join("@" + names[m] for m in r["members"] if m != cid)
    return ("[Group room \"%s\" -- members: %s and %s] What was said since you last spoke:\n%s\n\n"
            "It is your turn. Answer as yourself in one to three sentences, like a quick messenger chat: react to "
            "what was just said -- %s's words or another member's -- and keep the back-and-forth going. When the "
            "talk naturally turns to another member, @mention them by name so they answer next; do not mention "
            "anyone just out of habit. Do not use tools or start work here; if work is needed, say so and suggest taking it to your "
            "own chat." % (r["name"], user_title, others, "\n".join(lines), user_title))


def _answer(sess, text: str, timeout: float = REPLY_TIMEOUT) -> Tuple[object, str]:
    """Send `text` to the member's session and wait for its answer. (session, answer or "")."""
    before = len(sess.history)
    new = sess.send(text)
    sess = new or sess
    if new is not None:
        before = 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.5)
        if not getattr(sess, "busy", False) and len(sess.history) > before:
            answers = [h for h in sess.history[before:] if h.get("role") == "assistant" and not h.get("notice")]
            if answers:
                return sess, str(answers[-1].get("text") or "").strip()
    return sess, ""


def _run(rid: str, msg: Dict) -> None:
    """Answers to one user message, then the chain of @mentions, within the limits."""
    try:
        r = room(rid)
        names = _names(r["members"])
        import characters
        user_title = characters.user_title(characters.default_character()) or "user"
        queue, replies, chain, last = pick(r, msg["mentions"]), 0, 0, ""
        while queue and replies < MAX_REPLIES:
            cid = queue.pop(0)
            _speaking[rid] = cid
            sess = _seat(r, cid)
            t0 = time.time()
            sess, answer = _answer(sess, _prompt(r, cid, names, user_title))
            _log("room.turn", room=rid, character=cid, sid=sess.sid, secs=round(time.time() - t0, 1),
                 chars=len(answer), ok=bool(answer), lvl="info" if answer else "warn")
            r = room(rid)
            if sess.sid != r["seats"].get(cid):
                r["seats"][cid] = sess.sid
            r["seen"][cid] = messages(rid)[-1]["n"] if messages(rid) else 0
            _write_json(_room_path(rid), r)
            dialog_log.saw(cid, sess.sid, rid, r["seen"][cid])   # it heard the room up to here (inbox/B)
            if not answer:
                continue
            said = mentions(answer, r["members"], names)
            m = _append(rid, cid, answer[:MAX_TEXT], said)
            r["seen"][cid] = m["n"]
            _write_json(_room_path(rid), r)
            dialog_log.saw(cid, sess.sid, rid, m["n"])
            replies, last = replies + 1, cid
            for nxt in said:
                if nxt != cid and nxt not in queue and chain < MAX_CHAIN:
                    queue.insert(0, nxt)
                    chain += 1
                    _log("room.chain", room=rid, **{"from": cid, "to": nxt})
        _log("room.done", room=rid, replies=replies, chain=chain, left=len(queue))
    except Exception as e:  # noqa: BLE001 -- a failed turn must end the room's busy state and be seen
        try:
            import obslog
            obslog.exception("room.failed", e, room=rid)
        except Exception:  # noqa: BLE001
            pass
    finally:
        _busy.pop(rid, None)
        _speaking.pop(rid, None)


def say(rid: str, text: str) -> Dict:
    """The user's message into the room; the answers are worked out in the background (poll messages())."""
    r = room(rid)
    if r is None:
        raise KeyError(rid)
    text = (text or "").strip()[:MAX_TEXT]
    if not text:
        raise ValueError("empty message")
    if _busy.get(rid):
        raise RuntimeError("the room is still answering")
    msg = _append(rid, "user", text, mentions(text, r["members"]))
    _log("room.say", room=rid, n=msg["n"], chars=len(text), mentions=len(msg["mentions"]))
    try:
        import events
        events.publish("room.message", r["members"], subject=rid, n=msg["n"], who="user", mentions=msg["mentions"])
    except Exception:  # noqa: BLE001
        pass
    _busy[rid] = True
    threading.Thread(target=_run, args=(rid, msg), name="room-" + rid, daemon=True).start()
    return msg


def artifacts_dir(rid: str) -> Path:
    return _dir() / rid / "artifacts"


def artifacts(rid: str) -> List[dict]:
    r = room(rid)
    if r is None:
        raise ValueError("no such room")
    adir = artifacts_dir(rid)
    if not adir.exists():
        return []
    exts_img = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    exts_doc = {".md", ".txt", ".json", ".pdf", ".html", ".csv", ".yaml", ".yml"}
    exts_code = {".py", ".js", ".ts", ".gd", ".sh", ".sql", ".css"}
    found = []
    seen_sizes = set()
    seen_names = set()
    from urllib.parse import quote
    try:
        for fp in adir.rglob("*"):
            if not fp.is_file() or fp.name.startswith("."):
                continue
            if any(part.startswith(".") for part in fp.parts[:-1]):
                continue
            suffix = fp.suffix.lower()
            if suffix not in exts_img and suffix not in exts_doc and suffix not in exts_code:
                continue
            try:
                sz = fp.stat().st_size
            except OSError:
                continue
            if sz in seen_sizes and sz > 5000:
                continue
            if fp.name in seen_names:
                continue
            seen_sizes.add(sz)
            seen_names.add(fp.name)

            kind = "image" if suffix in exts_img else ("document" if suffix in exts_doc else "code")
            url = f"/api/file/raw?path={quote(str(fp))}"

            sz_str = f"{sz / 1048576:.1f} MB" if sz >= 1048576 else (f"{sz / 1024:.0f} KB" if sz >= 1024 else f"{sz} B")

            mtime = fp.stat().st_mtime
            found.append({
                "name": fp.name,
                "stem": fp.stem,
                "kind": kind,
                "ext": suffix.lstrip("."),
                "size": sz,
                "size_human": sz_str,
                "url": url,
                "mtime": mtime,
                "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
            })
    except Exception as e:
        _logger.warning("failed to collect room artifacts for %s: %s", rid, e)
    found.sort(key=lambda x: x["mtime"], reverse=True)
    return found


# ------------------------------------------------------------------------------------------------ http

def api(method: str, path: str, body: Optional[dict]) -> Optional[Tuple[int, Dict]]:
    """GET /api/rooms · POST /api/rooms {name, members, strategy} · GET /api/rooms/<id>?after=n (via path suffix
    /after/<n>) · GET /api/rooms/<id>/artifacts · POST /api/rooms/<id>/say {text}. A POST is the operator's page."""
    clean_path = path.split("?")[0]
    if not (clean_path == "/api/rooms" or clean_path.startswith("/api/rooms/")):
        return None
    rest = clean_path[len("/api/rooms"):].strip("/").split("/")
    try:
        if method == "GET" and rest == [""]:
            return 200, {"ok": True, "rooms": rooms()}
        if method == "POST" and rest == [""]:
            b = body or {}
            return 200, {"ok": True, "room": create(str(b.get("name") or ""), list(b.get("members") or []),
                                                     str(b.get("strategy") or "natural"))}
        rid = rest[0]
        r = room(rid)
        if r is None:
            return 404, {"ok": False, "error": "no such room"}
        if method == "GET" and len(rest) == 2 and rest[1] == "artifacts":
            arts = artifacts(rid)
            return 200, {"ok": True, "artifacts": arts, "total": len(arts), "next_before": None}
        if method == "GET" and (len(rest) == 1 or (len(rest) == 3 and rest[1] == "after" and rest[2].isdigit())):
            after = int(rest[2]) if len(rest) == 3 else 0
            msgs = [_named_now(m) for m in messages(rid, after)]
            names = _names(r["members"])
            import dialog_log
            for m in msgs:
                who = m.get("who")
                if who and who != dialog_log.USER and who not in names:
                    names[who] = dialog_log.speaker(who)
            return 200, {"ok": True, "room": {k: r[k] for k in ("id", "name", "mode", "members", "strategy")},
                         "names": names, "messages": msgs, "busy": bool(_busy.get(rid)),
                         "speaking": _speaking.get(rid, "")}
        if method in ("PATCH", "POST") and len(rest) == 1:
            b = body or {}
            updated = update(rid, name=b.get("name"), strategy=b.get("strategy"), members=b.get("members"),
                             add_member=b.get("add_member"), remove_member=b.get("remove_member"))
            return 200, {"ok": True, "room": updated}
        if method == "POST" and len(rest) == 2 and rest[1] == "members":
            b = body or {}
            updated = update(rid, add_member=b.get("add"), remove_member=b.get("remove"))
            return 200, {"ok": True, "room": updated}
        if method == "POST" and len(rest) == 2 and rest[1] == "say":
            return 200, {"ok": True, "message": say(rid, str((body or {}).get("text") or ""))}
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}
    except RuntimeError as e:
        return 409, {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}
