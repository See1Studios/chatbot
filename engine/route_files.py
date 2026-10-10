"""Files over HTTP (monolith-split split/B, moved from server.py): file preview and download, session artifacts,
persona pictures and the page's static files. Routes are listed in server.py's tables."""
from __future__ import annotations

import io
import mimetypes
import time
from urllib.parse import quote, unquote

from PIL import Image, ImageOps

import identity
import platform_compat
import static_delivery
import i18n
from host_config import DATA, HOME, STATIC, WEB_ROOT, WORKSPACE
from preview_guard import _resolve_safe_preview_file
from route_table import Req
from session import AgentSession, _safe_artifact_rel

MAX_USER_AVATAR_BYTES = 15 * 1024 * 1024

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
    if (not fp.exists() or not fp.is_file()) and rel.lower() == "favicon.ico":
        for fallback_name in ("face-icon.png", "face-icon.webp"):
            candidate = STATIC / fallback_name
            if candidate.exists() and candidate.is_file():
                fp = candidate
                break
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


# ------------------------------------------------------------ user profile and avatar
def user_avatar_path(ws: Optional[Path] = None) -> Path:
    return (ws or WORKSPACE) / "user_avatar.webp"


def user_md_path(ws: Optional[Path] = None) -> Path:
    return (ws or WORKSPACE) / "USER.md"


def user_info(req: Req):
    """GET /api/user: returns current user title, USER.md content, and avatar status."""
    md_file = user_md_path()
    av_file = user_avatar_path()

    user_title = identity.user_title()
    content = ""
    if md_file.is_file():
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""

    has_avatar = av_file.is_file()
    avatar_url = ""
    if has_avatar:
        try:
            avatar_url = f"/api/user/avatar?t={int(av_file.stat().st_mtime)}"
        except OSError:
            avatar_url = "/api/user/avatar"

    return req.json({
        "ok": True,
        "user_title": user_title,
        "user_md": content,
        "has_avatar": has_avatar,
        "avatar_url": avatar_url,
    })


def user_save(req: Req):
    """PUT /api/user: saves USER.md content."""
    body = req.body or {}
    content = body.get("user_md")
    if content is not None:
        md_file = user_md_path()
        try:
            platform_compat.write_text(md_file, str(content), encoding="utf-8")
        except OSError as e:
            return req.json({"ok": False, "error": f"failed to write USER.md: {e}"}, 500)

    return req.json({"ok": True})


def user_avatar_get(req: Req):
    """GET /api/user/avatar: serves user avatar."""
    av_file = user_avatar_path()
    if not av_file.is_file():
        return req.send(404, b"avatar not found", "text/plain")

    try:
        data = av_file.read_bytes()
        return req.send(200, data, "image/webp", cache_control="private, max-age=60")
    except OSError as e:
        return req.send(500, str(e).encode("utf-8"), "text/plain")


def user_avatar_upload(req: Req):
    """POST /api/user/avatar: streams image body, crops to square, saves as 512x512 WebP."""
    length = 0
    try:
        length = int(req.headers.get("Content-Length", 0))
    except (ValueError, TypeError):
        length = 0

    if length <= 0:
        return req.json({"ok": False, "error": "empty body"}, 400)
    if length > MAX_USER_AVATAR_BYTES:
        return req.json({"ok": False, "error": "file too large"}, 413)

    try:
        raw = req.rfile.read(length)
    except OSError as e:
        return req.json({"ok": False, "error": f"read failed: {e}"}, 400)

    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))
        img = img.resize((512, 512), Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")

        av_file = user_avatar_path()
        img.save(av_file, "WEBP", quality=90)
    except Exception as e:
        return req.json({"ok": False, "error": f"invalid image: {e}"}, 400)

    return req.json({
        "ok": True,
        "avatar_url": f"/api/user/avatar?t={int(time.time())}",
        "has_avatar": True,
    })


def user_avatar_delete(req: Req):
    """DELETE /api/user/avatar: removes user avatar."""
    av_file = user_avatar_path()
    if av_file.is_file():
        try:
            av_file.unlink()
        except OSError as e:
            return req.json({"ok": False, "error": f"failed to delete avatar: {e}"}, 500)

    return req.json({"ok": True, "has_avatar": False})
