"""The `dialog` tool (docs/plans/unified-message-inbox.md inbox/D, F): what a character says or does to another
off-screen, face to face in the lounge (D9) -- not a phone. Under it, Telegram's getDialogs, getHistory and sendMessage
as one tool, served by mcp_server.

  dialog {"action": "list"}                                     your dialogs: id, name, unread, mentions
  dialog {"action": "read", "dialog_id": "<id>", "limit": 20}   the latest messages; you have now read them
  dialog {"action": "send", "dialog_id": "<id>" | "to": "<character id, role or name>", "text": "...",
          "kind": "say" | "action", "reply_to": n}                  an action is a stage direction: done, not said
The argument is `dialog_id`: the name models reach for (live 2026-10-02, #554 -- `dialog` was missed four times).

Who sends is the session that called (mcp_caller, from the connection's process), never an argument, and the tool
refuses when that is unknown. A private session cannot use it: private talk must not travel into work dialogs, and work
dialogs stay out of private ones (private-security). There is no note or memo kind: a message is a message, an answer
is reply_to. Standard library + dialog_log; room_chat is imported so rooms are known in the tool server's process.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import dialog_log
import room_chat  # noqa: F401 -- registers rooms as a kind of dialog

NAMES = ("dialog",)
READ_LIMIT = 20
READ_CHARS = 2000
MAX_TEXT = room_chat.MAX_TEXT
TOOL_DEFS = [{
    "name": "dialog",
    "description": "Talk with the other characters off-screen, face to face in the lounge (not a phone). list: who "
                   "you talk with and what you have not heard yet. read: the latest of one dialog_id (now heard). "
                   "send: say something (kind say) or do something (kind action: a stage direction such as 'hands "
                   "Kit a coffee', which they take as done to them) to a dialog_id, or to a character by "
                   "id/role/name with `to`; reply_to answers a message number of that dialog. dialog_id is an id "
                   "exactly as list or the off-screen line gives it.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read", "send"]},
            "dialog_id": {"type": "string"},
            "to": {"type": "string"},
            "text": {"type": "string"},
            "kind": {"type": "string", "enum": ["say", "action"]},
            "reply_to": {"type": "integer"},
            "limit": {"type": "integer"},
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


def _view(m: Dict) -> Dict:
    out = {"n": m["n"], "from": dialog_log.speaker(m["who"]), "text": str(m["text"])[:READ_CHARS]}
    if m.get("reply_to"):
        out["reply_to"] = m["reply_to"]
    if m.get("kind") == "action":
        out["kind"] = "action"   # a stage direction: they did this
    return out


def call(args: Dict, envelope: Callable, who: Dict) -> Dict:
    me, sid = who.get("character") or "", who.get("id") or ""
    if not me or not sid:
        return envelope(False, "dialog: the calling session is unknown, so nothing can be sent or read as you", None)
    if who.get("private"):
        return envelope(False, "dialog: not in a private session -- private talk stays out of work dialogs", None)
    action = str(args.get("action") or "")
    if action == "list":
        rows = []
        for did in dialog_log.dialogs_of(me):
            n, mention = dialog_log.unread(me, did, sid)
            rows.append({"dialog_id": did, "name": dialog_log.label(did, me), "unread": n, "mentions": mention})
        return envelope(True, "%d dialogs" % len(rows), {"dialogs": rows})
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
        return envelope(True, "%d messages" % len(msgs), {"dialog_id": did, "messages": [_view(m) for m in msgs]})
    if action == "send":
        text = str(args.get("text") or "").strip()
        if not text:
            return envelope(False, "dialog: empty text", None)
        members: List[str] = dialog_log.members(did)
        mentioned = room_chat.mentions(text, [m for m in members if m != dialog_log.USER]) if not did.startswith("dm:") else []
        try:
            reply = int(args["reply_to"]) if args.get("reply_to") not in (None, "") else None
            msg = dialog_log.append(did, me, text[:MAX_TEXT], mentioned, reply, str(args.get("kind") or "say"))
        except ValueError as e:
            return envelope(False, "dialog: %s" % e, None)
        dialog_log.saw(me, sid, did, msg["n"])
        return envelope(True, "sent", {"dialog_id": did, "n": msg["n"]})
    return envelope(False, "dialog: unknown action %r (list, read, send)" % action, None)
