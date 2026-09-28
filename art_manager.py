"""Character art manager, the server half (docs/plans/character-art-manager.md am/B): a character's art slots and its
gallery, and the one way a picture gets into a slot.

  GET  /api/characters/<id>/art                  slots by kind (Character Card V3 names) + gallery + format problems
  GET  /api/characters/<id>/gallery/<file>       a gallery picture (served through character_art.handle)
  POST /api/characters/<id>/art/assign           JSON {"from": "<gallery file>", "kind", "name", "framing", "brain"}
  POST /api/characters/<id>/art/upload           raw image body, X-File-Name header -> into the gallery
  POST /api/characters/<id>/art/remove           JSON {"kind", "name", "framing", "brain"} -> back to the gallery

gallery/ is where candidates wait (character-resource-pipeline.md 2.1: an agent adds candidates there, never over an
approved picture). Putting one in a slot is the operator's approval: the picture is fitted to the kind's canvas,
saved as WebP under its size cap by the ART_NAMES_v1 name (characters.art_file reads the same names), and the original
kept as a PNG master beside it. What it replaces moves to _old/; removing a slot moves its picture back to the gallery.
Nothing is deleted.
"""
from __future__ import annotations

import io
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import characters

PREFIX = "/api/characters/"
KINDS = {"icon": "avatar", "background": "stage", "emotion": "sprite"}   # CCv3 asset type -> our art kind
EMOTION_SLOTS = ("neutral", "sadness", "joy", "love", "anger", "fear", "surprise")   # SillyTavern's 6 + neutral (SD1)
MAX_UPLOAD = 20 * 1024 * 1024
_GALLERY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(png|webp|jpe?g)$")
_IMAGE_EXT = (".png", ".webp", ".jpg", ".jpeg")


class ArtError(ValueError):
    pass


def _base(cid: str, ws=None) -> Path:
    return characters.card_path(cid, ws).parent


def _slot_path(cid: str, kind: str, name: str = "", framing: str = "bust", brain: str = "", ws=None) -> Path:
    """Where a slot's WebP lives, by the ART_NAMES_v1 names. ArtError for a kind or name that cannot be one."""
    base = _base(cid, ws)
    brain = (brain or "").strip().lower()
    if brain and not characters._SLUG.match(brain):
        raise ArtError("bad brain: %s" % brain)
    name = (name or "").strip().lower()
    if kind == "icon":
        return base / "avatar" / ("%s.webp" % brain) if brain else base / "avatar.webp"
    if kind == "background":
        if name in ("", "main", "stage"):
            return base / "stage.webp"
        if not characters._ART_NAME.match(name):
            raise ArtError("bad name: %s" % name)
        return base / ("stage.%s.webp" % name)
    if kind == "emotion":
        if framing not in characters.FRAMINGS:
            raise ArtError("bad framing: %s" % framing)
        if not (name and len(name) <= 64 and characters._ART_NAME.match(name)):
            raise ArtError("bad name: %s" % name)
        folder = base / "sprites" / framing / brain if brain else base / "sprites" / framing
        return folder / ("%s.webp" % name)
    raise ArtError("unknown kind: %s" % kind)


# ---------------------------------------------------------------------------------------------------- listing

def _url(cid: str, rel: str, path: Path) -> str:
    v = int(path.stat().st_mtime) if path.is_file() else 0
    return "/api/characters/%s/%s%sv=%d" % (cid, rel, "&" if "?" in rel else "?", v)


def _slot(cid: str, kind: str, name: str, framing: str = "bust", brain: str = "", ws=None) -> Dict:
    own = _slot_path(cid, kind, name, framing, brain, ws)
    art_kind = KINDS[kind]
    shown, placeholder = characters.art_file(cid, art_kind, provider=brain, framing=framing, label=name or "neutral", ws=ws)
    if kind == "icon":
        rel = "avatar" + ("?provider=" + brain if brain else "")
    elif kind == "background":
        rel = "stage" + ("?name=" + name if name and name != "main" else "")
    else:
        rel = "sprites/%s/%s.webp" % (framing, name) + ("?provider=" + brain if brain else "")
    base = _base(cid, ws)
    try:
        shows = str(shown.relative_to(base))
    except ValueError:
        shows = ""
    return {"kind": kind, "name": name or "main", "framing": framing if kind == "emotion" else "", "brain": brain,
            "own": own.is_file(), "placeholder": bool(placeholder), "shows": shows,
            "url": _url(cid, rel, shown)}


