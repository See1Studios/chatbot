"""CLIENT_ERRORS_v1 (#424): the page's uncaught errors reach the host log as `page.error`.

A refresh sometimes showed an empty chat: the page's session opening swallowed an error and made a new empty
session (fourteen of them on 2026-09-29), and nothing recorded what went wrong -- the page had no way to report.
Only the error's name, the first MAX_MSG characters of its message, where it happened and the top of its stack are
kept; never a message's text. Same-origin only (server.py routes it with the operator's other page calls).
"""
from __future__ import annotations

from typing import Optional, Tuple

import obslog

PATH = "/api/client-error"
MAX_MSG = 200
MAX_STACK = 600


def api(method: str, path: str, body) -> Optional[Tuple[int, dict]]:
    if method != "POST" or path != PATH:
        return None
    b = body if isinstance(body, dict) else {}
    obslog.event("page.error", lvl="warn", name=str(b.get("name") or "")[:60],
                 msg=str(b.get("message") or "")[:MAX_MSG], where=str(b.get("where") or "")[:200],
                 stack=str(b.get("stack") or "")[:MAX_STACK], context=str(b.get("context") or "")[:80])
    return 200, {"ok": True}
