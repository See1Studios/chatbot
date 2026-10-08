"""A character's name change, carried by the engine (NAME_CHANGE_v1, operator 2026-10-02: names were swapped by hand in
two cards and nothing else followed). Ids carry everything, so screens and engine lines follow by themselves; what
does not is a name written as text. The engine settles it, not the model (VISION):

  reconcile(ws, now) -- each card remembers the name it last had (`known_name` in its chatbot extension). A card whose
      name differs was renamed: the change goes into the card's `renames` [{old, new, at}], and the names are rewritten
      in every character's card text, visual.md and lorebook -- all renames at once, in one pass, so a swap does not
      undo itself. Memories and talk are not rewritten (private, and the record of what was said).
  note(ws) -- the name changes, one line, for the instruction bundle: a brain reads old notes and memories right.
  as_of(text, ts, ws) -- text written at `ts`, with each name as it was then turned into the name now: what screens
      and an HTTP brain's replay show of older talk. Talk after a change is left as it is.

A name is replaced where it starts a word (not right after a letter); Korean particles may follow it. Standard library
+ characters; rewrites go through characters.save and platform_compat.
"""
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional, Tuple

import characters
import platform_compat

_cache: Dict[str, object] = {"at": 0.0, "renames": []}
CACHE_SEC = 5.0


def _ext(card: Dict) -> Dict:
    return card["data"].setdefault("extensions", {}).setdefault(characters.EXT, {})


def _pattern(names: List[str]):
    names = sorted({n for n in names if n}, key=len, reverse=True)
    return re.compile(r"(?<![\w])(%s)" % "|".join(re.escape(n) for n in names)) if names else None


def _swap(text: str, mapping: Dict[str, str]) -> str:
    rx = _pattern(list(mapping))
    return rx.sub(lambda m: mapping[m.group(1)], text) if rx and text else text


def _walk(value, mapping: Dict[str, str]):
    if isinstance(value, str):
        return _swap(value, mapping)
    if isinstance(value, list):
        return [_walk(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: (v if k in ("name", "known_name", "renames") else _walk(v, mapping)) for k, v in value.items()}
    return value


def reconcile(ws=None, now: Optional[float] = None) -> List[Dict]:
    """Find renamed cards and carry the change; returns [{id, old, new, at}] (empty when nothing changed)."""
    now = now or time.time()
    found, cards = [], {}
    for c in characters.listing(ws):
        cid, card = c["id"], c["card"]
        cards[cid] = card
        e, name = _ext(card), card["data"].get("name") or ""
        if e.get("known_name") is None:
            e["known_name"] = name                       # first sight: the name it has now is its name
            characters.save(cid, card, ws)
        elif e["known_name"] != name and name:
            found.append({"id": cid, "old": e["known_name"], "new": name, "at": now})
    if not found:
        return []
    mapping = {f["old"]: f["new"] for f in found}
    for cid, card in cards.items():
        e = _ext(card)
        for f in found:
            if f["id"] == cid:
                e.setdefault("renames", []).append({"old": f["old"], "new": f["new"], "at": f["at"]})
                e["known_name"] = f["new"]
        card["data"] = _walk(card["data"], mapping)
        characters.save(cid, card, ws)
        for p in (characters.card_path(cid, ws).parent / "visual.md", characters.lorebook_path(cid, ws)):
            extra = p.name
            if p.is_file():
                old = p.read_text(encoding="utf-8")
                new = _swap(old, mapping) if extra.endswith(".md") else json.dumps(
                    _walk(json.loads(old), mapping), ensure_ascii=False, indent=2) + "\n"
                if new != old:
                    platform_compat.write_text(p, new, encoding="utf-8")
    _cache["at"] = 0.0
    try:
        from telemetry import obslog
        obslog.event("character.renamed", lvl="info", changes=[{"id": f["id"], "at": f["at"]} for f in found])
    except Exception:  # noqa: BLE001
        pass
    return found


def renames(ws=None) -> List[Dict]:
    """Every recorded change, oldest first: {id, old, new, at}."""
    if ws is None and time.time() - float(_cache["at"]) < CACHE_SEC:
        return list(_cache["renames"])  # type: ignore[arg-type]
    out = []
    for c in characters.listing(ws):
        for r in (characters.ext(c["card"]).get("renames") or []):
            if isinstance(r, dict) and r.get("old") and r.get("new"):
                out.append({"id": c["id"], "old": r["old"], "new": r["new"], "at": float(r.get("at") or 0)})
    out.sort(key=lambda r: r["at"])
    if ws is None:
        _cache.update(at=time.time(), renames=out)
    return out


def as_of(text: str, ts, ws=None) -> str:
    """`text` as written at `ts`, each character's name then turned into its name now."""
    if not text or not isinstance(ts, (int, float)):
        return text
    later = [r for r in renames(ws) if r["at"] > ts]
    if not later:
        return text
    then: Dict[str, Tuple[str, str]] = {}                # id -> (name at ts, name now)
    for r in later:                                      # oldest first: the first change after ts names it then
        then.setdefault(r["id"], (r["old"], r["new"]))
        then[r["id"]] = (then[r["id"]][0], r["new"])
    return _swap(text, {old: new for old, new in then.values() if old != new})


def note(ws=None) -> str:
    """One line for the instruction bundle, "" when no character was ever renamed."""
    rs = renames(ws)
    if not rs:
        return ""
    parts = ["%s was called %s until %s" % (r["new"], r["old"], time.strftime("%m-%d %H:%M", time.localtime(r["at"])))
             for r in rs]
    return ("[Name changes] " + "; ".join(parts) + ". Notes, memories and talk from before use the former names "
            "-- read them as the same people.")
