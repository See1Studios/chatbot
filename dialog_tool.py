"""The `dialog` tool (docs/plans/archive/2026/unified-message-inbox.md inbox/D, F): a character's messages with its coworkers in the
one office they share (D9) -- DMs, meeting rooms, and what it does at another's desk. Under it, Telegram's getDialogs,
getHistory and sendMessage as one tool, served by mcp_server.

  dialog {"action": "list"}                                     your dialogs: id, name, unread, mentions
  dialog {"action": "read", "dialog_id": "<id>", "limit": 20}   the latest messages; you have now read them
  dialog {"action": "send", "dialog_id": "<id>" | "to": "<character id, role or name>", "text": "...",
          "kind": "say" | "action", "reply_to": n}                  an action is a stage direction: done, not said
  dialog {"action": "handoff", "to": "<role or character>", "text": "<task>", "done_when": "..."}
                                                                work that is not your role's, to the director who owns
                                                                it (HANDOFF_v1, dialog_handoff); the result comes back
The argument is `dialog_id`: the name models reach for (live 2026-10-02, #554 -- `dialog` was missed four times).

Who sends is the session that called (mcp_caller, from the connection's process), never an argument, and the tool
refuses when that is unknown. A private session cannot use it: private talk must not travel into work dialogs, and work
dialogs stay out of private ones (private-security). There is no note or memo kind: a message is a message, an answer
is reply_to. Standard library + dialog_log; room_chat is imported so rooms are known in the tool server's process.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional
from urllib.parse import urlencode

import dialog_log
import room_chat  # noqa: F401 -- registers rooms as a kind of dialog

NAMES = ("dialog",)
READ_LIMIT = 20
READ_CHARS = 2000
MAX_TEXT = room_chat.MAX_TEXT
TOOL_DEFS = [{
    "name": "dialog",
    "description": "Your office messages with the other characters, your coworkers in the same office: DMs and "
                   "meeting rooms. list: your threads and what you have not read. read: the latest of one dialog_id "
                   "(marks it read; `how` says whether it came as a message or in person). send: message them (kind "
                   "say), or go over to their desk and do something in person (kind action: a stage direction such "
                   "as 'sets a coffee on Kit's desk', which they take as done to them) -- to a dialog_id, or to a "
                   "character by id/role/name with `to`; reply_to answers a message "
                   "number of that thread. dialog_id is an id exactly as list or the [Office] line gives it. "
                   "Write what you physically do between *asterisks* -- '*sets a coffee on Kit's desk* morning!' -- "
                   "and it arrives as an action followed by your words; a text wholly in (parentheses) is an action. "
                   "handoff: work that is not your role's goes to the director who owns it -- `to` a role (or a "
                   "coworker), `text` the task with what you know, `done_when` how they will know it is finished; "
                   "they work it at their own desk and the result comes back to you as a message. handoffs: the ones "
                   "you sent or received, newest first, with their state now (sent, running, waiting -- on work it handed on, done, failed, cancelled). "
                   "cancel: stop handoff number `handoff` that you sent or are working (`text` says why) -- when the user "
                   "calls it off or it is no longer needed; its turn stops and the work it handed on is cancelled too.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read", "send", "handoff", "handoffs", "cancel"]},
            "dialog_id": {"type": "string"},
            "to": {"type": "string"},
            "text": {"type": "string"},
            "kind": {"type": "string", "enum": ["say", "action"]},
            "reply_to": {"type": "integer"},
            "limit": {"type": "integer"},
            "done_when": {"type": "string"},
            "handoff": {"type": "integer"},
        },
        "required": ["action"],
    },
}]


def _character(ref: str) -> Optional[str]:
    import characters
    cid = characters.resolve(ref)
    if cid:
        return cid
    want = (ref or "").strip().lower()
    return next((c["id"] for c in characters.listing() if want and c["name"].strip().lower() == want), None)


def _view(m: Dict, did: str) -> Dict:
    import character_names
    out = {"n": m["n"], "from": dialog_log.speaker(m["who"]), "how": dialog_log.how(m, did),
           "text": character_names.as_of(str(m["text"]), m.get("ts"))[:READ_CHARS]}
    if m.get("reply_to"):
        out["reply_to"] = m["reply_to"]
    if m.get("kind") == "action":
        out["kind"] = "action"   # a stage direction: they did this
    return out


# Argument names models reach for instead of the schema's (live 2026-10-02: `dialog`, `character`, `target`,
# `message` -- each cost a refused call). The schema's own name wins when both are given.
ALIASES = {"to": ("target", "recipient", "character", "role"), "text": ("message", "content", "brief", "task", "reason"),
           "dialog_id": ("dialog",), "handoff": ("id", "handoff_id")}   # names models were seen using (drill 2026-10-05: brief)


def _canon(args: Dict) -> Dict:
    out = dict(args or {})
    for name, others in ALIASES.items():
        if not out.get(name):
            out[name] = next((out[o] for o in others if out.get(o)), out.get(name))
    return out


def call(args: Dict, envelope: Callable, who: Dict, host_get: Optional[Callable] = None) -> Dict:
    """`host_get`: how the tool server reaches the chat host; after a dm is sent the host is told, so both coworkers'
    windows show it now and the one it went to may react (inbox/E, G)."""
    me, sid = who.get("character") or "", who.get("id") or ""
    if not me or not sid:
        return envelope(False, "dialog: the calling session is unknown, so nothing can be sent or read as you", None)
    if who.get("private"):
        return envelope(False, "dialog: not in a private session -- private talk stays out of work dialogs", None)
    args = _canon(args)
    action = str(args.get("action") or "")
    if action == "list":
        rows = []
        for did in dialog_log.dialogs_of(me):
            n, mention = dialog_log.unread(me, did, sid)
            rows.append({"dialog_id": did, "name": dialog_log.label(did, me), "unread": n, "mentions": mention})
        return envelope(True, "%d dialogs" % len(rows), {"dialogs": rows})
    if action == "handoff":
        return _handoff(args, envelope, me, sid, host_get)
    if action == "cancel":   # HANDOFF_CANCEL_v1
        import dialog_handoff
        try:
            h = dialog_handoff.cancel(int(str(args.get("handoff") or 0).lstrip("#")), me, args.get("text") or "")
        except (dialog_handoff.HandoffError, TypeError, ValueError) as e:
            return envelope(False, "dialog: %s" % e, None)
        return envelope(True, "#%d will be cancelled within seconds: its turn stops, and what it handed on is cancelled "
                              "too" % h["id"], {"handoff": h["id"], "was": h.get("state")})
    if action == "handoffs":   # the ledger: what was handed, to whom, and how it stands now
        import dialog_handoff
        rows = dialog_handoff.ledger(me, max(1, min(int(args.get("limit") or 10), 30)))
        return envelope(True, "%d handoffs, newest first" % len(rows), {"handoffs": rows})
    did = str(args.get("dialog_id") or "")
    if not did and args.get("to") and action == "send":
        other = _character(str(args["to"]))
        if not other or other == me:
            return envelope(False, "dialog: no other character called %r" % args["to"], None)
        did = dialog_log.dm_id(me, other)
    if me not in dialog_log.members(did):
        why = "give dialog_id" if not did else "no dialog %r of yours" % did
        return envelope(False, "dialog: %s -- set dialog_id to an id exactly as action list returns it (dm:char_...:char_... or "
                               "room_...), or send with `to`" % why, None)
    if action == "read":
        limit = max(1, min(int(args.get("limit") or READ_LIMIT), READ_LIMIT))
        msgs = dialog_log.history(did)[-limit:]
        if msgs:
            dialog_log.saw(me, sid, did, msgs[-1]["n"])
        return envelope(True, "%d messages" % len(msgs), {"dialog_id": did, "messages": [_view(m, did) for m in msgs]})
    if action == "send":
        text = str(args.get("text") or "").strip()
        if not text:
            return envelope(False, "dialog: empty text", None)
        kind = str(args.get("kind") or "say")
        if kind not in dialog_log.KINDS:
            return envelope(False, "dialog: kind is say or action", None)
        members: List[str] = dialog_log.members(did)
        sent: List[int] = []
        try:
            reply = int(args["reply_to"]) if args.get("reply_to") not in (None, "") else None
            for i, (k, part) in enumerate(dialog_log.pieces(text[:MAX_TEXT], kind)):   # inbox/H: split by shape
                mentioned = room_chat.mentions(part, [m for m in members if m != dialog_log.USER]) \
                    if not dialog_log.is_dm(did) else []
                sent.append(dialog_log.append(did, me, part, mentioned, reply if i == 0 else None, k)["n"])
        except ValueError as e:
            if not sent:
                return envelope(False, "dialog: %s" % e, None)
        if not sent:
            return envelope(False, "dialog: empty text", None)
        dialog_log.saw(me, sid, did, sent[-1])
        for n in sent if host_get and dialog_log.is_dm(did) else []:
            host_get("/api/office/notify?" + urlencode({"dialog": did, "n": n}))   # a nudge; {} when unreachable
        return envelope(True, "sent", {"dialog_id": did, "n": sent[-1], "sent": sent})
    return envelope(False, "dialog: unknown action %r (list, read, send, handoff, handoffs, cancel)" % action, None)


def _owners() -> str:
    """The team's roles and what each owns (D-5), for a handoff that named no one."""
    import characters
    roles = sorted({r for c in characters.listing() for r in c.get("roles") or []})
    return "; ".join("%s (%s)" % (r, characters.role_pack(r).get("owns") or "-") for r in roles) or "no roles yet"


