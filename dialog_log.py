"""A dialog's record (docs/plans/unified-message-inbox.md inbox/A-B): one file per dialog, a line per message,
numbered in that dialog -- Telegram's message box. Rooms and dialogs between two characters keep the same shape.

  register(matches, members, path, of, start, label) -- a module that owns another kind of dialog (room_chat: rooms)
      adds it
  dm_id(a, b) -> "dm:<a>:<b>", the two character ids sorted, so both ends name it alike
  members(did) -> who may write in it (a room's members and "user"; a dm's two characters); [] when unknown
  history(did, after=0) -> the messages after number `after`
  append(did, who, text, mentions=(), reply_to=None, kind="say") -> the message; refuses a writer who is not a member,
      a reply to a number the dialog does not hold, and a kind not in KINDS. Each message also goes into the event mailbox as `msg.new`
      {conversation, n, from} for the other characters -- never its text (character-events-and-rooms).
  dialogs_of(cid) -> the dialogs a character is in
  Read positions (inbox/B), two of them because one character has several brains (work, room seat, private):
  read(cid, did) -- how far the character has read: Telegram's read_inbox_max_id, for unread counts and badges
  seen(sid, cid, did) -- how far this session's brain has seen; a session that has seen nothing starts from the
      character's read, so a new session never skips what is unread
  saw(cid, sid, did, n) -- both move forward to n (never back); forget(sid) -- a handover: the new brain starts again
      from the character's read
  unread(cid, did, sid="") -> (messages after the position not written by cid, of those the ones mentioning cid)
  turn_note(cid, sid, noted, handed_over=False) -> the catch-up line before a work turn (inbox/C)

A message is {n, ts, who, text, mentions}, with reply_to (the n it answers) when it answers one and kind "action" when
it is a stage direction -- something done, not said (inbox/F, decision D10). The characters share one office (D9): a
dm is a coworker's DM or a visit to the other's desk, a room is a meeting room. The user's dialog with
one character is that character's session record, not a file here. Standard library + platform_compat; characters and
events are imported where they are needed. This module knows no other kind by name: kinds register, so it stays the
layer below them. Writes take a file lock: the tool server writes from its own process.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import platform_compat

USER = "user"
KINDS = ("say", "action")   # what a message is: words, or a stage direction the other side takes as something done
_lock = threading.Lock()
_kinds: List[Dict[str, Callable]] = []


def register(matches: Callable[[str], bool], members: Callable[[str], List[str]], path: Callable[[str], Path],
             of: Callable[[str], List[str]], start: Callable[[str, str], int], label: Callable[[str], str]) -> None:
    """`of(cid)`: that kind's dialogs the character is in; `start(cid, did)`: the read position before any was kept
    (a room: where the member last spoke); `label(did)`: what the dialog is called in a note."""
    _kinds.append({"matches": matches, "members": members, "path": path, "of": of, "start": start, "label": label})


def _kind(did: str) -> Optional[Dict[str, Callable]]:
    return next((k for k in _kinds if k["matches"](did or "")), None)


def _char_id(cid: str) -> bool:
    import characters
    return bool(characters.ID_RE.match(cid or ""))


def dm_id(a: str, b: str) -> str:
    if a == b or not (_char_id(a) and _char_id(b)):
        raise ValueError("a dm is between two different characters")
    return "dm:%s:%s" % tuple(sorted((a, b)))


def _dm_pair(did: str) -> List[str]:
    parts = (did or "").split(":")
    if len(parts) == 3 and parts[0] == "dm" and parts[1] < parts[2] and _char_id(parts[1]) and _char_id(parts[2]):
        return parts[1:]
    return []


def members(did: str) -> List[str]:
    pair = _dm_pair(did)
    if pair:
        return pair
    k = _kind(did)
    return list(k["members"](did)) if k else []


def _dir() -> Path:
    import os
    from host_config import DATA
    return Path(os.environ.get("CHATBOT_DIALOGS_DIR") or (Path(DATA) / "dialogs"))


def path(did: str) -> Optional[Path]:
    """The record's file: a registered kind's own (a room's stays where rooms keep it); a dm's under dialogs/ (no ":"
    in a file name)."""
    pair = _dm_pair(did)
    if pair:
        return _dir() / ("dm_%s_%s.log.jsonl" % tuple(pair))
    k = _kind(did)
    return k["path"](did) if k else None


class _Locked:
    """The dialogs' write lock, across threads and processes."""

    def __enter__(self):
        _dir().mkdir(parents=True, exist_ok=True)
        _lock.acquire()
        self.fh = open(str(_dir() / ".lock"), "a+", encoding="utf-8", newline="\n")
        platform_compat.lock_file(self.fh)
        return self

    def __exit__(self, *exc):
        platform_compat.unlock_file(self.fh)
        self.fh.close()
        _lock.release()


def history(did: str, after: int = 0) -> List[Dict]:
    p = path(did)
    try:
        lines = p.read_text(encoding="utf-8").splitlines() if p else []
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m["n"] > after:
            out.append(m)
    return out


def append(did: str, who: str, text: str, mentions: Iterable[str] = (), reply_to: Optional[int] = None,
           kind: str = "say") -> Dict:
    if kind not in KINDS:
        raise ValueError("kind: one of %s" % ", ".join(KINDS))
    writers = members(did)
    if who not in writers:
        raise ValueError("not a member of this dialog")
    p = path(did)
    with _Locked():
        prev = history(did)
        if reply_to is not None and not any(m["n"] == reply_to for m in prev):
            raise ValueError("reply_to: no such message in this dialog")
        msg = {"n": (prev[-1]["n"] + 1) if prev else 1, "ts": time.time(), "who": who, "text": text,
               "mentions": list(mentions)}
        if reply_to is not None:
            msg["reply_to"] = int(reply_to)
        if kind != "say":
            msg["kind"] = kind
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(str(p), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    _announce(did, msg, [m for m in writers if m not in (who, USER)])
    return msg


def _announce(did: str, msg: Dict, to: List[str]) -> None:
    """The update line (Telegram's pts): which dialog has which new number, for whom. A courtesy -- the record and the
    read positions already hold the truth, so a failure here loses no message."""
    if not to:
        return
    try:
        import events
        events.publish("msg.new", to, subject=did, conversation=did, n=msg["n"], **{"from": msg["who"]})
    except Exception as e:  # noqa: BLE001
        try:
            import obslog
            obslog.event("dialog.announce_failed", lvl="warn", dialog=did, error=str(e)[:200])
        except Exception:  # noqa: BLE001
            pass


def dialogs_of(cid: str) -> List[str]:
    out = []
    try:
        names = sorted(p.name for p in _dir().glob("dm_*.log.jsonl"))
    except OSError:
        names = []
    for name in names:
        did = _dm_from_file(name)
        if did and cid in _dm_pair(did):
            out.append(did)
    for k in _kinds:
        out.extend(k["of"](cid))
    return out


def _dm_from_file(name: str) -> Optional[str]:
    """dm_<a>_<b>.log.jsonl -> dm:<a>:<b>, at the one "_" where both halves are character ids."""
    core = name[len("dm_"):-len(".log.jsonl")] if name.startswith("dm_") and name.endswith(".log.jsonl") else ""
    for at in (i for i, ch in enumerate(core) if ch == "_"):
        did = "dm:%s:%s" % (core[:at], core[at + 1:])
        if _dm_pair(did):
            return did
    return None


# ------------------------------------------------------------------------------------------------ read positions

def _positions_path() -> Path:
    return _dir() / "positions.json"


def _load() -> Dict[str, Dict[str, int]]:
    try:
        data = json.loads(_positions_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {"read": dict(data.get("read") or {}), "seen": dict(data.get("seen") or {})}


def _save(data: Dict) -> None:
    tmp = _positions_path().with_suffix(".tmp")
    platform_compat.write_text(tmp, json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_positions_path())


def _key(a: str, did: str) -> str:
    return "%s|%s" % (a, did)


def read(cid: str, did: str) -> int:
    got = _load()["read"].get(_key(cid, did))
    if got is not None:
        return int(got)
    k = None if _dm_pair(did) else _kind(did)
    return int(k["start"](cid, did)) if k else 0


def seen(sid: str, cid: str, did: str) -> int:
    got = _load()["seen"].get(_key(sid, did)) if sid else None
    return int(got) if got is not None else read(cid, did)


def saw(cid: str, sid: str, did: str, n: int) -> None:
    with _Locked():
        data = _load()
        for table, who in (("read", cid), ("seen", sid)):
            if who:
                data[table][_key(who, did)] = max(int(n), int(data[table].get(_key(who, did), 0)))
        _save(data)


def forget(sid: str) -> None:
    with _Locked():
        data = _load()
        data["seen"] = {k: v for k, v in data["seen"].items() if not k.startswith(sid + "|")}
        _save(data)


def unread(cid: str, did: str, sid: str = "") -> Tuple[int, int]:
    after = seen(sid, cid, did) if sid else read(cid, did)
    new = [m for m in history(did, after) if m.get("who") != cid]
    return len(new), sum(1 for m in new if cid in (m.get("mentions") or []))


# ------------------------------------------------------------------------------------------------ the turn's note

RECAP_DIALOGS = 3      # after a handover: the dialogs with the latest messages
RECAP_MESSAGES = 2     # and the last messages of each
RECAP_CHARS = 200


def label(did: str, cid: str) -> str:
    """What `cid` calls the dialog in a note: the other character's name for a dm, a room's name."""
    import characters
    pair = _dm_pair(did)
    if pair:
        other = pair[0] if pair[1] == cid else pair[1]
        return characters.name(other) or other   # one thread holds both their messages and their visits
    k = _kind(did)
    return "%s (meeting room)" % (k["label"](did) if k else did)


def speaker(who: str) -> str:
    import characters
    return "the user" if who == USER else (characters.name(who) or who)


def how(m: Dict, did: str) -> str:
    """How it reached the reader (#558: "brought a coffee by DM" read wrong). Between two coworkers words come as a
    message and an action is done in person, at the reader's desk; in a meeting room both happen in the room."""
    if _dm_pair(did):
        return "came by your desk" if m.get("kind") == "action" else "message"
    return "in the room"


def line(m: Dict, did: str) -> str:
    """One message as a reader takes it: "Kit (message): words", "Kit (came by your desk): sets a coffee down"."""
    return "%s (%s): %s" % (speaker(m["who"]), how(m, did), str(m["text"])[:RECAP_CHARS])


def turn_note(cid: str, sid: str, noted: Dict[str, int], handed_over: bool = False) -> str:
    """The catch-up before a work turn (inbox/C): each dialog with messages this session has not seen, as counts --
    never a body, so other dialogs do not leak into this one. Said again only when something new came since it was
    last said (`noted`: dialog -> newest number said, kept by the caller per session). After a handover the new brain
    starts again from the character's read and also gets the latest messages of its busiest dialogs, so a brain that
    lost its tool results (an HTTP brain, a swapped provider) still knows what was said."""
    if handed_over:
        forget(sid)
        noted.clear()
    rows, fresh, recent = [], False, []
    for did in dialogs_of(cid):
        msgs = history(did)
        if handed_over and msgs:
            recent.append((msgs[-1]["ts"], did, msgs[-RECAP_MESSAGES:]))
        after = seen(sid, cid, did)
        new = [m for m in msgs if m["n"] > after and m.get("who") != cid]
        if not new:
            continue
        mention = sum(1 for m in new if cid in (m.get("mentions") or []))
        if _dm_pair(did):
            visits = sum(1 for m in new if m.get("kind") == "action")
            parts = [p for p in ("%d message%s" % (len(new) - visits, "" if len(new) - visits == 1 else "s")
                                 if len(new) - visits else "",
                                 "came by %d time%s" % (visits, "" if visits == 1 else "s") if visits else "") if p]
            count = ", ".join(parts)
        else:
            count = "%d new%s" % (len(new), ", %d mention you" % mention if mention else "")
        rows.append("%s: %s [%s]" % (label(did, cid), count, did))
        fresh = fresh or new[-1]["n"] > noted.get(did, 0)
        noted[did] = new[-1]["n"]
    out = []
    if recent:
        lines = []
        for _, did, msgs in sorted(recent, reverse=True)[:RECAP_DIALOGS]:
            lines.append("%s:" % label(did, cid))
            lines.extend("  #%d %s" % (m["n"], line(m, did)) for m in msgs)
        out.append("[Office messages -- background, carried over from before the handover]\n" + "\n".join(lines))
    if rows and (fresh or handed_over):
        out.append("[Office] Coworkers messaged you or came by your desk: %s. Read it with the "
                   "dialog tool {action: read, dialog_id: <the id in brackets>} and react when it fits -- you may "
                   "tell the user, as anyone would at their desk; do not mention this line itself." % " · ".join(rows))
    return "\n\n".join(out)
