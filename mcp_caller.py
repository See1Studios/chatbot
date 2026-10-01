"""Which session made a tool call (docs/plans/unified-message-inbox.md inbox/0), for the tool server.

The host tells it from the connection: the process holding the client socket, walked up to an agent process the host
spawned (session.caller_session). The model never says who it is. An HTTP brain calls the tools from the host's own
process and names its session in HEADER, which the host trusts only on a connection from itself.

  serving(handler, tool, fn) -> fn() run with this call's connection known
  session_id(host_get, server_port) -> the calling session's id, "" when unknown (asked once per call, logged)
  screen_session(host_get) -> the session on screen: the guess the older tools made before inbox/0
  actor(host_get) -> the role id core tools record as who called (ACTOR_ATTRIBUTION_v1)
"""
from __future__ import annotations

import re
import threading
from urllib.parse import urlencode

import obslog

HEADER = "X-Chatbot-Session"
_CALL = threading.local()


def serving(handler, tool: str, fn):
    _CALL.conn = {"port": handler.client_address[1], "claim": str(handler.headers.get(HEADER) or "")[:80], "tool": tool}
    try:
        return fn()
    finally:
        _CALL.conn = None


def session_id(host_get, server_port: int) -> str:
    """An unknown caller is logged with its process's name (mcp.caller_unknown), so a provider that reaches the tools
    some other way shows up in the log."""
    c = getattr(_CALL, "conn", None)
    if not c:
        return ""
    if "sid" not in c:
        d = host_get("/api/sessions/caller?" + urlencode({"port": c["port"], "server": server_port, "claim": c["claim"]}))
        sid = str(d.get("id") or "")
        c["sid"] = sid if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", sid) else ""
        if not c["sid"]:
            obslog.event("mcp.caller_unknown", lvl="warn", tool=c["tool"], proc=str(d.get("proc") or "")[:40])
    return c["sid"]


def screen_session(host_get) -> str:
    sid = str(host_get("/api/sessions/active").get("id") or "")
    return sid if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", sid) else ""


def actor(host_get) -> str:
    """Who is calling the core tools (ACTOR_ATTRIBUTION_v1): the chat's live agent, as the role id
    "chat-agent:<provider of the session working right now>", or "chat-agent" when that cannot be told.
    Role ids only -- the persona's name is display, taken from identity by the page (NAME_NEUTRAL_v1)."""
    d = host_get("/api/sessions/active")
    return "chat-agent:%s" % str(d["provider"])[:20] if d.get("busy") and d.get("provider") else "chat-agent"
