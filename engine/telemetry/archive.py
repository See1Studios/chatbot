"""Event log archive (docs/plans/telemetry.md tl/B, D1): the log's history is kept, compressed, for KEEP_DAYS.

obslog rotates `events.jsonl` by size and keeps BACKUPS numbered files; the one that falls off the end used to be
overwritten. It now moves here (`stash`, a rename on the same disk: the writer is never held up), and the long
running processes' background thread calls `maintain` about once an hour: gzip what was stashed, then drop what is
older than KEEP_DAYS or over MAX_BYTES, oldest first. One resolver for the folder (`dir_for`), next to the log it
belongs to, so a test's log never archives into the install's.

  dir_for(log_path)   <log folder>/archive
  stash(path, log_path)
  maintain(log_path, now=None) -> {"compressed", "pruned", "kept", "bytes"} or {"busy": True}
  files(log_path)     archived files, oldest first (gz and not yet compressed)
"""
from __future__ import annotations

import gzip
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

import platform_compat

KEEP_DAYS = int(os.environ.get("CHATBOT_OBSLOG_KEEP_DAYS", "90"))
MAX_BYTES = int(os.environ.get("CHATBOT_OBSLOG_ARCHIVE_MAX_BYTES", str(1024 * 1024 * 1024)))
PREFIX = "events-"


def dir_for(log_path) -> Path:
    return Path(log_path).parent / "archive"


def stash(path: Path, log_path) -> Optional[Path]:
    """Move a rotated file into the archive under the time of its last line (its mtime). Never raises."""
    try:
        d = dir_for(log_path)
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(path.stat().st_mtime))
        dest = d / ("%s%s.jsonl" % (PREFIX, stamp))
        n = 1
        while dest.exists() or dest.with_suffix(".jsonl.gz").exists():
            n += 1
            dest = d / ("%s%s-%d.jsonl" % (PREFIX, stamp, n))
        os.replace(str(path), str(dest))
        return dest
    except OSError:
        return None


def files(log_path) -> List[Path]:
    d = dir_for(log_path)
    try:
        found = [p for p in d.iterdir() if p.name.startswith(PREFIX) and p.name.endswith((".jsonl", ".jsonl.gz"))]
    except OSError:
        return []
    return sorted(found, key=lambda p: (p.stat().st_mtime, p.name))


def _compress(p: Path) -> bool:
    gz = p.with_name(p.name + ".gz")
    tmp = gz.with_name(gz.name + ".tmp")
    try:
        mtime = p.stat().st_mtime
        with open(p, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        os.utime(str(tmp), (mtime, mtime))          # the archive keeps the time of its last line
        os.replace(str(tmp), str(gz))
        p.unlink()
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def maintain(log_path, now: Optional[float] = None) -> Dict:
    """Compress stashed files, then prune by age and size. One process at a time; a busy one returns at once."""
    now = time.time() if now is None else now
    d = dir_for(log_path)
    if not d.is_dir():
        return {"compressed": 0, "pruned": 0, "kept": 0, "bytes": 0}
    with open(d / ".lock", "a", encoding="utf-8", newline="\n") as lock:
        if not platform_compat.lock_file(lock, blocking=False):
            return {"busy": True}
        compressed = sum(1 for p in files(log_path) if p.suffix == ".jsonl" and _compress(p))
        pruned = 0
        kept = files(log_path)
        for p in [p for p in kept if p.stat().st_mtime < now - KEEP_DAYS * 86400]:
            p.unlink()
            pruned += 1
        kept = files(log_path)
        total = sum(p.stat().st_size for p in kept)
        while kept and total > MAX_BYTES:
            p = kept.pop(0)
            total -= p.stat().st_size
            p.unlink()
            pruned += 1
        platform_compat.unlock_file(lock)
    return {"compressed": compressed, "pruned": pruned, "kept": len(kept), "bytes": total}
