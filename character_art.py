"""Character art routes (ART_PLACEHOLDER_v1), kept out of server.py like card_upload.py and emotion.py:

  GET /api/characters/<id>/avatar?provider=      the badge
  GET /api/characters/<id>/stage?provider=&name= the chat background (a place; name picks stage.<name>)
  GET /api/characters/<id>/sprites?framing=      JSON {"framing", "sprites": {label: "<framing>/<label>.webp"}}
  GET /api/characters/<id>/sprites/<[framing/]label>.webp?provider=   by name, falling back (ART_NAMES_v1)
  GET /api/items/<id>/image                       an item's picture (items.image_file)

Pictures never 404 for a known kind: a missing one is the engine placeholder (characters.art_file). Unknown kinds
or bad paths are not ours (None).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

import characters

PREFIX = "/api/characters/"


def handle(path: str, query: Dict[str, List[str]]) -> Optional[Tuple[int, bytes, str, str]]:
    """(status, body, content type, Cache-Control) for a character art path, or None when it is not one."""
    if path.startswith("/api/items/") and path.endswith("/image"):   # an item's picture, same fallback rule
        import items
        return _picture(*items.image_file(path[len("/api/items/"):-len("/image")]))
    if not path.startswith(PREFIX):
        return None
    parts = path[len(PREFIX):].split("/")
    if len(parts) < 2 or not characters.ID_RE.match(parts[0]):
        return None
    cid, kind, rest = parts[0], parts[1], parts[2:]
    q = lambda k: (query.get(k) or [""])[0]  # noqa: E731
    if kind in ("avatar", "stage") and not rest:
        return _picture(*characters.art_file(cid, kind, provider=q("provider"), label=q("name")))
    if kind == "sprites" and not rest:
        body = json.dumps(characters.sprite_map(cid, q("framing") or "full"), ensure_ascii=False).encode("utf-8")
        return 200, body, "application/json; charset=utf-8", "no-cache"
    if kind == "sprites" and 1 <= len(rest) <= 2 and rest[-1].endswith((".webp", ".png")):
        framing = rest[0] if len(rest) == 2 else (q("framing") or "full")
        label = rest[-1].rsplit(".", 1)[0]
        return _picture(*characters.art_file(cid, "sprite", provider=q("provider"), framing=framing, label=label))
    return None


def _picture(path, placeholder: bool) -> Tuple[int, bytes, str, str]:
    ctype = "image/webp" if path.suffix == ".webp" else "image/png"
    # a placeholder is cached briefly so the character's own picture shows soon after it is added
    return 200, path.read_bytes(), ctype, "private, max-age=%d" % (30 if placeholder else 300)
