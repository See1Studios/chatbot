"""Which live caller may run an engine tool: the edition boundary and the tool server's per-caller scope.

A role makes a director better, not fenced (operator 2026-10-05: roles exist to give each character its own
instructions and skills so it does its work better). ROLE_TOOLS_v1 -- a `repo: none` role stopped on opening code,
refused subagents, redirected in handoff turns -- was turned off that day: it fenced roles instead of equipping
them, mistook a URL for code, and the lead grepped by command anyway. Roles carry instructions and skills
(`roles/<role>/ROLE.md` `skills:`); the guards that stay protect the system whoever acts: TREE_WATCH_v1
(write_guard.py), LIVE_DATA_GUARD_v1 (host_config.py), LIVE_AGENT_SUITE_v1 (run-tests.sh).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


def tool_refusal(name: str, args: Dict, edition_blocked: bool, *_unused) -> str:
    """Why an engine tool call may not run, or "": the edition boundary (a dev tool in the shipped build)."""
    return "%s is not available in this edition (shipped build)" % name if edition_blocked else ""


def live_scope(busy: list, grant: str, sessions_dir: Path, caller: Optional[Dict] = None) -> tuple:
    """(private, denied) of the sessions running a turn: a private one closes work tools (SESSION_SPLIT_v1), and so
    does a work turn marked personal (PERSONAL_TURN_v1); a work session whose character holds no role granting
    `grant` is denied it (TEAM_ROLES_v2); (False, False) if unknown.
    When `caller` is provided, evaluate only for that caller session to isolate across sessions."""
    import personal_turn
    if callable(caller):
        try:
            caller = caller()
        except Exception:
            caller = {}

    sid = str(caller.get("id") or "").strip() if isinstance(caller, dict) else str(caller or "").strip()
    if sid:
        target = next((x for x in (busy or []) if str(x.get("id") or "") == sid), None)
        mode = (target.get("mode") if target else None) or (caller.get("mode") if isinstance(caller, dict) else None)
        priv = bool((target.get("private") if target else False) or (caller.get("private") if isinstance(caller, dict) else False))
        if not mode and not priv:
            if sessions_dir:
                try:
                    import json
                    meta_p = Path(sessions_dir) / sid / "meta.json"
                    if meta_p.is_file():
                        meta = json.loads(meta_p.read_text(encoding="utf-8"))
                        mode = meta.get("mode")
                except Exception:
                    mode = None
            if not mode:
                # Mode cannot be resolved (busy lookup failed, caller lacked mode/private, and meta.json
                # was missing or corrupt). Fail-closed to prevent private sessions from executing work tools.
                return (True, False)

        closed = (mode == "private") or priv
        if not closed and sessions_dir:
            # Note: mcp_caller.caller only returns {id, character, mode, private}; it does not provide `turn`.
            # If busy lookup failed (busy=[]), `turn` is None unless caller dict explicitly supplied it.
            # In that case, is_marked() returns False (known limitation: fail-open for personal turns on busy outage).
            turn = (target.get("turn") if target else None) or (caller.get("turn") if isinstance(caller, dict) else None)
            personal_turn.await_judgment(sessions_dir, sid, turn)   # settle this turn before the mark is read
            closed = personal_turn.is_marked(sessions_dir, sid, turn)

        if closed:
            return (True, False)

        tools = None
        if target and "tools" in target:
            tools = target["tools"]
        elif isinstance(caller, dict) and "tools" in caller:
            tools = caller["tools"]
        elif (target and target.get("character")) or (isinstance(caller, dict) and caller.get("character")):
            cid = (target.get("character") if target else None) or (caller.get("character") if isinstance(caller, dict) else None)
            try:
                import characters
                tools = characters.tools_of(cid) if characters else None
            except Exception:
                tools = None
        # Note: mcp_caller.caller does not return `tools`. If busy lookup failed, tools is resolved via
        # characters.tools_of(cid). If character is missing or resolution fails, tools is None and denied is False
        # (known limitation: fail-open for role permissions when character cannot be resolved on busy outage).
        denied = bool(tools is not None and grant not in tools)
        return (False, denied)

    if isinstance(caller, dict) and (caller.get("mode") == "private" or bool(caller.get("private"))):
        return (True, False)

    for x in (busy or []):
        personal_turn.await_judgment(sessions_dir, str(x.get("id") or ""), x.get("turn"))
    closed = any(x.get("mode") == "private" or personal_turn.is_marked(sessions_dir, str(x.get("id") or ""), x.get("turn"))
                 for x in (busy or []))
    return (closed, any(x.get("mode") != "private" and "tools" in x and grant not in x["tools"] for x in (busy or [])))
