"""MCP_ARGS_v1 (docs/plans/engine-decides.md ed/A1): a tool call's arguments in the shape the tool reads, before any
tool sees them. The names and forms here are the ones models reached for in refused calls (logs/events.jsonl,
2026-09-23..10-03: 325 of 1706 calls failed, nearly all on a name, a wrapper or a missing action).

Only names and shapes change, never what is asked. Driven by the tool's own schema: a key is renamed only onto a
key the schema has and the call left empty; an action is mapped or inferred only onto one the schema lists. An
operator-only step (approve, run, land, discard) is never mapped onto a tool action: it stays unknown and the tool
refuses it as before. Standard library only.
"""
from __future__ import annotations

import ast
import json
from typing import Any, Dict, List, Optional, Tuple

# Keys models use instead of the schema's: canonical -> others. Applied only when the tool's schema has the
# canonical key and the call did not fill it.
ALIASES = {
    "cmd": ("command",),
    "pattern": ("query", "regex", "search"),
    "body": ("content", "text", "description", "hypothesis", "detail"),   # before "text": an observation's
    "text": ("fact", "content", "message", "note"),                          # content is its body
    "title": ("name", "summary"),
    "instruction": ("description", "details", "task", "prompt"),
    "name": ("servicename", "service"),
    "path": ("file", "filepath", "file_path", "dir", "directory"),
}
# Action words that mean one of the tool's own actions, per tool.
SYNONYMS = {
    "memory": {"remember": "add", "save": "add", "find": "search", "list": "show", "read": "show",
               "delete": "forget", "remove": "forget"},
    "observation": {"create": "add", "new": "add", "show": "get", "read": "get"},
    "ticket": {"show": "get", "view": "get", "read": "get", "status": "list"},
    "wiki": {"read": "get", "show": "get", "find": "search", "list": "sources"},
    "dialog": {"get": "read", "open": "read", "post": "send", "message": "send"},
    "web": {"fetch": "read", "get": "read", "open": "read", "find": "search"},
    "skill": {"get": "load", "read": "load", "show": "load"},
    "delegate": {"list": "status", "show": "status"},
}
# When the action is missing: the first rule whose key the call filled gives it.
INFER = {
    "memory": (("text", "add"), ("query", "search"), ("", "show")),
    "observation": (("title", "add"), ("body", "add"), ("id", "get"), ("", "list")),
    "ticket": (("title", "propose"), ("id", "get"), ("", "list")),
    "wiki": (("query", "search"), ("id", "get"), ("", "sources")),
    "web": (("url", "read"), ("query", "search")),
    "dialog": (("text", "send"), ("dialog_id", "read"), ("", "list")),
    "skill": (("name", "load"), ("", "list")),
    "delegate": (("tasks", "plan"), ("", "status")),
}
_WRAPPER_KEYS = {"arguments", "toolname", "servername", "tool_name", "server_name"}


def _literal(text: str) -> Any:
    """A JSON or Python literal written as a string (a list, a dict), or None."""
    s = text.strip()
    if not s or s[0] not in "[{":
        return None
    for parse in (json.loads, ast.literal_eval):
        try:
            return parse(s)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
    return None


def _unwrap(args: Dict, actions: List[str], changes: List[str]) -> Dict:
    """A call some harnesses wrap once more: {"Arguments": "<dict as text>", "ToolName": ..., "ServerName": ...}."""
    keys = {k.lower(): k for k in args}
    if "arguments" not in keys or not set(keys) <= _WRAPPER_KEYS | set(k.lower() for k in ("servicename",)):
        return args
    inner = args[keys["arguments"]]
    rest = {k: v for k, v in args.items() if k.lower() not in _WRAPPER_KEYS}
    if isinstance(inner, str):
        parsed = _literal(inner)
        if isinstance(parsed, dict):
            inner = parsed
        elif inner.strip().lower() in actions:
            inner = {"action": inner.strip().lower()}
    if not isinstance(inner, dict):
        return args
    changes.append("unwrapped Arguments")
    return {**rest, **inner}


def _rename(args: Dict, props: Dict, changes: List[str]) -> Dict:
    out = {}
    for k, v in args.items():                       # Action -> action, ServiceName -> servicename
        low = k.lower()
        if low != k and (low in props or any(low in o for o in ALIASES.values())) and low not in args:
            changes.append("%s->%s" % (k, low))
            k = low
        out[k] = v
    for canon, others in ALIASES.items():
        if canon in props and out.get(canon) in (None, ""):
            got = next((o for o in others if o not in props and out.get(o) not in (None, "")), None)
            if got:
                out[canon] = out.pop(got)
                changes.append("%s->%s" % (got, canon))
    return out


def _shape(args: Dict, props: Dict, changes: List[str]) -> Dict:
    """Arrays and objects sent as text, and array items sent as text, become the values the schema describes."""
    out = dict(args)
    for k, spec in props.items():
        v, want = out.get(k), (spec or {}).get("type")
        if isinstance(v, str) and want in ("array", "object"):
            parsed = _literal(v)
            if isinstance(parsed, list if want == "array" else dict):
                out[k], v = parsed, parsed
                changes.append("%s parsed" % k)
            elif want == "array" and v.strip() and ((spec.get("items") or {}).get("type") == "string"):
                out[k], v = [p.strip() for p in v.split(",") if p.strip()], out[k]
                changes.append("%s split" % k)
        item = (spec or {}).get("items") or {}
        if isinstance(v, list) and item.get("type") == "object":
            items = [(_literal(x) if isinstance(x, str) else x) for x in v]
            if items != v and all(isinstance(x, dict) for x in items):
                changes.append("%s items parsed" % k)
            sub: List[str] = []
            items = [_rename(x, item.get("properties") or {}, sub) if isinstance(x, dict) else x for x in items]
            changes += ["%s: %s" % (k, c) for c in dict.fromkeys(sub)]
            if items != v:
                out[k] = items
    return out


def _action(name: str, args: Dict, actions: List[str], changes: List[str]) -> Dict:
    if not actions:
        return args
    raw = str(args.get("action") or "").strip()
    act = raw.lower()
    if act == name:                                  # {"action": "observation"} -- the tool's name, not an action
        act = ""
    act = SYNONYMS.get(name, {}).get(act, act)
    if not act:
        act = next((a for key, a in INFER.get(name, ()) if (not key or args.get(key) not in (None, "", []))
                    and a in actions), "")
    if act and act != raw and act in actions:
        changes.append("action %s->%s" % (raw or "(none)", act))
        return {**args, "action": act}
    return args


def normalize(name: str, args: Optional[Dict], schema: Optional[Dict]) -> Tuple[Dict, List[str]]:
    """(the arguments the tool should read, what was changed -- empty when nothing was)."""
    args = dict(args) if isinstance(args, dict) else {}
    props = ((schema or {}).get("inputSchema") or {}).get("properties") or {}
    if not props:
        return args, []
    actions = [str(a) for a in ((props.get("action") or {}).get("enum") or [])]
    changes: List[str] = []
    args = _unwrap(args, actions, changes)
    args = _rename(args, props, changes)
    args = _shape(args, props, changes)
    args = _action(name, args, actions, changes)
    return args, changes
