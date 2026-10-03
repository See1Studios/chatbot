"""Homecoming / unsummon REST (sp/N).

Not a delete. Confirm once, speak one farewell line, pack the character folder
and that character private dialog logs (dialogs/ files whose names contain the
character id) into a zip under data/archive/characters/, verify the zip, append
one manifest line for later recall, then move the live character folder and
those dialog files into the archive tree. Never packs rooms/, sessions/, or
sqlite. Paths never come from the request. Tests use fixtures only.
"""
from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import characters

STEPS_PATH = Path(__file__).resolve().parent / "engine_data" / "unsummon_steps.json"


def public_spec() -> Dict[str, Any]:
    return json.loads(STEPS_PATH.read_text(encoding="utf-8"))


def _fill(template: str, **parts: str) -> str:
    text = template or ""
    for key, val in parts.items():
        text = text.replace("{" + key + "}", val)
    return text


def _has_card(cid: str, ws: Any) -> bool:
    try:
        return bool(cid) and characters.card_path(cid, ws).is_file()
    except ValueError:
        return False


def _workspace(ws: Any) -> Path:
    if ws is None:
        return Path(characters._default_ws())
    return Path(ws)


def _archive_root(ws: Any) -> Path:
    return _workspace(ws).resolve().parent / "archive" / "characters"


def _manifest_path(ws: Any) -> Path:
    return _archive_root(ws) / "manifest.jsonl"


def _dialogs_root(dialogs: Any, ws: Any) -> Path:
    if dialogs is not None:
        return Path(dialogs)
    try:
        import dialog_log
        return Path(dialog_log._dir())
    except Exception:
        return _workspace(ws).resolve().parent / "dialogs"


def dialog_files_for(cid: str, dialogs_root: Path) -> List[Path]:
    """Private dialog logs under dialogs/ whose file names contain cid. No sqlite."""
    if not dialogs_root.is_dir():
        return []
    out = []
    for child in sorted(dialogs_root.iterdir()):
        if not child.is_file():
            continue
        name = child.name
        if name.startswith("."):
            continue
        if name.endswith((".sqlite", ".sqlite3", ".db")):
            continue
        if cid in name:
            out.append(child)
    return out


def _add_tree(zf: zipfile.ZipFile, src: Path, arc_prefix: str) -> int:
    n = 0
    for path in sorted(src.rglob("*")):
        if path.is_file():
            zf.write(path, arc_prefix + "/" + path.relative_to(src).as_posix())
            n += 1
    return n


def pack_character(cid: str, ws: Any, dialogs: Any = None) -> Tuple[Path, Path, List[Path]]:
    """Write zip from copies. Returns (zip path, side folder path, dialog files to move)."""
    src = characters.characters_dir(ws) / cid
    if not src.is_dir():
        raise FileNotFoundError("no such character")
    dest_root = _archive_root(ws)
    dest_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d%H%M%S")
    base = "%s.%s" % (cid, stamp)
    if (dest_root / (base + ".zip")).exists():
        base = "%s.%s.%d" % (cid, stamp, int(time.time() * 1000) % 1000)
    zip_path = dest_root / (base + ".zip")
    side = dest_root / base
    droot = _dialogs_root(dialogs, ws)
    dfiles = dialog_files_for(cid, droot)
    files = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        files += _add_tree(zf, src, "character")
        for df in dfiles:
            zf.write(df, "dialogs/" + df.name)
            files += 1
        zf.writestr("meta.json", json.dumps({
            "id": cid,
            "archived": True,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dialogs": [df.name for df in dfiles],
            "files": files,
        }, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if "character/card.json" not in names and not any(n.endswith("/card.json") for n in names):
            zip_path.unlink(missing_ok=True)
            raise OSError("archive missing card.json")
        bad = zf.testzip()
        if bad is not None:
            zip_path.unlink(missing_ok=True)
            raise OSError("archive corrupt: %s" % bad)
    return zip_path, side, dfiles


def append_manifest(ws: Any, cid: str, name: str, archive: Path, dialogs: List[str]) -> None:
    root = _archive_root(ws)
    root.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "id": cid,
        "name": name,
        "archived": True,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "path": archive.name,
        "dialogs": dialogs,
    }, ensure_ascii=False)
    with _manifest_path(ws).open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def move_into_archive(cid: str, ws: Any, side: Path, dfiles: List[Path]) -> None:
    """After the zip is verified: move live character + dialog files into the archive folder."""
    src = characters.characters_dir(ws) / cid
    side.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.move(str(src), str(side / "character"))
    if dfiles:
        ddest = side / "dialogs"
        ddest.mkdir(parents=True, exist_ok=True)
        for df in dfiles:
            if df.is_file():
                shutil.move(str(df), str(ddest / df.name))


def roster_drop(cid: str, ws: Any) -> Optional[str]:
    team = characters.load_team(ws)
    members = dict(team["members"])
    members.pop(cid, None)
    default = team["default"]
    if default == cid or not _has_card(default, ws):
        default = next((m for m in members if _has_card(m, ws)), "")
    characters.save_team({"default": default, "members": members}, ws)
    return default or None


def farewell_text(name: str, spec: Optional[Dict[str, Any]] = None) -> str:
    spec = spec or public_spec()
    return _fill(str(spec.get("farewell") or "{name}"),
                 name=name, hook=str(spec.get("hook_default") or ""))


def undo_text(archive: Path, spec: Optional[Dict[str, Any]] = None) -> str:
    spec = spec or public_spec()
    return _fill(str(spec.get("undo") or "{archive}"), archive=str(archive))


def unsummon(cid: str, body: Any, ws: Any = None, dialogs: Any = None) -> Tuple[int, Dict[str, Any]]:
    if not isinstance(body, dict):
        return 400, {"ok": False, "error": "json object required"}
    if not characters.ID_RE.match(cid or ""):
        return 400, {"ok": False, "error": "character required"}
    if not body.get("confirm"):
        return 400, {"ok": False, "error": "confirm required"}
    try:
        card = characters.load(cid, ws)
    except (OSError, ValueError):
        return 404, {"ok": False, "error": "no such character"}
    name = characters.name(card, ws) or cid
    team = characters.load_team(ws)
    others = [m for m in team["members"] if m != cid and _has_card(m, ws)]
    if not others and cid in team["members"]:
        others = [d.name for d in characters.characters_dir(ws).iterdir()
                  if d.is_dir() and d.name != cid and characters.ID_RE.match(d.name)
                  and (d / "card.json").is_file()]
    if not others:
        return 409, {"ok": False, "error": "last character"}
    try:
        archive, side, dfiles = pack_character(cid, ws, dialogs=dialogs)
    except FileNotFoundError:
        return 404, {"ok": False, "error": "no such character"}
    except OSError as exc:
        return 500, {"ok": False, "error": "archive failed: %s" % exc}
    append_manifest(ws, cid, name, archive, [df.name for df in dfiles])
    move_into_archive(cid, ws, side, dfiles)
    new_default = roster_drop(cid, ws)
    spec = public_spec()
    return 200, {
        "ok": True,
        "id": cid,
        "name": name,
        "farewell": farewell_text(name, spec),
        "undo": undo_text(archive, spec),
        "archive": str(archive),
        "default": new_default,
    }


def handle_unsummon(cid: str, body: Any, ws: Any = None) -> Tuple[int, Dict[str, Any]]:
    return unsummon(cid, body, ws)
