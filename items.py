"""Items in private mode: given or used, and the affection a gift moves (composer-plus-menu plus/F; the first step of
private-mode §3). "Item" rather than "gift" (operator, 2026-09-28): giving is one thing to do with an item; some are
used -- on the character or together with them -- instead of given.

  GET  /api/sessions/<sid>/items   the catalog, this character's affection and how many gifts are left today
  POST /api/sessions/<sid>/item    JSON {"item": "<id>", "action": "give" | "use"}

The engine judges an item against the character's item_prefs (card extension; the older gift_prefs is still read)
through engine_data/affection.json -- never the model (private-mode D8). Only giving moves affection, three times a
day; using is told to the character with the same verdict so it reacts in character, and changes nothing else
(affection from what happens in talk comes with private-mode §3.6). Affection lives beside the card in
characters/<id>/state.json (private-mode D6). The page then sends the action (sendAction) and take_pending appends
the host note to it. Only a private session can give or use.
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
import platform_compat

ROOT = Path(__file__).resolve().parent
TABLE_PATH = ROOT / "engine_data" / "affection.json"
PLACEHOLDER = ROOT / "static" / "placeholders" / "item.webp"
PREFIX = "/api/sessions/"
ACTIONS = ("give", "use")
_SID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_VERDICT_NOTE = {
    "loves": "You love this.",
    "likes": "You like this.",
    "neutral": "You have no strong feeling about it; react as your character would.",
    "dislikes": "You do not like this; react honestly, still in character.",
}

_pending: Dict[str, str] = {}
_lock = threading.Lock()


class ItemError(ValueError):
    pass


def table() -> Dict:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def image_file(item_id: str, ws=None) -> Tuple[Path, bool]:
    """(path, is_placeholder): <workspace>/items/<id>.webp|png, else the engine placeholder (ART_PLACEHOLDER_v1)."""
    if _ID.match(item_id or ""):
        base = Path(ws or host_config.WORKSPACE) / "items"
        for ext in ("webp", "png"):
            if (base / ("%s.%s" % (item_id, ext))).is_file():
                return base / ("%s.%s" % (item_id, ext)), False
    return PLACEHOLDER, True


def catalog(ws=None) -> List[Dict]:
    """The items on offer (<workspace>/items.json); malformed entries are skipped, not fatal. An item can be given
    unless it says otherwise, and used when it has a use phrase ("use": "brushes their hair with the comb")."""
    try:
        raw = json.loads((Path(ws or host_config.WORKSPACE) / "items.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for it in raw.get("items") or []:
        if not (isinstance(it, dict) and _ID.match(str(it.get("id") or "")) and it.get("name")):
            continue
        use = str(it.get("use") or "").strip()
        actions = [a for a in (it.get("actions") or ["give"] + (["use"] if use else [])) if a in ACTIONS]
        if "use" in actions and not use:
            actions.remove("use")
        if not actions:
            continue
        out.append({"id": str(it["id"]), "icon": str(it.get("icon") or "🎁"), "name": str(it["name"]),
                    "tags": [str(t) for t in (it.get("tags") or [])], "actions": actions, "use": use,
                    "has_image": not image_file(str(it["id"]), ws)[1]})
    return out


def prefs_of(card: Dict) -> Dict[str, List[str]]:
    import characters
    ext = characters.ext(card) if card else {}
    p = ext.get("item_prefs") or ext.get("gift_prefs") or {}
    return {k: [str(t) for t in (p.get(k) or [])] for k in ("loves", "likes", "dislikes")}


def judge(item: Dict, prefs: Dict[str, List[str]]) -> str:
    """loves / likes / dislikes when a tag matches (loved wins over disliked), else neutral."""
    tags = set(item.get("tags") or [])
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
    if "given" not in st:
        st["given"] = st.pop("gifts", [])                   # written as "gifts" before the rename
    return st


def write_state(cid: str, st: Dict, ws=None) -> None:
    p = state_path(cid, ws)
    tmp = p.with_name(".state.%d.tmp" % os.getpid())
    platform_compat.write_text(tmp, json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _today(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def left_today(st: Dict, now: float, t: Dict) -> int:
    given = sum(1 for g in st.get("given") or [] if _today(g.get("ts", 0)) == _today(now))
    return max(0, int(t["give"]["daily_limit"]) - given)


def act(cid: str, item_id: str, action: str = "give", ws=None, now: Optional[float] = None) -> Dict:
    """Judge one item given to or used with one character; a gift is recorded and moves affection. ItemError when
    the item or action is unknown, or a gift is over today's limit."""
    import characters
    now = time.time() if now is None else now
    t = table()
    item = next((x for x in catalog(ws) if x["id"] == item_id), None)
    if item is None:
        raise ItemError("unknown item: %s" % item_id)
    if action not in item["actions"]:
        raise ItemError("%s cannot be %s" % (item_id, "given" if action == "give" else "used"))
    verdict = judge(item, prefs_of(characters.load(cid, ws)))
    with _lock:
        st = read_state(cid, ws)
        before = int(st["affection"].get("points") or 0)
        points = before
        if action == "give":
            if left_today(st, now, t) <= 0:
                raise ItemError("daily limit")
            delta = int(t["give"]["deltas"][verdict])
            last = (st["given"] or [{}])[-1]
            if last.get("id") == item_id and delta > 0:     # the same gift again is worth less
                delta = max(1, int(delta * float(t["give"]["repeat_factor"])))
            points = max(0, min(int(t["max"]), before + delta))
            st["affection"].update({"points": points, **level_of(points, t), "last_updated": now})
            st["given"].append({"id": item_id, "ts": now, "verdict": verdict, "delta": points - before})
            st["given"] = st["given"][-200:]
            write_state(cid, st, ws)
    return {"item": item, "action": action, "verdict": verdict, "label": t["give"]["labels"][verdict],
            "delta": points - before, "before": before, "points": points, **level_of(points, t),
            "left_today": left_today(st, now, t)}


