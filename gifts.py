"""Gifts in private mode and the affection they move (composer-plus-menu plus/F; the first step of private-mode §3).

  GET  /api/sessions/<sid>/gifts   the catalog, this character's affection and how many gifts are left today
  POST /api/sessions/<sid>/gift    JSON {"gift": "<id>"}: judge it, record it, and hold a note for the next message

The engine decides what a gift is worth -- the character's gift_prefs (card extension) against the gift's tags,
through engine_data/affection.json -- never the model (private-mode D8). Affection lives beside the card in
characters/<id>/state.json (private-mode D6): a card can be shared, a relationship cannot. The page then sends the
giving as an action (sendAction), and take_pending appends the host note to it, so the character reacts to the
verdict it was told and the history keeps both. Only a private session can give.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import host_config

TABLE_PATH = Path(__file__).resolve().parent / "engine_data" / "affection.json"
PREFIX = "/api/sessions/"
_SID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_VERDICT_NOTE = {
    "loves": "You love this.",
    "likes": "You like this.",
    "neutral": "You have no strong feeling about it; react as your character would.",
    "dislikes": "You do not like this; react honestly, still in character.",
}

_pending: Dict[str, str] = {}
_lock = threading.Lock()


class GiftError(ValueError):
    pass


def table() -> Dict:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def catalog(ws=None) -> List[Dict]:
    """The gifts on offer (<workspace>/gifts.json); malformed entries are skipped, not fatal."""
    try:
        raw = json.loads((Path(ws or host_config.WORKSPACE) / "gifts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for g in raw.get("gifts") or []:
        if isinstance(g, dict) and g.get("id") and g.get("name"):
            out.append({"id": str(g["id"]), "icon": str(g.get("icon") or "🎁"), "name": str(g["name"]),
                        "tags": [str(t) for t in (g.get("tags") or [])]})
    return out


def prefs_of(card: Dict) -> Dict[str, List[str]]:
    import characters
    p = (characters.ext(card).get("gift_prefs") or {}) if card else {}
    return {k: [str(t) for t in (p.get(k) or [])] for k in ("loves", "likes", "dislikes")}


def judge(gift: Dict, prefs: Dict[str, List[str]]) -> str:
    """loves / likes / dislikes when a tag matches (loved wins over disliked), else neutral."""
    tags = set(gift.get("tags") or [])
    for verdict in ("loves", "dislikes", "likes"):
        if tags & set(prefs.get(verdict) or []):
            return verdict
    return "neutral"


def level_of(points: int, t: Optional[Dict] = None) -> Dict:
    levels = sorted((t or table())["levels"], key=lambda x: x["min"])
    lv = levels[0]
    for x in levels:
        if points >= x["min"]:
            lv = x
    return {"level": lv["level"], "title": lv["title"]}


def state_path(cid: str, ws=None) -> Path:
    import characters
    return characters.card_path(cid, ws).parent / "state.json"


def read_state(cid: str, ws=None) -> Dict:
    try:
        st = json.loads(state_path(cid, ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st.setdefault("affection", {"points": 0})
    st.setdefault("gifts", [])
    return st


def write_state(cid: str, st: Dict, ws=None) -> None:
    p = state_path(cid, ws)
    tmp = p.with_name(".state.%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _today(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def left_today(st: Dict, now: float, t: Dict) -> int:
    given = sum(1 for g in st.get("gifts") or [] if _today(g.get("ts", 0)) == _today(now))
    return max(0, int(t["gift"]["daily_limit"]) - given)


def give(cid: str, gift_id: str, ws=None, now: Optional[float] = None) -> Dict:
    """Judge and record one gift to one character. GiftError when unknown or over today's limit."""
    import characters
    now = time.time() if now is None else now
    t = table()
    gift = next((g for g in catalog(ws) if g["id"] == gift_id), None)
    if gift is None:
        raise GiftError("unknown gift: %s" % gift_id)
    with _lock:
        st = read_state(cid, ws)
        if left_today(st, now, t) <= 0:
            raise GiftError("daily limit")
        verdict = judge(gift, prefs_of(characters.load(cid, ws)))
        delta = int(t["gift"]["deltas"][verdict])
        last = (st["gifts"] or [{}])[-1]
        if last.get("id") == gift_id and delta > 0:          # the same gift again is worth less
            delta = max(1, int(delta * float(t["gift"]["repeat_factor"])))
        before = int(st["affection"].get("points") or 0)
        points = max(0, min(int(t["max"]), before + delta))
        st["affection"].update({"points": points, **level_of(points, t), "last_updated": now})
        st["gifts"].append({"id": gift_id, "ts": now, "verdict": verdict, "delta": points - before})
        st["gifts"] = st["gifts"][-200:]
        write_state(cid, st, ws)
    return {"gift": gift, "verdict": verdict, "label": t["gift"]["labels"][verdict], "delta": points - before,
            "before": before, "points": points, **level_of(points, t), "left_today": left_today(st, now, t)}


def host_note(res: Dict) -> str:
    """What the character is told about the gift. Agent-facing, so English; the page shows it as a gift chip."""
    g = res["gift"]
    return ("[Gift - host note: the user gave you %s %s (%s). %s Affection %d -> %d (Lv.%d %s). "
            "React in character to receiving it; never mention points or levels.]"
            % (g["icon"], g["name"], ", ".join(g["tags"]) or "-", _VERDICT_NOTE[res["verdict"]],
               res["before"], res["points"], res["level"], res["title"]))


def take_pending(sid: str, text: str) -> str:
    """The message with this session's gift note appended; clears it. Unchanged without one."""
    with _lock:
        note = _pending.pop(sid, "")
    return (text.rstrip() + "\n\n" + note) if note else text


def _session(sid: str):
    if not _SID.match(sid or "") or ".." in sid:
        return None
    import session
    return session.REG.peek(sid)


def _summary(cid: str, ws=None) -> Dict:
    t = table()
    st = read_state(cid, ws)
    points = int(st["affection"].get("points") or 0)
    return {"points": points, "max": t["max"], **level_of(points, t), "left_today": left_today(st, time.time(), t)}


def handle_get(path: str) -> Optional[Tuple[int, Dict]]:
    if not (path.startswith(PREFIX) and path.endswith("/gifts")):
        return None
    sess = _session(path[len(PREFIX):-len("/gifts")])
    if sess is None or not getattr(sess, "character", ""):
        return 404, {"ok": False, "error": "no such session"}
    return 200, {"ok": True, "private": bool(sess.is_private), "gifts": catalog(), "affection": _summary(sess.character)}


def handle_post(path: str, body: Dict) -> Optional[Tuple[int, Dict]]:
    if not (path.startswith(PREFIX) and path.endswith("/gift")):
        return None
    sid = path[len(PREFIX):-len("/gift")]
    sess = _session(sid)
    if sess is None or not getattr(sess, "character", ""):
        return 404, {"ok": False, "error": "no such session"}
    if not sess.is_private:
        return 400, {"ok": False, "error": "gifts are for private mode"}
    try:
        res = give(sess.character, str((body or {}).get("gift") or ""))
    except GiftError as e:
        return (429 if "limit" in str(e) else 400), {"ok": False, "error": str(e)}
    with _lock:
        _pending[sid] = host_note(res)
    return 200, {"ok": True, "result": res}
