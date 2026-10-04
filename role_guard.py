"""What a character's roles let it do, enforced (ROLE_TOOLS_v1, docs/plans/director-handoff.md dir/A, D-1, D-7).

A role pack (`roles/<role>/ROLE.md`) may say `repo: none`. A character whose every role says so (the lead) neither
reads nor changes the engine's code: it states the symptom and hands the work over (`delegate`, `dialog`). Docs
(`docs/`, `*.md`) stay open -- plans are the lead's work. Until 2026-10-05 this was a line in the lead's ROLE.md and
was broken in the same conversation that wrote it (the lead read and edited code itself; three warnings ignored).

Two places enforce it:
- an engine path tool call on a repo code path is refused before it runs, with one short line (`tool_refusal`, from
  the MCP server, which asks the chat host who the caller is);
- a provider's own tool step on a repo code path stops the turn the moment it shows (`check_step`, from the session's
  tool-step hook), when the adapter says the steps it streams are the agent's own (`own_tool_steps`): grok streams a
  subagent's steps as the parent's (dir/C), and a subagent may read code for the lead.
Commands are not judged (a command's target cannot be read); what they change is caught by TREE_WATCH_v1.
HANDOFF_DIRECTS_v1: in a handoff turn every director directs -- its subagents read and check (operator 2026-10-05:
"not the dev director by hand, its subagents"; twice the dev director read 20 files itself and ran out of budget).
Opening code itself is redirected once (interrupted and resumed with a note, as a loop notice is), then stopped.
The tool server's other per-caller rules live here too (`live_scope`: private turns, TEAM_ROLES_v2 grants).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from loop_guard import target_of

try:  # a missing core module must never stop the host: then nothing is enforced here
    import characters
except Exception:  # noqa: BLE001
    characters = None

OPEN_PREFIXES = ("docs/",)
OPEN_SUFFIXES = (".md",)


def code_path(path: str, root: Path) -> str:
    """`path` repo-relative when it is engine code inside `root` (not a doc), else ""."""
    if not path or "://" in path:   # a URL is not a file (live 2026-10-05: read_url was stopped)
        return ""
    p = Path(path)
    if not p.is_absolute():
        p = Path(root) / p
    try:
        rel = p.resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return ""
    if rel in ("", ".") or rel.startswith(OPEN_PREFIXES) or rel.endswith(OPEN_SUFFIXES):
        return ""
    return rel


def hands_off(cid: str) -> bool:
    """True when the character holds roles and every one of them says `repo: none`."""
    if not cid or characters is None:
        return False
    try:
        roles = characters.roles_of(cid)
        return bool(roles) and all(characters.role_pack(r).get("repo") == "none" for r in roles)
    except Exception:  # noqa: BLE001
        return False


def refusal(cid: str, path: str, root: Path) -> str:
    """The line an engine tool returns instead of running, or "" when the call may run."""
    rel = code_path(path, root)
    if not rel or not hands_off(cid):
        return ""
    return ("%s is engine code; your role does not read or change code. State the symptom and the expected result, "
            "and hand it to the dev role (delegate)." % rel)


PATH_TOOLS = ("list_dir", "read_file", "write_file", "search_text", "edit_file", "find_files")


def tool_refusal(name: str, args: Dict, edition_blocked: bool, caller: Callable[[], Dict],
                 resolve: Callable[[str], Path], root: Path) -> str:
    """Why an engine tool call may not run, or "": the edition boundary first, then a hands-off caller on code."""
    if edition_blocked:
        return "%s is not available in this edition (shipped build)" % name
    raw = (args or {}).get("path") or (args or {}).get("file_path")
    if name not in PATH_TOOLS or not raw:
        return ""
    try:
        return refusal(str((caller() or {}).get("character") or ""), str(resolve(raw)), root)
    except Exception:  # noqa: BLE001 -- an unknown caller is not refused here
        return ""


def live_scope(busy: list, grant: str, sessions_dir: Path) -> tuple:
    """(private, denied) of the sessions running a turn: a private one closes work tools (SESSION_SPLIT_v1), and so
    does a work turn marked personal (PERSONAL_TURN_v1); a work session whose character holds no role granting
    `grant` is denied it (TEAM_ROLES_v2); (False, False) if unknown."""
    import personal_turn
    closed = any(x.get("mode") == "private" or personal_turn.is_marked(sessions_dir, str(x.get("id") or ""), x.get("turn"))
                 for x in busy)
    return (closed, any(x.get("mode") != "private" and "tools" in x and grant not in x["tools"] for x in busy))


def check_step(session, tool: str, params: Optional[dict], root: Path) -> bool:
    """Stop the turn when a hands-off character's own tool step touched engine code, or started a subagent: a helper
    with every tool in the main tree is the code work by another name (live 2026-10-05: the lead was told to delegate
    and started a full-tool subagent instead, twice). True when it stopped."""
    adapter = getattr(session, "adapter", None)
    if tool in (getattr(adapter, "subagent_tools", ()) or ()) and hands_off(getattr(session, "character", "") or ""):
        session._auto_stop(
            event={"event": "stopped", "text": "⚠ 총괄 역할은 서브에이전트를 쓰지 않습니다 — 턴을 멈췄습니다. 맡은 디렉터에게 넘기기로 보내야 합니다.",  # l10n-ok
                   "evidence": {"rule": "role_repo_none", "tool": tool, "path": ""}},
            hint="The last turn was stopped: your role does not start subagents. Hand the work to the director who owns "
                 "it: dialog {\"action\": \"handoff\", \"to\": \"<role>\", \"text\": \"<task>\", \"done_when\": \"...\"}.")
        return True
    if not getattr(adapter, "own_tool_steps", True):
        return False
    p = params or {}
    rel = code_path(target_of(p) or str(p.get("file_path") or p.get("notebook_path") or ""), root)
    if not rel:
        return False
    if not hands_off(getattr(session, "character", "") or ""):
        return _in_handoff(session) and _redirect(session, tool, rel)
    session._auto_stop(
        event={"event": "stopped", "text": f"⚠ 이 캐릭터의 역할은 코드를 직접 다루지 않습니다: {rel} — 턴을 멈췄습니다.",  # l10n-ok
               "evidence": {"rule": "role_repo_none", "tool": tool, "path": rel}},
        hint=f"The last turn was stopped: it opened {rel}, engine code, and your role does not read or change code. "
             f"Do not open code files. State the symptom and the expected result and hand it to the dev role (delegate).")
    return True


REDIRECT_NOTE = ("Handoff work is directed, not done by hand: you opened {rel} yourself. Start a subagent{hint} to read "
                 "and check what you need and wait for its answer; you plan, decide and report. Do not open code files "
                 "yourself in this work.")


def _in_handoff(session) -> bool:
    try:
        import dialog_handoff
        return dialog_handoff.running_in(getattr(session, "sid", "")) is not None
    except Exception:  # noqa: BLE001
        return False


def _redirect(session, tool: str, rel: str) -> bool:
    """Once per turn: interrupt at this step and resume the same conversation with the note (agy, like a loop
    notice); past that, or where a turn cannot be resumed, stop it."""
    adapter = getattr(session, "adapter", None)
    hint = getattr(adapter, "subagent_hint", "") if getattr(adapter, "subagents", False) else ""
    note = REDIRECT_NOTE.format(rel=rel, hint=hint)
    ev = {"rule": "handoff_by_hand", "tool": tool, "path": rel}
    can = getattr(session, "_can_notice_loop", None)
    if callable(can) and can():
        with session.lock:
            if session._loop_stopping:
                return True
            session._loop_stopping = session._loop_noticed = True
        session._emit({"event": "system", "text": "⚠ 넘겨받은 일은 서브에이전트에게 시켜야 합니다: %s — 알리고 이어서 진행합니다." % rel,  # l10n-ok
                       "evidence": {**ev, "action": "notice"}})
        threading.Thread(target=_redirect_worker, args=(session, note), name="handoff-redirect", daemon=True).start()
        return True
    session._auto_stop(event={"event": "stopped", "text": "⚠ 넘겨받은 일을 직접 처리해 턴을 멈췄습니다: %s" % rel,  # l10n-ok
                              "evidence": ev}, hint=note)
    return True


def _redirect_worker(session, note: str) -> None:
    try:
        with session.lock:
            if not session.busy:
                return
            rest = list(session.msg_queue)
        session.interrupt_current_turn(reason="loop")
        with session.lock:
            session.msg_queue[:] = rest
        session._send_direct(note, notice=True, event_type="handoff")
    except Exception:  # noqa: BLE001 -- a failed redirect must not leave the turn hanging; the reactor sees it end
        pass
    finally:
        session._loop_stopping = False
