"""Static file delivery: revalidation and compression (STATIC_DELIVERY_v1, 2026-09-28).

Measured on this install before the change: one full page load pulled 31 requests / 685 KB. Every
response carried `Cache-Control: no-cache` with no ETag and no Last-Modified, and nothing was
compressed even when the client offered gzip. So every reload re-downloaded every byte, and the
`?v=` cache-busting query strings in index.html could not do their job -- the browser had no way to
ask "did this change?" and had to take the whole file again.

Two changes, on text assets only (js/css/html):

  - a strong ETag from mtime + size, so a reload is a 304 with an empty body
  - gzip when the client accepts it, with `Vary: Accept-Encoding`

`Cache-Control` deliberately stays `no-cache`. The working habit here is "edit static/, hit
reload", and a long max-age would hide the edit. Revalidation gives the fast path without changing
that habit.

Images keep their own `max-age` and are never compressed: they are already compressed formats, so
gzip only costs CPU.

Pure functions with no server import, so the tests can exercise the rules directly.
"""
from __future__ import annotations

import gzip
import os
from pathlib import Path
from typing import Optional

# Types worth compressing. Images and fonts are left out on purpose.
COMPRESSIBLE = ("text/", "application/javascript", "application/json", "image/svg+xml")
# Below this, the gzip header and the CPU are worth more than the bytes saved.
MIN_COMPRESS_BYTES = 1024


def compressible(content_type: str) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    return any(ct == p or ct.startswith(p) for p in COMPRESSIBLE)


def negotiate(accept_encoding: Optional[str], content_type: str, size: int = 0) -> str:
    """Return "gzip" when the client takes it, the type is worth it and the body is big enough."""
    if size and size < MIN_COMPRESS_BYTES:
        return ""
    if not compressible(content_type):
        return ""
    if "gzip" not in (accept_encoding or "").lower():
        return ""
    return "gzip"


def compress(data: bytes) -> bytes:
    """gzip with mtime=0: the same input always yields the same bytes, so a response stays
    byte-identical across restarts and any future digest-based ETag is stable."""
    return gzip.compress(data, compresslevel=6, mtime=0)


def etag_for(path: os.PathLike) -> str:
    """Strong ETag from mtime + size.

    Deliberately not a content hash: 3 MB of vendored JS should not be read and hashed on every
    request, and for a file served straight off disk, mtime + size *is* its identity.
    """
    st = os.stat(path)
    mtime = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    return '"%x-%x"' % (int(mtime), st.st_size)


def if_none_match(header: Optional[str], etag: str) -> bool:
    """RFC 9110 If-None-Match: `*` matches any current entity, and a list may carry weak forms
    (`W/"..."`), which compare equal to their strong counterpart here."""
    if not header or not etag:
        return False
    want = etag.lstrip("W/").strip()
    for candidate in header.split(","):
        c = candidate.strip()
        if c == "*":
            return True
        if c.lstrip("W/").strip() == want:
            return True
    return False


CODE_EXT = (".js", ".css", ".html")


def fingerprint(folder: os.PathLike) -> str:
    """The page code's version (ASSET_RELOAD_v1): a short hash over the names, sizes and mtimes of the js/css/html
    files. An open page keeps the code it loaded across a host restart; when the restarted host reports a different
    fingerprint, the page reloads itself (static/app-api.js reloadIfAssetsChanged). Stats only, no reads."""
    import hashlib
    root = Path(folder)
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")):
        if p.suffix in CODE_EXT and p.is_file():
            st = p.stat()
            h.update(("%s:%d:%d\n" % (p.relative_to(root).as_posix(), st.st_size, int(st.st_mtime))).encode("utf-8"))
    return h.hexdigest()[:12]
