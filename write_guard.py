"""What an agent's finished tool steps did, for the operator: the evidence behind a loop verdict, and writes to
repo files that no live ticket lease covers (NO_TICKET_WRITE_v1).

The charter asks for a claim before any disk change; the restart guard only looks later. This reports a skipped
claim the moment the write lands, as an on-screen warning and an observation candidate. It never blocks a turn.
Provider-neutral: a write is recognised by words in the tool name, the file by the usual argument keys.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

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
    """Warn once per file per session when a write lands on a repo file without a lease."""
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
    session._emit({"event": "system", "text": f"⚠ 티켓 없이 {rel} 파일을 고쳤습니다. 승인된 티켓을 claim한 뒤 작업해야 합니다냥.",
                   "evidence": {"rule": "unticketed_write", "tool": tool, "path": rel}})
    if evolution is not None:
        evolution.record_candidate(session._observation_root(), "unticketed_write", session.sid, session.provider,
                                   {"path": rel, "tool": tool})
