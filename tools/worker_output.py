"""What a delegated worker's output says (split from worktree_runner, split/H): the report the PD reviews, the short
in-character line after the last `---`, and the LEARNED lessons kept in the expert's memory. Pure text; stdlib only.
"""
from __future__ import annotations

import re
from typing import List

LINE_RULE = ("At the very end of your final message, write a line containing only `---`, then one or two short "
             "sentences in character, spoken to your partner, about what you did.")

LEARNED_RULE = ("If you learned something worth remembering for future work here (about this project, the user's "
                "preferences, or how to work in this repository), put one short line starting with `LEARNED:` just "
                "before the `---` line. Skip it when there is nothing new.")
_LEARNED = re.compile(r"^\s*\**LEARNED\**\s*:\s*\**\s*(.+?)\s*$", re.I)
_SECRETISH = re.compile(r"(api[_-]?key|secret|password|passwd|token|bearer|sk-[A-Za-z0-9]{8,}|-----BEGIN)", re.I)


def learned(text: str) -> List[str]:
    """The LEARNED lessons in an agent's output: short, not secret-looking."""
    out = []
    for ln in (text or "").splitlines():
        m = _LEARNED.match(ln)
        if m and not _SECRETISH.search(m.group(1)):
            lesson = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
            if lesson and lesson not in out:
                out.append(lesson)
    return out


def said(text: str) -> str:
    """The in-character line after the last `---` of an agent's output (or its last lines); LEARNED lines left out."""
    lines = [ln for ln in (text or "").strip().splitlines() if not _LEARNED.match(ln)]
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).strip()[:500]
    return "\n".join(lines[-2:]).strip()[:500]


REPORT_LIMIT = 4000


def report(text: str, limit: int = REPORT_LIMIT) -> str:
    """The worker's final message before its last `---` line (the report the PD reviews), its end kept; LEARNED
    lines left out. said() is only the short in-character line after it."""
    lines = [ln for ln in (text or "").strip().splitlines() if not _LEARNED.match(ln)]
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            lines = lines[:i]
            break
    body = "\n".join(lines).strip()
    return body if len(body) <= limit else "…" + body[-limit:]
