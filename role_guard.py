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
from typing import Dict


def tool_refusal(name: str, args: Dict, edition_blocked: bool, *_unused) -> str:
    """Why an engine tool call may not run, or "": the edition boundary (a dev tool in the shipped build)."""
    return "%s is not available in this edition (shipped build)" % name if edition_blocked else ""


def live_scope(busy: list, grant: str, sessions_dir: Path) -> tuple:
    """(private, denied) of the sessions running a turn: a private one closes work tools (SESSION_SPLIT_v1), and so
    does a work turn marked personal (PERSONAL_TURN_v1); a work session whose character holds no role granting
    `grant` is denied it (TEAM_ROLES_v2); (False, False) if unknown."""
    import personal_turn
    closed = any(x.get("mode") == "private" or personal_turn.is_marked(sessions_dir, str(x.get("id") or ""), x.get("turn"))
                 for x in busy)
    return (closed, any(x.get("mode") != "private" and "tools" in x and grant not in x["tools"] for x in busy))
