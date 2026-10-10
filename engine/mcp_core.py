"""MCP adapters for the core: the `memory` and `ticket` tools.

Each action is one call into a core module (memory_store, tickets); nothing here decides anything
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
    import tickets
except Exception:  # noqa: BLE001
    tickets = None

NAMES = ("memory", "ticket")


def _charter_root(data: Path) -> Path:
    """Where memory lives. Same rule as host_config.charter_root; this module does not import the host."""
    data = Path(data)
    legacy = data / "workspace"
    if legacy.is_symlink() or not legacy.is_dir():
        return data
    if any(legacy.iterdir()):
        return legacy
    if (data / "AGENTS.md").exists() or (data / "roles").is_dir():
        return data
    return legacy


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
        "name": "ticket",
        "description": "The only way to create an evolution ticket; a ticket written out as free text is not one. Host or self changes start only from the operator's words or an APPROVED ticket. propose (title, target, evidence=[event:<session>#<line> | log:fp:<fp> | log:rid:<rid>] -- data only: the operator's message in this chat or what showed the problem is an event line, log refs come from `chatbot-ctl.sh logs`) -> the operator approves it outside this tool; list/get read; claim (id[, token][, paths]) takes the author lease on those repo-relative files (none named = every file; refused while another ticket holds any of them, or when the ticket is another agent's own) and returns a token; widen (id, token, paths) adds files to the ticket you hold (the same checks as a claim; the operator sees the scope grow in a note); note (id, text[, token]); release (id, token, outcome=done|gate_failed|failed|abandoned[, text]). done is refused while those paths are uncommitted. Max 3 attempts per ticket.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["propose", "list", "get", "claim", "widen", "note", "release"]},
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


PRIVATE_CLOSED = ("private session: work memory and tickets are closed here. Private talk is kept "
                  "apart, in this character's private memory, by the host.")


STAFF_MEMORY_CLOSED = ("the house memory is written only by a character whose role grants house-memory (the PD); "
                       "your own memory is kept by the host.")


LIST_RECENT = 20


def _ticket_list(data, status: str) -> dict:
    """`ticket list`: a status filters ("open" = not closed); none gives the open ones and the latest LIST_RECENT, not
    the whole store (live 2026-10-05: 652 tickets, 180 KB, read back from a spill file)."""
    if status:
        return envelope(True, "ok", {"tickets": tickets.list_tickets(data, status)})
    rows = tickets.list_tickets(data)
    shown = [r for r in rows if r.get("status") in tickets.OPEN_STATES]
    shown += [r for r in rows[-LIST_RECENT:] if r not in shown]
    return envelope(True, "%d tickets: the open ones and the latest %d (status=open|proposed|done|... for others)"
                    % (len(rows), LIST_RECENT), {"tickets": shown})

def _ticket(data, args: dict, secret_re, actor: str) -> dict:
    """The `ticket` tool: propose, list, get, claim, widen, note, release (approving is the operator's)."""
    if tickets is None:
        return envelope(False, "ticket core unavailable", None)
    action = str(args.get("action") or "")
    text_fields = "\n".join(str(args.get(k) or "") for k in ("title", "target", "text"))
    if secret_re.search(text_fields):
        return envelope(False, "refusing to record secret-like content", None)
    token = str(args.get("token") or "") or None
    try:
        if action == "propose":
            t, merged = tickets.propose(data, args.get("title"), args.get("target"), args.get("evidence"), actor=actor)
            return envelope(True, "merged into an open ticket" if merged else "proposed; waiting for the operator's approval",
                            {"ticket": t, "merged": merged})
        if action == "list":
            return _ticket_list(data, str(args.get("status") or ""))
        if action == "get":
            return envelope(True, "ok", {"ticket": tickets.get(data, args.get("id"))})
        if action == "claim":
            return envelope(True, "claimed", tickets.claim(data, args.get("id"), token, paths=args.get("paths"), actor=actor))
        if action == "widen":   # TICKET_WIDEN_v1 for the chat: no reason left to call tickets.widen from python
            return envelope(True, "widened", tickets.widen(data, args.get("id"), token, args.get("paths"), actor=actor))
        if action == "note":
            return envelope(True, "noted", {"ticket": tickets.add_note(data, args.get("id"), str(args.get("text") or ""), token,
                                                                       actor=actor)})
        if action == "release":
            return envelope(True, "released", tickets.release(data, args.get("id"), token, str(args.get("outcome") or ""),
                                                              str(args.get("text") or ""), actor=actor))
    except tickets.TicketError as e:
        return envelope(False, str(e), None)
    return envelope(False, "unknown action; approving, declining and reopening tickets is the operator's job, not a tool's", None)


def call(name: str, args: dict, data, secret_re, actor: str = "chat-agent",
         private: bool = False, staff: bool = False) -> dict:
    """Run one of the tools in NAMES. `data` is the instance data directory, `secret_re` the host's pattern for
    content that must never be stored."""
    data = Path(data)
    args = args or {}
    if private:   # PRIVATE_MEMORY_v1: a private session never reads or writes work memory or tickets
        return envelope(False, PRIVATE_CLOSED, None)
    if staff and name == "memory" and str((args or {}).get("action") or "") in ("add", "forget"):
        return envelope(False, STAFF_MEMORY_CLOSED, None)   # TEAM_ROLES_v2: everyone reads the house memory
    try:
        if name == "memory":
            if memory_store is None:
                return envelope(False, "memory core unavailable", None)
            action = str(args.get("action") or "")
            if secret_re.search("\n".join(str(args.get(k) or "") for k in ("text", "query", "section"))):
                return envelope(False, "refusing to store secret-like content", None)
            mem = _charter_root(data) / "memory"
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

        if name == "ticket":
            return _ticket(data, args, secret_re, actor)
        return envelope(False, "unknown tool: %s" % name, None)
    except Exception as e:  # noqa: BLE001
        return envelope(False, "error: %s" % e, None)
