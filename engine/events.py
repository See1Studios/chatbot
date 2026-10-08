"""The event mailbox (docs/plans/character-events-and-rooms.md evt/B): what happened -- work, system, private,
schedules -- goes into one record, each event addressed to the characters it concerns, and every session reads what
was addressed to its character since it last read (a cursor per session, kept across restarts).

The publisher resolves recipients by relation (the work's worker, the default character, who was there) and passes
their ids; this module never knows a role or a name. Events carry no conversation text. A private event reaches only
the private channel of the characters who were there (private-security T3).

  publish(type, to, channel="work", subject="", **payload) -> the event
  pending(sid, character, channel) -> events addressed to that character on that channel since the session's cursor
  mark(sid, event_id) / cursor(sid)

Standard library + platform_compat. Kept 30 days or 10 MB, private events 7 days (decision E3).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import platform_compat

ALL = "*"


def _log(evt: str, **fields) -> None:
    """The engine log's copy (OBSLOG_v1): the mailbox and the log are one record seen twice. Metadata only -- a
    private event keeps even its subject out."""
    try:
        from telemetry import obslog
        obslog.event(evt, **fields)
    except Exception:  # noqa: BLE001
        pass
CHANNELS = ("work", "private")
KEEP_SEC = 30 * 86400
KEEP_PRIVATE_SEC = 7 * 86400
MAX_BYTES = 10 * 1024 * 1024
_lock = threading.Lock()


def _dir() -> Path:
    from host_config import DATA
    return Path(os.environ.get("CHATBOT_EVENTS_DIR") or (DATA / "events"))


def _record() -> Path:
    return _dir() / "events.jsonl"


def _cursors() -> Path:
    return _dir() / "cursors.json"


class _Locked:
    """The record's write lock, across threads and processes (the runner and the tool server publish too)."""

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


def _read_all() -> List[Dict]:
    try:
        lines = _record().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def last_id() -> int:
    events = _read_all()
    return events[-1]["id"] if events else 0


def publish(type: str, to: Iterable[str], channel: str = "work", subject: str = "", **payload) -> Dict:
    """Record one event for the characters `to` (ids, or ALL). Returns it."""
    if channel not in CHANNELS:
        raise ValueError("unknown channel: %s" % channel)
    rcpt = [ALL] if to == ALL or ALL in list(to) else sorted({c for c in to if c})
    with _Locked():
        events = _read_all()
        now = time.time()
        event = {"id": max((events[-1]["id"] + 1) if events else 1, int(now * 1000)), "ts": now, "type": type,
                 "channel": channel, "subject": str(subject), "to": rcpt, "payload": payload}
        events.append(event)
        kept = [e for e in events
                if now - e.get("ts", 0) < (KEEP_PRIVATE_SEC if e.get("channel") == "private" else KEEP_SEC)]
        text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept)
        while len(text.encode("utf-8")) > MAX_BYTES and len(kept) > 1:
            kept = kept[len(kept) // 10 or 1:]
            text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept)
        if len(kept) == len(events):
            with open(str(_record()), "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        else:
            tmp = _record().with_suffix(".tmp")
            platform_compat.write_text(tmp, text, encoding="utf-8")
            tmp.replace(_record())
            _log("events.prune", removed=len(events) - len(kept), kept=len(kept))
    private = channel == "private"
    _log("events.publish", type=type, channel=channel, id=event["id"], to=len(rcpt) if rcpt != [ALL] else "*",
         **({} if private else {"subject": event["subject"]}))
    return event


def _load_cursors() -> Dict[str, int]:
    try:
        data = json.loads(_cursors().read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def cursor(sid: str) -> Optional[int]:
    """Where session `sid` has read up to; None for a session that has never read."""
    return _load_cursors().get(str(sid))


def mark(sid: str, event_id: int) -> None:
    with _Locked():
        data = _load_cursors()
        data[str(sid)] = max(int(event_id), data.get(str(sid), 0))
        tmp = _cursors().with_suffix(".tmp")
        platform_compat.write_text(tmp, json.dumps(data), encoding="utf-8")
        tmp.replace(_cursors())


def pending(sid: str, character: str, channel: str = "work") -> List[Dict]:
    """The events for `character` on `channel` after session `sid`'s cursor (all of them if it has none)."""
    after = cursor(sid) or 0
    got = [e for e in _read_all() if e["id"] > after and e.get("channel") == channel
           and (ALL in e.get("to", []) or character in e.get("to", []))]
    if got:
        _log("events.deliver", sid=str(sid), character=character, channel=channel, n=len(got),
             types=sorted({e["type"] for e in got}))
    return got


def latest(type: str) -> Optional[Dict]:
    """The newest event of a type, or None."""
    return next((e for e in reversed(_read_all()) if e.get("type") == type), None)


def recent(type: str) -> List[Dict]:
    """Every kept event of a type, oldest first."""
    return [e for e in _read_all() if e.get("type") == type]