def host_note(res: Dict) -> str:
    """What the character is told. Agent-facing, so English; the page shows it as an item chip."""
    it = res["item"]
    what = "%s %s (%s)" % (it["icon"], it["name"], ", ".join(it["tags"]) or "-")
    if res["action"] == "use":
        return ("[Item - host note: the user uses %s on or with you: \"%s\". %s React in character; never mention "
                "items, points or levels.]" % (what, it["use"], _VERDICT_NOTE[res["verdict"]]))
    return ("[Item - host note: the user gave you %s. %s Affection %d -> %d (Lv.%d %s). React in character to "
            "receiving it; never mention points or levels.]"
            % (what, _VERDICT_NOTE[res["verdict"]], res["before"], res["points"], res["level"], res["title"]))


def take_pending(sid: str, text: str) -> str:
    """The message with this session's item note appended; clears it. Unchanged without one."""
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
    if not (path.startswith(PREFIX) and path.endswith("/items")):
        return None
    sess = _session(path[len(PREFIX):-len("/items")])
    if sess is None or not getattr(sess, "character", ""):
        return 404, {"ok": False, "error": "no such session"}
    return 200, {"ok": True, "private": bool(sess.is_private), "items": catalog(), "affection": _summary(sess.character)}


def handle_post(path: str, body: Dict) -> Optional[Tuple[int, Dict]]:
    if not (path.startswith(PREFIX) and path.endswith("/item")):
        return None
    sid = path[len(PREFIX):-len("/item")]
    sess = _session(sid)
    if sess is None or not getattr(sess, "character", ""):
        return 404, {"ok": False, "error": "no such session"}
    if not sess.is_private:
        return 400, {"ok": False, "error": "items are for private mode"}
    body = body or {}
    try:
        res = act(sess.character, str(body.get("item") or ""), str(body.get("action") or "give"))
    except ItemError as e:
        return (429 if "limit" in str(e) else 400), {"ok": False, "error": str(e)}
    with _lock:
        _pending[sid] = host_note(res)
    return 200, {"ok": True, "result": res}
