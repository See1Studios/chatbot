"""Observation life cycle: what happens to an observation after it is recorded
(docs/plans/recursive-self-evolution.md §4.6). Core module: standard library and
`evolution`, every path derived from the `obs_root` argument.

The cycle is observe -> record -> refer -> act, and this module owns the last
two steps that a recorded observation still needs:

- scan: read only the header of each observation file, so it stays cheap when
  hundreds exist. A log that has files but yields no parsed header is a broken
  scan, never "nothing to see".
- resolve: open/parked -> actioned | declined | superseded, with a date and a
  one-line resolution. A resolved observation is archived the day after.
- review: a digest of the open observations plus the host's candidates since the
  last review, and a review date that is written only when a review ran (with a
  line saying what came of it).

Layout under `obs_root` (data/workspace/skill-observations):
  observation-log/NNNN-slug.md   open and parked observations
  observation-log/archive/       resolved observations, one day or more old
  candidates.jsonl               turn signals collected by the host
  last-review-date.txt           `never`, or the date a review last ran
  last-review-epoch.txt          the moment it ran (candidates before it count as reviewed)
  review-history.log             one line per review
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import evolution

RESOLVED = ("actioned", "declined", "superseded")
STATES = ("open", "parked") + RESOLVED
LAST_REVIEW = "last-review-date.txt"
LAST_REVIEW_EPOCH = "last-review-epoch.txt"
REVIEW_HISTORY = "review-history.log"
_HEADER_BYTES = 16384
_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:[ \t]?(.*))?$")


class ObservationError(Exception):
    """A refusal the caller can show as is."""


class ScanBroken(ObservationError):
    """Files are there but no header could be read: the scan itself is faulty."""


def log_dir(obs_root) -> Path:
    return Path(obs_root) / evolution.OBSERVATION_LOG


# ----------------------------------------------------------------- frontmatter

def _header_lines(text: str) -> Optional[List[str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i]
    return None


def _value(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith('"'):
        try:
            return str(json.loads(raw))
        except ValueError:
            pass
    return raw


def parse_header(text: str) -> Optional[Dict[str, str]]:
    """Top-level `key: value` pairs of the header block; None if there is no header.
    List continuation lines are ignored (only scalar fields matter here)."""
    lines = _header_lines(text)
    if lines is None:
        return None
    meta: Dict[str, str] = {}
    for line in lines:
        m = _KEY.match(line)
        if m:
            meta[m.group(1)] = _value(m.group(2))
    return meta


def _read_header(path: Path) -> Optional[Dict[str, str]]:
    try:
        with open(str(path), encoding="utf-8", errors="replace") as f:
            return parse_header(f.read(_HEADER_BYTES))
    except OSError:
        return None


def _entry(path: Path, meta: Dict[str, str]) -> Dict:
    m = re.match(r"^(\d+)", path.name)
    try:
        oid = int(meta.get("id") or (m.group(1) if m else ""))
    except ValueError:
        oid = int(m.group(1)) if m else 0
    return {"id": oid, "file": path.name, "title": meta.get("title", ""), "status": (meta.get("status") or "").lower(),
            "area": meta.get("area", ""), "date": meta.get("date", ""), "resolved": meta.get("resolved", ""),
            "parked_until": meta.get("parked_until", "")}


# ------------------------------------------------------------------------ scan

def scan(obs_root, include_archive: bool = False) -> List[Dict]:
    """Header-only listing, oldest id first. Raises ScanBroken when the log has
    observation files and none of them parsed."""
    dirs = [log_dir(obs_root)]
    if include_archive:
        dirs.append(log_dir(obs_root) / "archive")
    out: List[Dict] = []
    files = 0
    for d in dirs:
        try:
            names = sorted(f for f in d.iterdir() if f.is_file() and f.suffix == ".md")
        except OSError:
            continue
        for f in names:
            files += 1
            meta = _read_header(f)
            if meta is not None:
                out.append(_entry(f, meta))
    if files and not out:
        raise ScanBroken("%d observation file(s) but no readable header: the scan is broken, not the log empty" % files)
    return sorted(out, key=lambda e: e["id"])


def find(obs_root, oid) -> Tuple[Path, Dict]:
    """The file of observation `oid` (log first, then archive) and its header."""
    try:
        want = int(oid)
    except (TypeError, ValueError):
        raise ObservationError("no such observation: %s" % (oid,))
    for d in (log_dir(obs_root), log_dir(obs_root) / "archive"):
        try:
            for f in sorted(d.glob("*.md")):
                meta = _read_header(f)
                if meta is not None and _entry(f, meta)["id"] == want:
                    return f, meta
        except OSError:
            continue
    raise ObservationError("no such observation: %s" % oid)


def get(obs_root, oid) -> Dict:
    path, meta = find(obs_root, oid)
    text = path.read_text(encoding="utf-8", errors="replace")
    body = text.split("\n---\n", 1)[1] if "\n---\n" in text else ""
    out = _entry(path, meta)
    out["archived"] = path.parent.name == "archive"
    out["body"] = body.strip()[:4000]
    return out


def list_observations(obs_root, status: Optional[str] = None) -> List[Dict]:
    return [e for e in scan(obs_root) if status in (None, "", e["status"])]


# --------------------------------------------------------------------- resolve

def _set_fields(text: str, fields: Dict[str, str]) -> str:
    """Set top-level header fields in place (adding any that are missing before the closing rule)."""
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if not lines or lines[0].strip() != "---" or end is None:
        raise ObservationError("observation has no header block")
    for key, val in fields.items():
        for i in range(1, end):
            m = _KEY.match(lines[i])
            if m and m.group(1) == key:
                lines[i] = "%s: %s" % (key, val) if val != "" else "%s:" % key
                break
        else:
            lines.insert(end, "%s: %s" % (key, val) if val != "" else "%s:" % key)
            end += 1
    return "\n".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _line(value, limit: int) -> str:
    """One trimmed line of text; None is empty, not the word "None"."""
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()[:limit]


def _today(now: Optional[float]) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))


def resolve(obs_root, oid, status: str, resolution: str, until: str = "", now: Optional[float] = None) -> Dict:
    """Move an open or parked observation to actioned/declined/superseded (or park it).
    A resolution line is required: closing without saying why is how findings vanish."""
    if status not in ("parked",) + RESOLVED:
        raise ObservationError("status must be one of: parked, %s" % ", ".join(RESOLVED))
    resolution = _line(resolution, 300)
    if not resolution:
        raise ObservationError("a resolution is required")
    path, meta = find(obs_root, oid)
    current = (meta.get("status") or "").lower()
    if current in RESOLVED:
        raise ObservationError("observation %s is already %s" % (oid, current))
    fields = {"status": status, "resolution": json.dumps(resolution, ensure_ascii=False)}
    if status == "parked":
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(until or "")):
            raise ObservationError("parking needs `until` as YYYY-MM-DD")
        fields["parked_until"] = until
        fields["resolved"] = ""
    else:
        fields["resolved"] = _today(now)
        fields["parked_until"] = ""
    _atomic_write(path, _set_fields(path.read_text(encoding="utf-8"), fields))
    return _entry(path, _read_header(path) or {})


# --------------------------------------------------------------------- archive

def archive_resolved(obs_root, now: Optional[float] = None) -> List[str]:
    """Move observations resolved BEFORE today into archive/. One resolved today stays until
    tomorrow; a resolved one with no readable date gets today's date written instead.
    Returns the file names moved."""
    today = _today(now)
    moved: List[str] = []
    d = log_dir(obs_root)
    try:
        files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix == ".md")
    except OSError:
        return moved
    for f in files:
        meta = _read_header(f)
        if not meta or (meta.get("status") or "").lower() not in RESOLVED:
            continue
        when = meta.get("resolved", "")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", when):
            _atomic_write(f, _set_fields(f.read_text(encoding="utf-8"), {"resolved": today}))
            continue
        if when < today:
            (d / "archive").mkdir(exist_ok=True)
            f.replace(d / "archive" / f.name)
            moved.append(f.name)
    return moved


def add(obs_root, title: str, body: str, area: str = "", recent_limit: Optional[int] = None) -> Path:
    """Record a new observation. The archive sweep rides on the write, so it cannot be skipped."""
    d = log_dir(obs_root)
    archive_resolved(obs_root)
    return evolution.add_observation(d, title, body, area, recent_limit=recent_limit)


# ---------------------------------------------------------------------- review

def last_review(obs_root) -> str:
    try:
        return (Path(obs_root) / LAST_REVIEW).read_text(encoding="utf-8").strip() or "never"
    except OSError:
        return "never"


def _review_start_epoch(obs_root, last: str) -> float:
    """Candidates from this moment on are unreviewed: the exact review time when it agrees with the
    date file, else the start of that date (so a person editing the date file wins over a stale time)."""
    try:
        day_start = time.mktime(time.strptime(last, "%Y-%m-%d"))
    except ValueError:
        return 0.0
    try:
        exact = float((Path(obs_root) / LAST_REVIEW_EPOCH).read_text(encoding="utf-8").strip())
        if time.strftime("%Y-%m-%d", time.localtime(exact)) == last:
            return exact
    except (OSError, ValueError):
        pass
    return day_start


def unreviewed_candidates(obs_root) -> List[Dict]:
    """Candidates the host collected since the last review day began."""
    start = _review_start_epoch(obs_root, last_review(obs_root))
    out: List[Dict] = []
    try:
        for line in (Path(obs_root) / evolution.CANDIDATES_NAME).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                if float(row.get("epoch", 0)) >= start:
                    out.append(row)
            except (ValueError, TypeError, AttributeError):
                continue
    except OSError:
        pass
    return out


def digest(obs_root, now: Optional[float] = None, candidate_rows: int = 10) -> Dict:
    """What a review looks at: open and parked observations, and candidates since the last review.
    Candidates are hints: cite one as evidence with its `ref`."""
    archive_resolved(obs_root, now)
    entries = scan(obs_root)
    cands = unreviewed_candidates(obs_root)
    by_signal: Dict[str, int] = {}
    for c in cands:
        by_signal[c.get("signal", "?")] = by_signal.get(c.get("signal", "?"), 0) + 1
    recent = [{"ref": "candidate:%s" % c.get("epoch"), "ts": c.get("ts"), "signal": c.get("signal"),
               "provider": c.get("provider"), "user": (c.get("detail") or {}).get("user", "")}
              for c in cands[-candidate_rows:]]
    last = last_review(obs_root)
    return {
        "last_review": last,
        "open": [{k: e[k] for k in ("id", "title", "area", "date")} for e in entries if e["status"] == "open"],
        "parked": [{k: e[k] for k in ("id", "title", "parked_until")} for e in entries if e["status"] == "parked"],
        "unreviewed_candidates": len(cands),
        "candidates_by_signal": by_signal,
        "recent_candidates": recent,
    }


def mark_reviewed(obs_root, summary: str, now: Optional[float] = None) -> str:
    """Record that a review actually ran. A date means a review happened, so a summary of what
    came of it is required and kept in review-history.log."""
    summary = _line(summary, 300)
    if not summary:
        raise ObservationError("say what the review covered and decided; a date without a review is a lie")
    base = Path(obs_root)
    if not base.is_dir():
        raise ObservationError("no observation directory")
    archive_resolved(obs_root, now)
    day = _today(now)
    _atomic_write(base / LAST_REVIEW_EPOCH, "%.3f\n" % (time.time() if now is None else now))
    _atomic_write(base / LAST_REVIEW, day + "\n")
    with open(str(base / REVIEW_HISTORY), "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (day, summary))
    return day
