"""What an agent's finished tool steps did, for the operator: the evidence behind a loop verdict, and writes to
repo files that no live ticket lease covers (NO_TICKET_WRITE_v1).

The charter asks for a claim before any disk change; the restart guard only looks later. A write the agent's own tool
steps show is stopped the moment it lands (director-handoff dir/B: a warning alone was ignored three times on
2026-10-04); a write is recognised by words in the tool name, the file by the usual argument keys.
TREE_WATCH_v1 (dir/B): a subagent's writes never show as tool steps (agy, codex) or show as the parent's (grok), so
every turn also compares the git working tree at its start and end. A file that changed in the turn, is tracked or
untracked-but-not-ignored and has no live lease is put on hold: the operator sees it, and every later work turn on
this host is told to revert it or get a ticket first, until the file is clean or leased. Provider-neutral.
Limit: a file someone else changes in the main tree during the turn is attributed to the turn.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from loop_guard import is_read_only, normalize, target_of

try:  # observing is best effort: a missing core module must never stop the host
    import evolution
    import tickets
except Exception:  # noqa: BLE001
    evolution = tickets = None


WRITE_TOOL_WORDS = ("write", "edit", "replace", "patch", "create_file", "delete", "rename", "move")


def loop_evidence(v, params: Optional[dict], output) -> dict:
    """What the repeated call actually asked and got, kept in the event log: without the arguments
    (line range) and the output's size/ends there is no telling a truncated read from a model habit."""
    try:
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(output)
    text = "" if output is None else text
    return {"rule": v.rule, "count": v.count, "tool": v.tool,
            "params": json.dumps(normalize(params), ensure_ascii=False, default=str)[:300],
            "output_chars": len(text), "output_head": text[:120], "output_tail": text[-120:] if len(text) > 120 else ""}


def written_path(tool: str, params: Optional[dict]) -> str:
    """The file a finished write step touched, or "" when the step is not a write."""
    name = (tool or "").lower()
    if is_read_only(name) or not any(w in name for w in WRITE_TOOL_WORDS):
        return ""
    p = params or {}
    return target_of(p) or str(p.get("file_path") or p.get("notebook_path") or "").strip()


def unleased_repo_file(path: str, root: Path, data: Path) -> str:
    """`path` repo-relative when it is a file git would track and no live lease covers it, else ""."""
    p = Path(path)
    if not p.is_absolute():
        p = data / "workspace" / p
    root = Path(root).resolve()
    try:
        rel = p.resolve().relative_to(root).as_posix()
    except ValueError:
        return ""
    ignored = subprocess.run(["git", "check-ignore", "-q", "--", rel], cwd=str(root),
                             capture_output=True, timeout=5).returncode
    if ignored != 1:  # 0 = ignored, 128 = no git here: nothing to govern
        return ""
    if tickets is None:
        return rel
    for lease in tickets.leases(data):
        for held in lease.get("paths") or [""]:
            h = held.rstrip("/")
            if not h or rel == h or rel.startswith(h + "/"):
                return ""
    return rel


def check(session, tool: str, params: Optional[dict], root: Path) -> None:
    """Stop the turn when a write lands on a repo file without a lease (once per file per session)."""
    path = written_path(tool, params)
    if not path:
        return
    try:
        rel = unleased_repo_file(path, root, session.meta_path.parent.parent.parent)
    except Exception:  # noqa: BLE001 -- observing must never disturb a turn
        return
    warned = session.__dict__.setdefault("_unticketed_warned", set())
    if not rel or rel in warned:
        return
    warned.add(rel)
    session._auto_stop(
        event={"event": "stopped", "text": f"⚠ 티켓 없이 {rel} 파일을 고쳐 턴을 멈췄습니다. 승인된 티켓을 claim한 뒤 작업해야 합니다.",
               "evidence": {"rule": "unticketed_write", "tool": tool, "path": rel}},
        hint=f"The last turn was stopped: it changed {rel}, a repo file no ticket covers. Revert that change, or ask "
             f"the operator for a ticket and claim it, before any other work; hand code work to the dev role.")
    if evolution is not None:
        evolution.record_candidate(session._observation_root(), "unticketed_write", session.sid, session.provider,
                                   {"path": rel, "tool": tool})


# ---- TREE_WATCH_v1 ----------------------------------------------------------------------------------------------
TREE_HOLD: Dict[str, str] = {}   # repo path -> the session whose turn changed it without a lease (this host process)


def tree_state(root: Path) -> Optional[Dict[str, tuple]]:
    """{repo path: (git status, mtime_ns, size)} for every changed or untracked (not ignored) file; None without git."""
    try:
        out = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=str(root),
                             capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    state, parts, i = {}, out.stdout.decode("utf-8", "replace").split("\0"), 0
    while i < len(parts):
        entry, i = parts[i], i + 1
        if len(entry) < 4:
            continue
        if entry[0] in "RC":   # a rename or copy names its source next: not a path of its own
            i += 1
        rel = entry[3:]
        try:
            st = (Path(root) / rel).stat()
            state[rel] = (entry[:2], st.st_mtime_ns, st.st_size)
        except OSError:
            state[rel] = (entry[:2], 0, -1)
    return state


def _data(session) -> Path:
    return session.meta_path.parent.parent.parent


def _held(rel: str, now: Dict[str, tuple], root: Path, data: Path) -> bool:
    return rel in now and bool(unleased_repo_file(str(Path(root) / rel), root, data))


def turn_start(session, root: Path) -> str:
    """Remember the tree; drop holds that are clean or leased now. Returns the hold line for the agent, or ""."""
    try:
        now = tree_state(root)
        session._tree_before = now
        if now is None:
            return ""
        for rel in [r for r in TREE_HOLD if not _held(r, now, root, _data(session))]:
            TREE_HOLD.pop(rel, None)
    except Exception:  # noqa: BLE001 -- watching must never disturb a turn
        return ""
    if not TREE_HOLD:
        return ""
    return ("On hold: repo files changed without a ticket: %s. Before any other work, revert them (git checkout -- "
            "<file>; delete a new file) or ask the operator for a ticket and claim it. Change nothing else."
            % ", ".join(sorted(TREE_HOLD)[:8]))


def turn_end(session, root: Path, outcome: str = "") -> List[str]:
    """Compare the tree with the turn's start; put new unleased changes on hold and tell the operator."""
    if outcome == "steer":   # the turn goes on with the added instruction: compare at its real end
        return []
    before = session.__dict__.pop("_tree_before", None)
    try:
        after = tree_state(root) if before is not None else None
        if after is None:
            return []
        data = _data(session)
        found = sorted(r for r, sig in after.items()
                       if before.get(r) != sig and r not in TREE_HOLD and _held(r, after, root, data))
    except Exception:  # noqa: BLE001
        return []
    if not found:
        return []
    for rel in found:
        TREE_HOLD[rel] = session.sid
    try:
        session._emit({"event": "system", "text": "⚠ 이번 턴에 티켓 없이 바뀐 파일: %s — 되돌리거나 티켓을 잡을 때까지 업무 턴마다 알립니다."  # l10n-ok
                       % ", ".join(found[:8]), "evidence": {"rule": "unticketed_tree_change", "paths": found}})
        if evolution is not None:
            evolution.record_candidate(session._observation_root(), "unticketed_write", session.sid, session.provider,
                                       {"path": ", ".join(found[:8]), "tool": "tree"})
    except Exception:  # noqa: BLE001
        pass
    return found
