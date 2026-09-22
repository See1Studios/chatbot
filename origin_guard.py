"""Browser-origin checks for the HTTP API (pure functions, stdlib only).

The API has no login: it is reachable by every page the operator's browser
opens. Two questions decide what a foreign page may do:

- same_origin(): was this request made by a page served by this very server?
  Used for actions with side effects on the host.
- cors_allowed(): may a page from `origin` read our responses? Only pages on
  the same machine (same hostname, any port, e.g. the hub on another port).

Limits: `Origin` is set by browsers and can be forged by any non-browser
client, so this stops other websites and careless scripts, not a hostile
process on the LAN.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit


def _host_only(val: str) -> str:
    return (urlsplit(val if "//" in val else "//" + val).hostname or "").lower()


def same_origin(origin: Optional[str], host: Optional[str], sec_fetch_site: Optional[str] = None) -> bool:
    """True when the request comes from a page served at `host` itself.

    `Origin` wins when present. Without it, a browser's own
    `Sec-Fetch-Site: same-origin` is accepted; a client that sends neither
    (curl, scripts) is refused.
    """
    host = (host or "").strip().lower()
    if not host:
        return False
    if origin:
        try:
            return urlsplit(origin).netloc.lower() == host
        except ValueError:
            return False
    return (sec_fetch_site or "").strip().lower() == "same-origin"


def cors_allowed(origin: Optional[str], host: Optional[str]) -> bool:
    """True when a page at `origin` may read responses from `host`: same
    hostname, any port or scheme."""
    if not origin or not host:
        return False
    try:
        want = _host_only(host.strip())
        return bool(want) and _host_only(origin) == want
    except ValueError:
        return False
