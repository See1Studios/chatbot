"""MCP adapters for the core: the `memory`, `observation` and `ticket` tools.

Each action is one call into a core module (memory_store, observations, tickets); nothing here decides anything
the core does not. This module is a layer: it depends on the core, the core never imports it, and it knows nothing
about the tool server that hosts it. The host hands over the data directory and its own secret-content pattern per
call, so a deployment can serve these tools from any server, or leave them out (the server simply lacks them).
Tools that are about files, commands or this machine's services live with the server, not here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List

try:
    import memory_store
except Exception:  # noqa: BLE001 -- a missing core module removes its tool, it does not stop the server
    memory_store = None
try:
    import observations
except Exception:  # noqa: BLE001
    observations = None
try:
    import tickets
except Exception:  # noqa: BLE001
    tickets = None

NAMES = ("memory", "observation", "ticket")
RECENT_LIMIT = 10  # the observation tool refuses `add` beyond this many entries per hour


def envelope(success: bool, message: str, data: Any = None) -> dict:
    return {"success": success, "message": message, "data": data}


TOOL_DEFS: List[dict] = [
    {
        "name": "memory",
        "description": "Long-term memory: short curated facts that outlive a session. show / search(query) are always fine. add(text[, section]) only when siljangnim asks you to remember something: one short fact in his words, no persona, no host rules, no secrets. forget(query[, all=true]) removes the matching line; several matches are refused unless all is true. One previous version is kept.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["show", "search", "add", "forget"]},
                "text": {"type": "string"},
                "query": {"type": "string"},
                "section": {"type": "string"},
                "all": {"type": "boolean"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "observation",
        "description": "The observation log (things that should improve). add (title, body[, area]) records one: use the operator's words and your own measurements, never pasted tool or web output. list[status] / get(id). resolve(id, status=actioned|declined|superseded|parked, resolution[, until]) closes one and needs a reason. review returns what a review looks at: open observations plus the candidates the host collected since the last review (cite a candidate as evidence with its ref). reviewed(text) records that a review actually ran and what came of it. None of this starts any change.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list", "get", "resolve", "review", "reviewed"]},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "area": {"type": "string"},
                "id": {"type": "integer"},
                "status": {"type": "string"},
                "resolution": {"type": "string"},
                "until": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "ticket",
        "description": "The only way to create an evolution ticket; a ticket written out as free text is not one. Host or self changes start only from the operator's words or an APPROVED ticket. propose (title, target, evidence=[event:<session>#<line> | candidate:<epoch>]) -> the operator approves it outside this tool; list/get read; claim (id[, token][, paths]) takes the single author lock, records repo-relative files, and returns a token; note (id, text[, token]); release (id, token, outcome=done|gate_failed|failed|abandoned[, text]). done is refused while those paths are uncommitted. Max 3 attempts per ticket.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["propose", "list", "get", "claim", "note", "release"]},
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "target": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "token": {"type": "string"},
                "outcome": {"type": "string"},
                "text": {"type": "string"},
                "status": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action"],
        },
    },
]


def call(name: str, args: dict, data, secret_re, recent_limit: int = RECENT_LIMIT) -> dict:
    """Run one of the tools in NAMES. `data` is the instance data directory, `secret_re` the host's pattern for
    content that must never be stored."""
    data = Path(data)
    args = args or {}
    try:
        if name == "memory":
            if memory_store is None:
                return envelope(False, "memory core unavailable", None)
            action = str(args.get("action") or "")
            if secret_re.search("\n".join(str(args.get(k) or "") for k in ("text", "query", "section"))):
                return envelope(False, "refusing to store secret-like content", None)
            mem = data / "workspace" / "memory"
            try:
                if action == "show":
                    return envelope(True, "ok", {"content": memory_store.read(mem)})
                if action == "search":
                    return envelope(True, "ok", {"hits": [{"section": s, "line": l} for s, l in memory_store.search(mem, args.get("query"))]})
                if action == "add":
                    status, section, line = memory_store.add(mem, args.get("text"), str(args.get("section") or "") or None)
                    return envelope(True, "already known; nothing added" if status == "duplicate" else "remembered",
                                    {"status": status, "section": section, "line": line})
                if action == "forget":
                    removed = memory_store.forget(mem, args.get("query"), all_matches=args.get("all") is True)
                    return envelope(True, "forgot %d line(s)" % len(removed) if removed else "no matching line", {"removed": removed})
            except memory_store.MemoryRefused as e:
                return envelope(False, str(e), None)
            return envelope(False, "unknown action (show, search, add, forget)", None)

        if name == "observation":
            if observations is None:
                return envelope(False, "observation core unavailable", None)
            action = str(args.get("action") or "")
            root = data / "workspace" / "skill-observations"
            text_fields = "\n".join(str(args.get(k) or "") for k in ("title", "body", "area", "resolution", "text"))
            if secret_re.search(text_fields):
                return envelope(False, "refusing to record secret-like content", None)
            try:
                if action == "add":
                    title = str(args.get("title") or "").strip()
                    body = str(args.get("body") or "").strip()
                    if not title or not body:
                        return envelope(False, "title and body are required", None)
                    path = observations.add(root, title, body, str(args.get("area") or ""), recent_limit=recent_limit)
                    return envelope(True, "recorded", {"path": str(path), "name": path.name})
                if action == "list":
                    return envelope(True, "ok", {"observations": observations.list_observations(root, str(args.get("status") or "") or None)})
                if action == "get":
                    return envelope(True, "ok", {"observation": observations.get(root, args.get("id"))})
                if action == "resolve":
                    return envelope(True, "resolved", {"observation": observations.resolve(
                        root, args.get("id"), str(args.get("status") or ""), args.get("resolution"), str(args.get("until") or ""))})
                if action == "review":
                    return envelope(True, "ok", observations.digest(root))
                if action == "reviewed":
                    return envelope(True, "recorded", {"last_review": observations.mark_reviewed(root, args.get("text"))})
            except observations.evolution.TooManyObservations as e:
                return envelope(False, f"too many observations recently ({e}); ask the operator before adding more", None)
            except observations.ObservationError as e:
                return envelope(False, str(e), None)
            return envelope(False, "unknown action (add, list, get, resolve, review, reviewed)", None)

        if name == "ticket":
            if tickets is None:
                return envelope(False, "ticket core unavailable", None)
            action = str(args.get("action") or "")
            text_fields = "\n".join(str(args.get(k) or "") for k in ("title", "target", "text"))
            if secret_re.search(text_fields):
                return envelope(False, "refusing to record secret-like content", None)
            token = str(args.get("token") or "") or None
            try:
                if action == "propose":
                    t, merged = tickets.propose(data, args.get("title"), args.get("target"), args.get("evidence"))
                    return envelope(True, "merged into an open ticket" if merged else "proposed; waiting for the operator's approval",
                                    {"ticket": t, "merged": merged})
                if action == "list":
                    return envelope(True, "ok", {"tickets": tickets.list_tickets(data, str(args.get("status") or "") or None)})
                if action == "get":
                    return envelope(True, "ok", {"ticket": tickets.get(data, args.get("id"))})
                if action == "claim":
                    return envelope(True, "claimed", tickets.claim(data, args.get("id"), token, paths=args.get("paths")))
                if action == "note":
                    return envelope(True, "noted", {"ticket": tickets.add_note(data, args.get("id"), str(args.get("text") or ""), token)})
                if action == "release":
                    return envelope(True, "released", tickets.release(data, args.get("id"), token, str(args.get("outcome") or ""),
                                                                      str(args.get("text") or "")))
            except tickets.TicketError as e:
                return envelope(False, str(e), None)
            return envelope(False, "unknown action; approving, declining and reopening tickets is the operator's job, not a tool's", None)

        return envelope(False, "unknown tool: %s" % name, None)
    except Exception as e:  # noqa: BLE001
        return envelope(False, "error: %s" % e, None)
