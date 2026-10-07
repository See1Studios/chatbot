"""Files over HTTP (monolith-split split/B, moved from server.py): file preview and download, session artifacts,
persona pictures and the page's static files. Routes are listed in server.py's tables."""
from __future__ import annotations

import mimetypes
from urllib.parse import quote, unquote

import identity
import static_delivery
import i18n
from host_config import DATA, HOME, STATIC, WEB_ROOT
from preview_guard import _resolve_safe_preview_file
from route_table import Req
from session import AgentSession, _safe_artifact_rel

mimetypes.add_type("image/webp", ".webp")

_TEXT_SUFFIXES = (
    ".md", ".py", ".js", ".json", ".sh", ".css", ".html", ".txt", ".ts", ".jsx", ".tsx",
    ".yml", ".yaml", ".ini", ".conf", ".cfg", ".sql", ".xml", ".csv", ".log", ".env.example"
)


def artifacts_all(req: Req):
    sess = AgentSession("global")
    return req.json({"artifacts": sess.get_artifacts()})


def preview(req: Req):
    raw_target = req.q("path", "")
    fp, reason = _resolve_safe_preview_file(raw_target)
    if not fp:
        return req.json({"ok": False, **i18n.field("error", reason or 'preview.err.not_found')}, 404)
    ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
    stat = fp.stat()
    is_text = False
    content = None
    is_image = ctype.startswith("image/")
    raw_url = "/api/file/raw?path=" + quote(str(fp))
    if is_image:
        kind = "image"
    elif ctype.startswith("text/") or fp.suffix.lower() in _TEXT_SUFFIXES:
        kind = "text"
        is_text = True
        try:
            # preview up to 500KB text
            if stat.st_size <= 500_000:
                content = fp.read_text(encoding="utf-8", errors="replace")
            else:
                content = fp.read_text(encoding="utf-8", errors="replace")[:200_000] + f"\n\n... (the file is too large: {stat.st_size:,} bytes; only the first 200KB shown)"
        except Exception as e:
            content = f"cannot read the content: {e}"
    else:
        kind = "binary"

    rel_label = str(fp).replace(str(HOME), "~", 1)
    return req.json({
        "ok": True,
        "name": fp.name,
        "path": str(fp),
        "label": rel_label,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mime": ctype,
        "kind": kind,
        "is_text": is_text,
        "content": content,
        "raw_url": raw_url,
    })


def raw(req: Req):
    raw_target = req.q("path", "")
    fp, reason = _resolve_safe_preview_file(raw_target)
    if not fp:
        return req.send(404, (i18n.text(reason) if reason else "not found").encode("utf-8"), "text/plain; charset=utf-8")
    ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
    try:
        data = fp.read_bytes()
        return req.send(200, data, ctype, cache_control="private, max-age=60")
    except Exception as e:
        return req.send(500, str(e).encode("utf-8"), "text/plain")


def artifact(req: Req):
    fp = _safe_artifact_rel(req.arg)
    if not fp:
        return req.send(404, b"not found", "text/plain")
    data = fp.read_bytes()
    ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
    return req.send(200, data, ctype, cache_control="private, max-age=3600")


def persona(req: Req):
    # persona assets — stay inside DATA/persona (or the web-root fallback).
    # http.server does not collapse `..`; join+resolve without a root
    # check would read any file the process can open.
    path = req.path
    rel_p = path[len("/chat/persona/"):] if path.startswith("/chat/persona/") else path[len("/persona/"):]
    rel_p = unquote(rel_p or "")
    parts = rel_p.split("/")
    if (
        not rel_p
        or ".." in parts
        or rel_p.startswith(("/", "\\"))
        or any(part.startswith(".") for part in parts)
    ):
        return req.send(404, b"not found", "text/plain")
    persona_root = (DATA / "persona").resolve()
    fp_p = (DATA / "persona" / rel_p).resolve()
    try:
        fp_p.relative_to(persona_root)
    except ValueError:
        fp_p = None
    if fp_p is None or not fp_p.exists() or not fp_p.is_file():
        web_persona = (WEB_ROOT / "chat" / "persona").resolve()
        fp_p = (WEB_ROOT / "chat" / "persona" / rel_p).resolve()
        try:
            fp_p.relative_to(web_persona)
        except ValueError:
            return req.send(404, b"not found", "text/plain")
    if fp_p.exists() and fp_p.is_file():
        data = fp_p.read_bytes()
        ctype = mimetypes.guess_type(str(fp_p))[0] or "application/octet-stream"
        return req.send(200, data, ctype, cache_control="public, max-age=60")
    return req.send(404, b"not found", "text/plain")


def static(req: Req):
    path = req.path
    rel = "index.html" if path in ("/", "/chat", "/chat/") else path.lstrip("/")
    if ".." in rel:
        return req.send(400, b"bad path", "text/plain")
    fp = STATIC / rel
    if not fp.exists() or not fp.is_file():
        return req.send(404, b"not found", "text/plain")
    data = fp.read_bytes()
    ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
    etag = static_delivery.etag_for(fp)
    gz = static_delivery.negotiate(req.headers.get("Accept-Encoding"), ctype, len(data))
    if rel.endswith(".html") or rel == "index.html":
        ctype = "text/html; charset=utf-8"
        if rel == "index.html":
            # `<!--IDENTITY-->` -> the identity from this instance's instruction files.
            # Served statically (marker untouched) it is a harmless comment and app.js
            # falls back to /api/identity.
            data = data.replace(
                b"<!--IDENTITY-->",
                ("<script>window.__IDENTITY__=" + identity.script_json() + ";</script>").encode("utf-8"), 1)
        return req.send(200, data, ctype, cache_control="no-cache", etag=etag, encoding=gz)
    elif rel.endswith(".js"):
        ctype = "application/javascript; charset=utf-8"
        return req.send(200, data, ctype, cache_control="no-cache", etag=etag, encoding=gz)
    elif rel.endswith(".css"):
        ctype = "text/css; charset=utf-8"
        return req.send(200, data, ctype, cache_control="no-cache", etag=etag, encoding=gz)
    elif rel.lower().endswith((".png", ".webp", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2")):
        return req.send(200, data, ctype, cache_control="public, max-age=86400")
    return req.send(200, data, ctype)
