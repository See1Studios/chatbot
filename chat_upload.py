"""Files a user attaches to a message (composer-plus-menu plus/C), kept out of server.py like card_upload.py:

  POST /api/sessions/<sid>/upload          raw body = the file; X-File-Name: its name (URI-encoded)
  POST /api/sessions/<sid>/upload/remove   JSON {"name": "<stored name>"}: the ✕ on a chip before sending

A file is saved in the session's own folder, sessions/<sid>/uploads/, and waits there as a pending attachment.
The next message of that session carries the list (take_pending, one line in the message route), so the page's
send path stays as it is and every provider reads the files with the file tools it already has. Pending lists live
in memory: a restart forgets which were not sent yet, the files stay.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import host_config

MAX_BYTES = 20 * 1024 * 1024        # D3: one file
MAX_PENDING = 1                     # one file per message (operator, 2026-09-28; was D3's 10)
PREFIX = "/api/sessions/"
_SID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
# The same names the file preview refuses (preview_guard._SECRET_NAME_RE): what would be refused on the way out
# is refused on the way in, so no secret ends up in a session folder by drag and drop.
_SECRET = re.compile(r"(?i)(^\.env($|\.)|oauth|token|secret|credential|passwd|password|api[_-]?key|auth\.json"
                     r"|^id_(rsa|dsa|ecdsa|ed25519)|_history$|\.(pem|key|p12|pfx)$|^\.git-credentials$|^\.netrc$)")

_pending: Dict[str, List[Dict]] = {}
_lock = threading.Lock()


def _sessions_dir() -> Path:
    return host_config.SESSIONS


def safe_name(raw: str) -> str:
    """A file name that is only a name: NFC, no path, no control or shell-unfriendly characters, at most 120."""
    name = unicodedata.normalize("NFC", unquote(raw or "")).replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip(". ")
    if len(name) > 120:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:110] + dot + ext[:9]) if dot and len(ext) <= 9 else name[:120]
    return name or "file"


def _human(n: int) -> str:
    return "%.1f MB" % (n / 1048576) if n >= 1048576 else "%.0f KB" % max(1, n / 1024)


def handle(path: str, headers, rfile) -> Optional[Tuple[int, Dict]]:
    """(HTTP status, JSON body) for the two upload routes; None for any other path."""
    if not path.startswith(PREFIX) or not (path.endswith("/upload") or path.endswith("/upload/remove")):
        return None
    removing = path.endswith("/upload/remove")
    sid = path[len(PREFIX):-len("/upload/remove" if removing else "/upload")]
    if not _SID.match(sid) or ".." in sid:
        return 400, {"ok": False, "error": "bad session id"}
    sess_dir = _sessions_dir() / sid
    if not sess_dir.is_dir():
        return 404, {"ok": False, "error": "no such session"}
    try:
        n = int(headers.get("Content-Length") or 0)
    except ValueError:
        return 400, {"ok": False, "error": "invalid Content-Length"}
    if removing:
        try:
            body = json.loads((rfile.read(n) if 0 < n <= 10_000 else b"{}").decode("utf-8") or "{}")
        except ValueError:
            return 400, {"ok": False, "error": "bad JSON"}
        return 200, {"ok": True, "removed": remove(sid, str(body.get("name") or ""))}
    raw_name = unquote(headers.get("X-File-Name") or "").replace("\\", "/").split("/")[-1].strip()
    name = safe_name(raw_name)
    if _SECRET.search(raw_name) or _SECRET.search(name):   # before cleaning too: ".env" must not pass as "env"
        return 400, {"ok": False, "error": "이 이름의 파일은 보안상 올릴 수 없습니다: %s" % name}   # l10n-ok
    if n <= 0:
        return 400, {"ok": False, "error": "empty file"}
    if n > MAX_BYTES:
        return 413, {"ok": False, "error": "파일이 너무 큽니다 (최대 %d MB)" % (MAX_BYTES // 1048576)}   # l10n-ok
    with _lock:
        if len(_pending.get(sid, [])) >= MAX_PENDING:
            return 400, {"ok": False, "error": "한 번에 %d개까지 첨부할 수 있습니다" % MAX_PENDING}   # l10n-ok
    data = rfile.read(n)
    up = sess_dir / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    stored = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), name)
    target = up / stored
    k = 1
    while target.exists():
        k += 1
        target = up / ("%s-%d-%s" % (time.strftime("%Y%m%d-%H%M%S"), k, name))
    target.write_bytes(data)
    item = {"name": target.name, "label": name, "path": str(target), "size": len(data),
            "size_human": _human(len(data)), "mime": (headers.get("Content-Type") or "application/octet-stream").split(";")[0]}
    with _lock:
        _pending.setdefault(sid, []).append(item)
    return 200, {"ok": True, "file": item}


def remove(sid: str, stored_name: str) -> bool:
    """Drop one pending attachment and its file. False when it is not pending (already sent, or never there)."""
    with _lock:
        items = _pending.get(sid, [])
        hit = next((x for x in items if x["name"] == stored_name), None)
        if hit is None:
            return False
        items.remove(hit)
    try:
        Path(hit["path"]).unlink()
    except OSError:
        pass
    return True


def attachment_block(items: List[Dict]) -> str:
    """What the agent reads after the message. Agent-facing, so English; the page shows it as cards."""
    lines = ["- %s (%s, %s)" % (x["path"], x["mime"], x["size_human"]) for x in items]
    return "[Attached files - read them with your file tools]\n" + "\n".join(lines)


def take_pending(sid: str, text: str) -> str:
    """The message text with this session's pending attachments appended; clears them. Unchanged without any."""
    with _lock:
        items = _pending.pop(sid, [])
    if not items:
        return text
    return (text.rstrip() + "\n\n" if text.strip() else "") + attachment_block(items)