def listing(cid: str, ws=None) -> Dict:
    base = _base(cid, ws)
    icons = [_slot(cid, "icon", "", ws=ws)] + [
        _slot(cid, "icon", "", brain=p.stem, ws=ws) for p in sorted((base / "avatar").glob("*.webp"))
        if characters._SLUG.match(p.stem)]
    places = ["main"] + [p.name[len("stage."):-len(".webp")] for p in sorted(base.glob("stage.*.webp"))]
    backgrounds = [_slot(cid, "background", n, ws=ws) for n in places]
    emotions = {}
    for framing in characters.FRAMINGS:
        folder = base / "sprites" / framing
        names = list(EMOTION_SLOTS) + sorted(p.stem for p in folder.glob("*.webp") if p.stem not in EMOTION_SLOTS) \
            if folder.is_dir() else list(EMOTION_SLOTS)
        emotions[framing] = [_slot(cid, "emotion", n, framing, ws=ws) for n in names]
    gallery = []
    gdir = base / "gallery"
    if gdir.is_dir():
        for p in sorted(gdir.iterdir(), key=lambda x: -x.stat().st_mtime):
            if p.is_file() and _GALLERY_NAME.match(p.name):
                gallery.append({"file": p.name, "bytes": p.stat().st_size,
                                "url": _url(cid, "gallery/" + p.name, p)})
    return {"ok": True, "character": cid, "icon": icons, "background": backgrounds, "emotion": emotions,
            "gallery": gallery, "problems": characters.check_art(cid, ws=ws)}


def gallery_file(cid: str, name: str, ws=None) -> Optional[Path]:
    name = unquote(name or "")
    if not _GALLERY_NAME.match(name) or ".." in name:
        return None
    p = _base(cid, ws) / "gallery" / name
    return p if p.is_file() else None


# ---------------------------------------------------------------------------------------------------- writing

def _open(data: bytes):
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        return im
    except Exception:  # noqa: BLE001
        raise ArtError("not a picture")


