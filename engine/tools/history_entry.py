"""history_entry -- a merged delegation leaves its line in the work diary (HISTORY.md).

Why: in the review of #505-#525, 29 delegated changes had landed and not one was in the diary, so the next agent
starting from HISTORY.md (AGENTS.md "Start here") did not know they existed. A worker cannot write the diary itself:
parallel workers would all edit its top and collide when their branches land. So the runner writes it, on main,
after the merge, in the same commit as the ticket's record (tools/worktree_runner.py record_and_report).

The entry is mechanical -- the title, the commits, the files -- and says so; the why lives in the ticket and the
plan. When the diary passes its budget (tests/test_docs_budget.py), the oldest day moves to docs/history/<day>.md,
as an agent would do by hand.
"""
from __future__ import annotations

import datetime
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def _write(path: Path, text: str) -> None:
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:   # LF on every OS (test_platform_imports)
        f.write(text)

HISTORY = "HISTORY.md"
ROTATED = "docs/history"
BUDGET = 40 * 1024 - 2048          # under tests/test_docs_budget.py's 40KB, with room for the next hand-written entry
MAX_COMMITS = 8
MAX_FILES = 14
TICKET_FILES = re.compile(r"^data/workspace/skill-observations/tickets/")
DAY_HEAD = re.compile(r"(?m)^## (\d{4}-\d{2}-\d{2}) ")


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else ""


def entry(tid: int, title: str, provider: str, commits: List[str], files: List[str], day: str) -> str:
    lines = ["## %s — %s (#%d, 위임 %s)" % (day, title.strip() or "(제목 없음)", tid, provider), ""]   # l10n-ok
    if commits:
        shown = ", ".join("`%s` %s" % tuple(c.split(" ", 1)) if " " in c else "`%s`" % c for c in commits[:MAX_COMMITS])
        more = " 외 %d개" % (len(commits) - MAX_COMMITS) if len(commits) > MAX_COMMITS else ""   # l10n-ok
        lines.append("- **커밋**: %s%s" % (shown, more))   # l10n-ok
    if files:
        more = " 외 %d개" % (len(files) - MAX_FILES) if len(files) > MAX_FILES else ""   # l10n-ok
        lines.append("- **바뀐 파일**: %s%s" % (", ".join("`%s`" % f for f in files[:MAX_FILES]), more))   # l10n-ok
    lines.append("- 위임 병합 때 자동으로 쓴 줄(`tools/history_entry.py`). 이유와 결정은 티켓과 계획 문서에.")   # l10n-ok
    return "\n".join(lines) + "\n"


def insert(text: str, block: str) -> str:
    """The block goes above the newest entry, under the diary's own heading and notes."""
    m = re.search(r"(?m)^## ", text)
    if not m:
        return text.rstrip("\n") + "\n\n" + block
    return text[:m.start()] + block + "\n" + text[m.start():]


def rotate(repo: Path, text: str) -> Tuple[str, List[str]]:
    """While the diary is over budget, its oldest day moves to docs/history/<day>.md. Returns the diary and the files
    written beside it."""
    written: List[str] = []
    while len(text.encode("utf-8")) > BUDGET:
        days = DAY_HEAD.findall(text)
        if len(set(days)) < 2:
            break                                    # one day left: nothing older to move
        oldest = sorted(days)[0]
        first = re.search(r"(?m)^## %s " % re.escape(oldest), text).start()
        later = [m.start() for m in DAY_HEAD.finditer(text) if m.group(1) != oldest and m.start() > first]
        end = later[0] if later else len(text)
        moved, text = text[first:end], text[:first] + text[end:]
        rel = "%s/%s.md" % (ROTATED, oldest)
        path = repo / rel
        old = path.read_text(encoding="utf-8") if path.exists() else "# chatbot 개발로그 — %s\n\n" % oldest   # l10n-ok
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, old.rstrip("\n") + "\n\n" + moved.strip("\n") + "\n")
        note = "%s 기록은 하루 예산을 넘어 [docs/history/%s.md](docs/history/%s.md)로 회전했습니다." % (oldest, oldest, oldest)   # l10n-ok
        if note not in text:
            head = re.search(r"(?m)^## ", text)
            at = head.start() if head else len(text)
            text = text[:at].rstrip("\n") + "\n" + note + "\n\n" + text[at:]
        written.append(rel)
    return text, written


def record_merge(repo: Path, tid: int, title: str, provider: str, base: Optional[str], head: Optional[str],
                 day: Optional[str] = None) -> List[str]:
    """Write the entry for a landed ticket; returns the repo-relative files it wrote (to commit with the record)."""
    path = repo / HISTORY
    if not path.exists() or not head:
        return []
    span = "%s..%s" % (base, head) if base else head
    commits = [l for l in _git(repo, "log", "--format=%h %s", span if base else "-1", *([] if base else [head])).splitlines() if l]
    files = [f for f in _git(repo, "diff", "--name-only", span if base else head + "^!").splitlines()
             if f and not TICKET_FILES.match(f)]
    day = day or datetime.date.today().isoformat()
    text, rotated = rotate(repo, insert(path.read_text(encoding="utf-8"), entry(tid, title, provider, commits, files, day)))
    _write(path, text)
    return [HISTORY] + rotated
