"""HTTP routing (monolith-split split/B). server.py keeps one ordered table per method; a route is (pattern, handler)
and the first route whose pattern matches and whose handler does not return NEXT answers the request.

Patterns: "/api/x" matches that path only; "/api/x/*/y" matches any path that starts with "/api/x/" and ends with
"/y" (the part between, slashes included, is `req.arg`); "/api/x/*" matches the prefix; a tuple matches when any
member does; None matches every path (a handler that answers only some paths returns NEXT for the rest).
Handlers take a Req and answer through it (`req.json`, `req.send`)."""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Optional, Tuple
from urllib.parse import parse_qs

JSON = "application/json; charset=utf-8"
NEXT = object()   # a handler's "not mine": try the next route


def json_bytes(obj: Any, code: int = 200):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return code, raw


class Req:
    """One request as the handlers see it: the normalized path, the query, the JSON body (POST/PUT), the handler."""

    def __init__(self, handler, path: str, query: str = "", body: Optional[dict] = None):
        self.h, self.path, self.query, self.body, self.arg = handler, path, query, body, ""

    @property
    def headers(self):
        return self.h.headers

    @property
    def rfile(self):
        return self.h.rfile

    def qs(self) -> dict:
        return parse_qs(self.query)

    def q(self, name: str, default: Any = "") -> Any:
        return parse_qs(self.query).get(name, [default])[0]

    def send(self, code: int, body: bytes, content_type: str, **kw) -> None:
        return self.h._send(code, body, content_type, **kw)

    def json(self, payload: Any, code: int = 200, **kw) -> None:
        code, raw = json_bytes(payload, code)
        return self.h._send(code, raw, JSON, **kw)


def match(pattern, path: str) -> Tuple[bool, str]:
    if pattern is None:
        return True, path
    if isinstance(pattern, tuple):
        for p in pattern:
            ok, arg = match(p, path)
            if ok:
                return ok, arg
        return False, ""
    if "*" not in pattern:
        return path == pattern, ""
    prefix, suffix = pattern.split("*", 1)
    if not (path.startswith(prefix) and path.endswith(suffix)):
        return False, ""
    return True, (path[len(prefix):-len(suffix)] if suffix else path[len(prefix):])


def dispatch(routes: Iterable[Tuple[Any, Callable]], req: Req) -> bool:
    """Run the first route that takes the request; False when none did."""
    for pattern, handler in routes:
        ok, arg = match(pattern, req.path)
        if ok:
            req.arg = arg
            if handler(req) is not NEXT:
                return True
    return False


# Adapters for the domain modules' own entry points, which each answer only their paths.

def api(fn: Callable, method: str) -> Callable:
    """fn(method, path, body) -> (status, payload) or None."""
    def handler(req: Req):
        r = fn(method, req.path, req.body)
        if r is None:
            return NEXT
        return req.json(r[1], r[0])
    return handler


def gift(fn: Callable) -> Callable:
    """fn(req) -> (status, payload) or a falsy value."""
    def handler(req: Req):
        r = fn(req)
        if not r:
            return NEXT
        return req.json(r[1], r[0])
    return handler


def first(*handlers: Callable) -> Callable:
    """The handlers in order, as one route: the first that takes the request answers it."""
    def handler(req: Req):
        for h in handlers:
            if h(req) is not NEXT:
                return None
        return NEXT
    return handler
