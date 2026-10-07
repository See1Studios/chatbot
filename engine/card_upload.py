"""The PNG inside a character-card upload (#250; moved out of server.py, pew/N1c).

POST /api/characters/import sends either a multipart form or the raw PNG. png_from_body(content_type, body) returns
the PNG bytes: a part named *.png, typed image/png or starting with the PNG signature, else the first binary part;
for a raw body, only a body that is a PNG. None when there is nothing to import. handle() is the whole route for
server.py. Standard library only (plus tools.st_import when a card is actually imported).
"""
from __future__ import annotations

import email
import email.policy
from typing import Dict, Optional, Tuple

MAX_BYTES = 25 * 1024 * 1024
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_from_body(content_type: str, body: bytes) -> Optional[bytes]:
    ct = content_type or ""
    if "multipart/form-data" not in ct.lower():
        return body if body.startswith(PNG_SIG) else None
    hdr = f"Content-Type: {ct}\r\n\r\n".encode("utf-8")
    msg = email.message_from_bytes(hdr + body, policy=email.policy.default)
    if not msg.is_multipart():
        return msg.get_payload(decode=True) or None
    first_binary = None
    for part in msg.iter_parts():
        data = part.get_payload(decode=True)
        if not data:
            continue
        name = (part.get_filename() or "").lower()
        if name.endswith(".png") or (part.get_content_type() or "").lower() == "image/png" or data.startswith(PNG_SIG):
            return data
        if first_binary is None:
            first_binary = data
    return first_binary


def handle(headers, rfile, ws) -> Tuple[int, Dict]:
    """The whole POST /api/characters/import: (HTTP status, JSON body). Imports the card into workspace `ws`."""
    def fail(error: str, status: int = 400) -> Tuple[int, Dict]:
        return status, {"success": False, "ok": False, "error": error}
    try:
        try:
            n = int(headers.get("Content-Length") or 0)
        except ValueError:
            return fail("invalid Content-Length")
        if n <= 0:
            return fail("empty body")
        if n > MAX_BYTES:
            return fail("payload too large (max 25MB)", 413)
        png = png_from_body(headers.get("Content-Type") or "", rfile.read(n))
        if not png:
            return fail("No valid PNG file provided")
        from tools.st_import import import_st_png_bytes
        res = import_st_png_bytes(png, ws=ws)
        return 200, {"success": True, "ok": True, "character": {"id": res["id"], "name": res["name"], "path": res["path"]}}
    except Exception as e:  # noqa: BLE001
        return fail(str(e))
