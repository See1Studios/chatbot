"""Read every character setting, merge changes into their own files, keep and restore versions (character-settings
cs/A, cs/B). The page never builds a whole file: it sends the keys it changed and this module reads the file, changes
those keys and writes it whole and atomically -- after keeping the previous version in
<data>/backups/characters/<id>/<file>.<time> (the newest KEEP per file).

  GET   /api/characters/<id>/settings                    {fields: [{key, tab, type, label, editable, sensitive,
                                                          value, options?, default?}]}
  PATCH /api/characters/<id>/settings                    {key: value, ...} -> {changed: [...], errors: {key: why}}
  GET   /api/characters/<id>/settings/versions/<key>      {versions: [{version, bytes}]} newest first
  POST  /api/characters/<id>/settings/restore             {key, version} -> the file back at that version
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import characters
import items
import platform_compat
from character_settings import fields as F

KEEP = 20
MAX_TEXT = 200
MAX_LONG = 100_000
_PATH = re.compile(r"^/api/characters/([\w-]{1,64})/settings(?:/(versions)/([\w.]+)|/(restore))?$")


def _card_dir(cid: str, ws=None) -> Path:
    return characters.card_path(cid, ws).parent


def _file_of(f: Dict, cid: str, ws=None) -> Path:
    """The file a setting lives in."""
    src = f["source"]
    if src in ("card", "display", "ext"):
        return characters.card_path(cid, ws)
    if src == "brain":
        return characters.brain_override_path(cid, ws)
    if src == "team":
        return characters.team_path(ws)
    if src == "state":
        return items.state_path(cid, ws)
    return _card_dir(cid, ws) / f["where"]


def _backups(cid: str, path: Path, ws=None) -> Tuple[Path, str]:
    root = characters.card_path(cid, ws).parents[2].parent / "backups" / "characters"   # <data>/backups/characters
    return (root / ("_team" if path.name == "team.json" else cid)), path.name


def keep_version(cid: str, path: Path, ws=None) -> None:
    """The file as it is now, kept before a write (ladder/B); the newest KEEP per file."""
    if not path.exists():
        return
    d, name = _backups(cid, path, ws)
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d%H%M%S")
    n = 0
    while (d / ("%s.%s%s" % (name, stamp, "-%d" % n if n else ""))).exists():
        n += 1
    platform_compat.write_text(d / ("%s.%s%s" % (name, stamp, "-%d" % n if n else "")),
                               path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    for old in sorted(d.glob(name + ".*"))[:-KEEP]:
        old.unlink()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    platform_compat.write_text(tmp, text, encoding="utf-8")
    tmp.replace(path)


def _roles_available(ws=None) -> List[str]:
    root = characters.team_path(ws).parent / "roles"
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))) \
        if root.is_dir() else []


def _value(f: Dict, cid: str, card: Dict, ws=None) -> Any:
    src, where = f["source"], f["where"]
    data = card.get("data") or {}
    if src == "card":
        v = data.get(where)
        return v if v is not None else ([] if f["type"] == "list" else "")
    if src == "ext":
        node = characters.ext(card)
        for part in where.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return str(node or "")
    if src == "display":
        v = characters.ext(card).get("display", {}).get(where)
        return (v if isinstance(v, dict) else None) if f["type"] == "focal" else str(v or "")
    if src == "brain":
        return (characters.read_brain_overrides(cid, ws) or {}).get(where)
    if src == "team":
        return list(characters.load_team(ws).get("members", {}).get(cid) or [])
    if src == "state":
        st = items.read_state(cid, ws)
        defaults = {"threshold": "gist", "auto_scene": True, "places": []}
        return st.get(where, defaults.get(where))
    path = _file_of(f, cid, ws)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def card_format(cid: str, ws=None) -> Dict[str, str]:
    """The card's own format as it says (spec, spec_version), for the drawer's footer ("Character Card V3 ...")."""
    card = characters.load(cid, ws)
    return {"spec": str(card.get("spec") or ""), "version": str(card.get("spec_version") or "")}


def read(cid: str, ws=None) -> List[Dict]:
    """Every setting of the character with its value, in FIELDS order."""
    card = characters.load(cid, ws)
    out = []
    for f in F.by_key().values():
        e = {k: f[k] for k in ("key", "tab", "type", "editable", "sensitive")}
        e["label"] = {"key": "charset." + f["key"], "vars": {}}
        e["file"] = _file_of(f, cid, ws).name   # a restore brings this whole file back (cs/D says so)
        e["folded"] = f["key"] in F.FOLDED
        e["value"] = _value(f, cid, card, ws)
        if f["key"] in F.OPTIONS:
            e["options"] = F.OPTIONS[f["key"]]
        if f["type"] == "roles":
            e["options"] = _roles_available(ws)
        if f["type"] == "brain":
            chain = characters.brains(card, f["where"])
            e["default"] = chain[0] if chain else None
        out.append(e)
    return out


def _check(f: Dict, v: Any, ws=None) -> Tuple[Optional[str], Any]:
    """(why it is refused, or None; the value as stored)."""
    t = f["type"]
    if t in ("text", "longtext"):
        if not isinstance(v, str):
            return "not text", None
        return ("too long", None) if len(v) > (MAX_TEXT if t == "text" else MAX_LONG) else (None, v)
    if t == "list":
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return "not a list of text", None
        return None, [x.strip() for x in v if x.strip()][:200]
    if t == "bool":
        return (None, v) if isinstance(v, bool) else ("not true/false", None)
    if t == "select":
        return (None, v) if v in F.OPTIONS.get(f["key"], []) else ("not one of the options", None)
    if t == "brain":
        if v is None:
            return None, None
        if not isinstance(v, dict) or not str(v.get("provider") or "").strip():
            return "a brain needs a provider", None
        return None, {"provider": str(v["provider"]).strip(), "model": str(v.get("model") or "").strip(),
                      "effort": str(v.get("effort") or "").strip()}
    if t == "focal":
        if v is None:
            return None, None
        try:
            x, y, zoom = (float(v[k]) for k in ("x", "y", "zoom"))
        except (TypeError, KeyError, ValueError):
            return "a face crop needs x, y and zoom", None
        if not (0 <= x <= 100 and 0 <= y <= 100 and 0.5 <= zoom <= 5):
            return "out of range", None
        return None, {"x": x, "y": y, "zoom": zoom, "master": str(v.get("master") or "")[:500]}
    if t == "roles":
        have = set(_roles_available(ws))
        if not isinstance(v, list) or not all(isinstance(x, str) and x in have for x in v):
            return "unknown role", None
        return None, list(dict.fromkeys(v))
    return "unknown type", None


def patch(cid: str, changes: Dict[str, Any], ws=None) -> Dict[str, Any]:
    """Merge `changes` into their files, each file read, changed and written once, its previous version kept first.
    A refused key is reported and left out; the others are written."""
    known, errors, ok = F.by_key(), {}, {}
    for k, v in (changes or {}).items():
        f = known.get(k)
        if f is None:
            errors[k] = "unknown setting"
        elif not f["editable"]:
            errors[k] = "read only"
        else:
            why, val = _check(f, v, ws)
            if why:
                errors[k] = why
            else:
                ok[k] = (f, val)
    by_file: Dict[Path, List[Tuple[Dict, Any]]] = {}
    for f, val in ok.values():
        by_file.setdefault(_file_of(f, cid, ws), []).append((f, val))
    for path, items_ in by_file.items():
        keep_version(cid, path, ws)
        src = items_[0][0]["source"]
        if src in ("card", "display", "ext"):
            card = characters.load(cid, ws)
            data = card.setdefault("data", {})
            chatbot = data.setdefault("extensions", {}).setdefault("chatbot", {})
            for f, val in items_:
                if f["source"] == "card":
                    data[f["where"]] = val
                elif f["source"] == "display":
                    chatbot.setdefault("display", {})[f["where"]] = val
                else:   # ext: a dotted path under extensions.chatbot
                    *parents, leaf = f["where"].split(".")
                    node = chatbot
                    for part in parents:
                        if not isinstance(node.get(part), dict):
                            node[part] = {}
                        node = node[part]
                    node[leaf] = val
            characters.save(cid, card, ws)
        elif src == "brain":
            for f, val in items_:
                characters.write_brain_override(cid, f["where"], val, ws)
        elif src == "team":
            team = characters.load_team(ws)
            team.setdefault("members", {})[cid] = items_[0][1]
            characters.save_team(team, ws)
        elif src == "state":
            st = items.read_state(cid, ws)
            for f, val in items_:
                st[f["where"]] = val
            items.write_state(cid, st, ws)
        else:
            _write_text(path, items_[0][1])
    if ok:
        try:
            from telemetry import obslog
            obslog.event("character.setting", character=cid, keys=sorted(ok))   # which keys, never the values
        except Exception:  # noqa: BLE001
            pass
    return {"changed": sorted(ok), "errors": errors}


def versions(cid: str, key: str, ws=None) -> List[Dict]:
    f = F.by_key().get(key)
    if f is None:
        raise KeyError(key)
    d, name = _backups(cid, _file_of(f, cid, ws), ws)
    return [{"version": p.name[len(name) + 1:], "bytes": p.stat().st_size}
            for p in sorted(d.glob(name + ".*"), reverse=True)] if d.is_dir() else []


def restore(cid: str, key: str, version: str, ws=None) -> None:
    """The setting's whole file back at `version` (the file as it is now is kept first, so a restore undoes too)."""
    f = F.by_key().get(key)
    if f is None:
        raise KeyError(key)
    path = _file_of(f, cid, ws)
    d, name = _backups(cid, path, ws)
    src = d / ("%s.%s" % (name, version))
    if not re.match(r"^[\w-]+$", version or "") or not src.is_file():
        raise KeyError(version)
    text = src.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        json.loads(text)   # a damaged backup is refused, not written
    keep_version(cid, path, ws)
    _write_text(path, text)


def api(method: str, path: str, body: Optional[dict]):
    m = _PATH.match(path or "")
    if not m:
        return None
    cid = m.group(1)
    try:
        if not characters.card_path(cid).exists():
            return 404, {"ok": False, "error": "no such character"}
    except ValueError:
        return 404, {"ok": False, "error": "no such character"}
    try:
        if m.group(2) and method == "GET":
            return 200, {"ok": True, "versions": versions(cid, m.group(3))}
        if m.group(4) and method == "POST":
            restore(cid, str((body or {}).get("key") or ""), str((body or {}).get("version") or ""))
            return 200, {"ok": True}
        if not m.group(2) and not m.group(4):
            if method == "GET":
                return 200, {"ok": True, "fields": read(cid), "card": card_format(cid)}
            if method == "PATCH":
                if not isinstance(body, dict):
                    return 400, {"ok": False, "error": "a JSON object of settings"}
                return 200, dict({"ok": True}, **patch(cid, body))
    except KeyError as e:
        return 404, {"ok": False, "error": "unknown %s" % e}
    return 405, {"ok": False, "error": "method not allowed"}
