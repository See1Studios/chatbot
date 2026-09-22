"""Long-term memory: the curated facts that outlive a session (data/workspace/memory/MEMORY.md).

Core module: standard library and `evolution`, every path derived from the `mem_dir` argument.
The command line (`tools/memory.py`) and the tool server both call these functions, so every
provider follows the same rules whether it has a shell or not.

Rules kept in one place:
- One fact per line, `- [YYYY-MM-DD] text`, under a `## Section` header. Section names come from the
  file itself, not from code; the first header is the default.
- Short on purpose: at most MAX_BYTES for the whole file, MAX_FACT_CHARS per fact.
- A date the caller already put in front of the fact is not doubled.
- Writes take a lock (the same lock file the older script used, so both can run side by side), replace
  the file atomically, and keep one previous generation as MEMORY.md.bak.
- `forget` refuses to remove more than one line unless told to: a broad word must not empty the file.
"""
from __future__ import annotations

import datetime
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import evolution

MEMORY_NAME = "MEMORY.md"
LOCK_NAME = ".MEMORY.lock"
BACKUP_NAME = "MEMORY.md.bak"
MAX_BYTES = 4096
MAX_FACT_CHARS = 300
MIN_QUERY_CHARS = 2
LOCK_WAIT_SEC = 5.0
_LEADING_DATE = re.compile(r"^\s*\[\d{4}-\d{2}-\d{2}\]\s*")

TEMPLATE = (
    "# 냥피디 장기 기억\n\n"
    "세션을 넘는 사실만 적는다. 나는 누구 → `PERSONA.md`. 호스트 법 → `~/AGENTS.md`.\n"
    "한 줄에 사실 하나. `[YYYY-MM-DD]` 날짜. 짧게 유지 (대략 4KB).\n\n"
    "## 실장님\n\n## 운영 결정\n\n## 진행 중\n"
)


class MemoryRefused(Exception):
    """A refusal the caller can show as is."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code  # 2: bad request, 3: file too big (the exit codes the command line has always used)


# ------------------------------------------------------------------ storage

def _file(mem_dir) -> Path:
    return Path(mem_dir) / MEMORY_NAME


def _ensure(mem_dir) -> None:
    d = Path(mem_dir)
    d.mkdir(parents=True, exist_ok=True)
    if not _file(d).exists():
        _file(d).write_text(TEMPLATE, encoding="utf-8")


def read(mem_dir) -> str:
    _ensure(mem_dir)
    return _file(mem_dir).read_text(encoding="utf-8")


class _Locked:
    def __init__(self, mem_dir):
        self.mem_dir = Path(mem_dir)
        self.fh = None

    def __enter__(self):
        _ensure(self.mem_dir)
        try:
            self.fh = evolution.acquire_lock(self.mem_dir / LOCK_NAME, LOCK_WAIT_SEC)
        except evolution.LockBusy:
            raise MemoryRefused("memory is being written by someone else; try again in a moment")
        return self

    def __exit__(self, *exc):
        if self.fh is not None:
            self.fh.close()


def _write(mem_dir, text: str) -> None:
    """Keep the current file as the one backup generation, then replace it atomically."""
    d = Path(mem_dir)
    data = text if text.endswith("\n") else text + "\n"
    current = _file(d).read_text(encoding="utf-8") if _file(d).exists() else None
    if current is not None:
        _atomic(d, BACKUP_NAME, current)
    _atomic(d, MEMORY_NAME, data)


def _atomic(d: Path, name: str, data: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".MEMORY.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(d / name))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ----------------------------------------------------------------- reading

def sections(text: str) -> List[str]:
    return [l[3:].strip() for l in text.splitlines() if l.startswith("## ")]


def search(mem_dir, query) -> List[Tuple[str, str]]:
    """(section, line) for every fact containing `query`, case-insensitively."""
    q = ("" if query is None else str(query)).strip().lower()
    if not q:
        raise MemoryRefused("검색어가 없습니다.")
    hits, section = [], ""
    for raw in read(mem_dir).splitlines():
        if raw.startswith("## "):
            section = raw[3:].strip()
        elif raw.startswith("- ") and q in raw.lower():
            hits.append((section, raw))
    return hits


# ----------------------------------------------------------------- writing

def _insert_line(body: str, section: str, line: str) -> str:
    header = "## %s" % section
    if header not in body:
        body = body.rstrip() + "\n\n%s\n" % header
    head, rest = body.split(header, 1)
    m = re.search(r"\n## ", rest)
    if m:
        return head + header + rest[:m.start()].rstrip() + "\n" + line + "\n" + rest[m.start():]
    return head + header + rest.rstrip() + "\n" + line + "\n"


def _clean_fact(fact) -> str:
    text = re.sub(r"\s+", " ", "" if fact is None else str(fact)).strip()
    text = re.sub(r"^-(?:\s+|$)", "", text)  # a list dash, not the minus of "-5도"
    while _LEADING_DATE.match(text):  # the line gets today's date from us, once
        text = _LEADING_DATE.sub("", text, count=1).strip()
    return text


def add(mem_dir, fact, section: Optional[str] = None, today: Optional[str] = None) -> Tuple[str, str, str]:
    """Add one fact. Returns (status, section, line) with status "added" or "duplicate"."""
    text = _clean_fact(fact)
    if not text:
        raise MemoryRefused("추가할 사실이 없습니다.")
    if len(text) > MAX_FACT_CHARS:
        raise MemoryRefused("사실이 너무 깁니다 (%d자 넘음). 한 줄로 줄여 주세요." % MAX_FACT_CHARS)
    line = "- [%s] %s" % (today or datetime.date.today().isoformat(), text)
    with _Locked(mem_dir):
        body = read(mem_dir)
        known = sections(body)
        target = (section or "").strip() or (known[0] if known else "")
        if not target or target not in known:
            raise MemoryRefused("--section 은 %s 중 하나." % ", ".join(known))
        if text.lower() in body.lower():
            return "duplicate", target, line
        new = _insert_line(body, target, line)
        if len(new.encode("utf-8")) > MAX_BYTES:
            raise MemoryRefused("MEMORY.md가 %d바이트를 넘습니다. 오래된 줄을 forget 한 뒤 다시 추가하세요." % MAX_BYTES, 3)
        _write(mem_dir, new)
    return "added", target, line


def forget(mem_dir, query, all_matches: bool = False) -> List[str]:
    """Remove the fact lines containing `query`. More than one match is refused unless `all_matches`."""
    q = ("" if query is None else str(query)).strip()
    if len(q) < MIN_QUERY_CHARS:
        raise MemoryRefused("삭제할 부분 문자열을 두 글자 이상 주세요.")
    qn = q.lower()
    with _Locked(mem_dir):
        body = read(mem_dir)
        kept, removed = [], []
        for raw in body.splitlines(keepends=True):
            line = raw.rstrip("\n")
            if line.startswith("- ") and qn in line.lower():
                removed.append(line)
            else:
                kept.append(raw)
        if not removed:
            return []
        if len(removed) > 1 and not all_matches:
            raise MemoryRefused("%d줄이 일치합니다. 하나만 지우려면 더 구체적으로 쓰고, 전부 지우려는 게 맞으면 all을 켜세요:\n%s"
                                % (len(removed), "\n".join(removed)))
        _write(mem_dir, "".join(kept))
    return removed
