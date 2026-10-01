"""A dialog's record (docs/plans/unified-message-inbox.md inbox/A): one file per dialog, a line per message, numbered
in that dialog -- Telegram's message box. Rooms and dialogs between two characters keep the same shape.

  register(matches, members, path) -- a module that owns another kind of dialog (room_chat: rooms) adds it here
  dm_id(a, b) -> "dm:<a>:<b>", the two character ids sorted, so both ends name it alike
  members(did) -> who may write in it (a room's members and "user"; a dm's two characters); [] when unknown
  history(did, after=0) -> the messages after number `after`
  append(did, who, text, mentions=(), reply_to=None) -> the message; refuses a writer who is not a member and a reply
      to a number the dialog does not hold

A message is {n, ts, who, text, mentions} and, when it answers one, reply_to (the n it answers). The user's dialog with
one character is that character's session record, not a file here. Standard library; characters is imported where
it is needed. This module knows no other kind by name: kinds register, so it stays the layer below them.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

USER = "user"
_lock = threading.Lock()
_kinds: List[Tuple[Callable[[str], bool], Callable[[str], List[str]], Callable[[str], Path]]] = []


def register(matches: Callable[[str], bool], members: Callable[[str], List[str]], path: Callable[[str], Path]) -> None:
    _kinds.append((matches, members, path))


def _kind(did: str):
    return next((k for k in _kinds if k[0](did or "")), None)


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
    return list(k[1](did)) if k else []


def _dir() -> Path:
    from host_config import DATA
    return Path(DATA) / "dialogs"


def path(did: str) -> Optional[Path]:
    """The record's file: a registered kind's own (a room's stays where rooms keep it); a dm's under dialogs/ (no ":"
    in a file name)."""
    pair = _dm_pair(did)
    if pair:
        return _dir() / ("dm_%s_%s.log.jsonl" % tuple(pair))
    k = _kind(did)
    return k[2](did) if k else None


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


def append(did: str, who: str, text: str, mentions: Iterable[str] = (), reply_to: Optional[int] = None) -> Dict:
    if who not in members(did):
        raise ValueError("not a member of this dialog")
    p = path(did)
    with _lock:
        prev = history(did)
        if reply_to is not None and not any(m["n"] == reply_to for m in prev):
            raise ValueError("reply_to: no such message in this dialog")
        msg = {"n": (prev[-1]["n"] + 1) if prev else 1, "ts": time.time(), "who": who, "text": text,
               "mentions": list(mentions)}
        if reply_to is not None:
            msg["reply_to"] = int(reply_to)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(str(p), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return msg