def _handoff(args: Dict, envelope: Callable, me: str, sid: str, host_get: Optional[Callable] = None) -> Dict:
    """HANDOFF_v1: record the handoff (dialog_handoff), leave the task in the two directors' dm -- shown in the receiver's
    work window now (the sender already shows its own turn, live 2026-10-05), without a reaction of its own (the handoff
    turn is the answer) -- and answer at once."""
    import characters
    import dialog_handoff
    ref = str(args.get("to") or "").strip()
    to = _character(ref) if ref else None
    if not to:
        return envelope(False, "dialog: handoff needs `to`, the role or coworker who owns the work: %s" % _owners(), None)
    role = ref if ref in characters.roles_of(to) else next(iter(characters.roles_of(to)), "")
    try:
        h = dialog_handoff.create(me, sid, to, role, args.get("text"), args.get("done_when"))
    except dialog_handoff.HandoffError as e:
        return envelope(False, "dialog: %s" % e, None)
    try:
        did = dialog_log.dm_id(me, to)
        m = dialog_log.append(did, me, "#%d %s%s" % (h["id"], h["task"], "\n-> " + h["done_when"] if h["done_when"] else ""),
                              announce=False)
        if host_get:
            host_get("/api/office/notify?" + urlencode({"dialog": did, "n": m["n"], "only": to}))   # receiver's window draws it
    except (ValueError, OSError):
        pass
    return envelope(True, "handed off as #%d to the %s director; they start when their desk is free, and the result "
                          "comes back to you as a message" % (h["id"], role or "other"), {"handoff": h["id"], "to_role": role})