def fit(im, kind: str, framing: str = "bust"):
    """The picture on the kind's canvas: icon and background are cropped to fill (centred), an expression is fitted
    whole onto a transparent canvas, feet or shoulders on the bottom edge, and must itself be transparent."""
    from PIL import Image, ImageOps
    if kind == "emotion":
        im = im.convert("RGBA")
        if im.getchannel("A").getextrema()[0] == 255:
            raise ArtError("an expression needs a transparent background")
        box = im.getchannel("A").getbbox() or (0, 0, im.width, im.height)   # the figure, not its clear margin
        im = im.crop(box)
        cw, ch = characters.FRAMINGS[framing][0]
        scale = min(cw / im.width, ch / im.height)
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas.paste(im, ((cw - im.width) // 2, ch - im.height), im)
        return canvas
    size = characters.ART_SIZE if kind == "icon" else characters.STAGE_SIZE
    return ImageOps.fit(im.convert("RGB"), size, Image.LANCZOS)


def _cap(kind: str, framing: str) -> int:
    if kind == "icon":
        return characters.ART_MAX_BYTES
    if kind == "background":
        return characters.STAGE_MAX_BYTES
    return characters.FRAMINGS[framing][1]


def webp(im, cap: int) -> bytes:
    """WebP under `cap` bytes: the best quality that fits. ArtError when even the lowest does not."""
    for q in (90, 84, 78, 72, 66, 60, 52, 44):
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=q, method=6)
        if buf.tell() <= cap:
            return buf.getvalue()
    raise ArtError("too detailed to fit under %d KB" % (cap // 1024))


def _retire(path: Path, base: Path) -> None:
    """Move a slot's picture (and its PNG master) to _old/, keeping where it was in its name."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for p in (path, path.with_suffix(".png")):
        if p.is_file():
            rel = str(p.relative_to(base)).replace("/", "__")
            dest = base / "_old" / ("%s-%s" % (stamp, rel))
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))


def assign(cid: str, source: str, kind: str, name: str = "", framing: str = "bust", brain: str = "", ws=None) -> Dict:
    """Put a gallery picture in a slot. Returns the slot as listed."""
    src = gallery_file(cid, source, ws)
    if src is None:
        raise ArtError("no such gallery picture: %s" % source)
    target = _slot_path(cid, kind, name, framing, brain, ws)
    im = _open(src.read_bytes())
    data = webp(fit(im, kind, framing), _cap(kind, framing))
    base = _base(cid, ws)
    _retire(target, base)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    im.save(target.with_suffix(".png"), "PNG")   # the master: the picture as chosen, before fitting
    return _slot(cid, kind, name, framing, brain, ws)


def remove(cid: str, kind: str, name: str = "", framing: str = "bust", brain: str = "", ws=None) -> Dict:
    """Take a slot's picture out -- back to the gallery as a candidate, its master to _old/."""
    target = _slot_path(cid, kind, name, framing, brain, ws)
    if not target.is_file():
        raise ArtError("that slot is empty")
    base = _base(cid, ws)
    dest = base / "gallery" / ("%s-%s.webp" % (time.strftime("%Y%m%d-%H%M%S"), target.stem))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(dest))
    _retire(target.with_suffix(".png"), base)
    return _slot(cid, kind, name, framing, brain, ws)


def upload(cid: str, filename: str, data: bytes, ws=None) -> Dict:
    """A picture from the page into the gallery, under a clean unique name."""
    if not data:
        raise ArtError("empty")
    if len(data) > MAX_UPLOAD:
        raise ArtError("too large")
    im = _open(data)
    fmt = (im.format or "").lower()
    ext = {"jpeg": "jpg", "png": "png", "webp": "webp"}.get(fmt)
    if not ext:
        raise ArtError("only PNG, WebP or JPEG")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(unquote(filename or "picture")).stem).strip("-")[:60] or "picture"
    gdir = _base(cid, ws) / "gallery"
    gdir.mkdir(parents=True, exist_ok=True)
    dest = gdir / ("%s.%s" % (stem, ext))
    if dest.exists():
        dest = gdir / ("%s-%s.%s" % (stem, time.strftime("%Y%m%d-%H%M%S"), ext))
    dest.write_bytes(data)
    return {"file": dest.name, "bytes": len(data), "url": _url(cid, "gallery/" + dest.name, dest)}


# ---------------------------------------------------------------------------------------------------- routes

def _cid(path: str, suffix: str) -> Optional[str]:
    if not (path.startswith(PREFIX) and path.endswith(suffix)):
        return None
    cid = path[len(PREFIX):-len(suffix)]
    return cid if characters.ID_RE.match(cid) and characters.card_path(cid).is_file() else None


def handle_get(path: str) -> Optional[Tuple[int, Dict]]:
    cid = _cid(path, "/art")
    return (200, listing(cid)) if cid else None


def handle_post(path: str, body: Dict) -> Optional[Tuple[int, Dict]]:
    body = body or {}
    for suffix, fn in (("/art/assign", "assign"), ("/art/remove", "remove")):
        cid = _cid(path, suffix)
        if not cid:
            continue
        args = {k: str(body.get(k) or "") for k in ("kind", "name", "framing", "brain")}
        args["framing"] = args["framing"] or "bust"
        try:
            slot = assign(cid, str(body.get("from") or ""), **args) if fn == "assign" else remove(cid, **args)
        except ArtError as e:
            return 400, {"ok": False, "error": str(e)}
        return 200, {"ok": True, "slot": slot}
    return None


def handle_upload(path: str, headers, rfile) -> Optional[Tuple[int, Dict]]:
    cid = _cid(path, "/art/upload")
    if not cid:
        return None
    try:
        length = int(headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length > MAX_UPLOAD:
        return 413, {"ok": False, "error": "too large"}
    try:
        return 200, {"ok": True, "file": upload(cid, headers.get("X-File-Name") or "", rfile.read(length))}
    except ArtError as e:
        return 400, {"ok": False, "error": str(e)}
