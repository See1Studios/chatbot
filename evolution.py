"""Core of the self-evolution system: the protected-path registry.

Which paths an agent may never write is decided here, from a data file
(`protected_paths.json` in the service root), not from code. Tool servers and
API handlers ask `is_protected()`; they do not keep a list of their own.

It also owns the host-lifecycle safety pieces the control script only calls
into (docs/plans/recursive-self-evolution.md §3 0-6): one shared lock for
start/doctor/repair, a maintenance flag, and a content-hash manifest of the
protected files that `doctor` checks and warns about.

The observation side (§4.6) lives here too: `on_turn_end` turns a finished turn
into observation candidates, `add_observation` writes an observation-log entry.
The host and the tool server only call these; they hold no logic of their own.

Design constraints (§3 0-0):
- Standard library only, and the `root` argument decides every path. Nothing
  from the host (config, session, tool server, HTTP server) is imported, so
  importing this module has no side effects and cannot create a cycle or a
  directory.
- Fail closed for protection: a missing or malformed registry protects
  everything. Fail open for the lifecycle lock: it is a safeguard, never a
  reason the host cannot start.
- The lock sits behind one function (`acquire_lock`); only that function
  knows about `fcntl`, so another platform can swap it.

Command line (used by chatbot-ctl.sh, which stays thin):
  run-locked LOCK WAIT -- CMD...   run CMD holding LOCK (WAIT 0: skip when busy)
  maintenance FLAG                 exit 0 when the flag file exists
  manifest-check                   warn-only comparison with the manifest
  manifest-update                  re-baseline the manifest (a human does this)
  self-check LOCK                  can the lock helper run at all?
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:  # POSIX only; see acquire_lock
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

REGISTRY_NAME = "protected_paths.json"
MANIFEST_NAME = "protected_manifest.json"
_GLOB_CHARS = "*?["
BUSY_EXIT = 75  # EX_TEMPFAIL: the lock stayed busy for the whole wait
SIGNALS_NAME = "observation_signals.json"
CANDIDATES_NAME = "candidates.jsonl"
OBSERVATION_LOG = "observation-log"
_CANDIDATES_MAX_BYTES = 256 * 1024
_CANDIDATES_KEEP_LINES = 500
_EXCERPT_CHARS = 160
_candidates_lock = threading.Lock()


class TooManyObservations(Exception):
    """Too many observations were added recently (a runaway, not a review)."""


class RegistryError(Exception):
    """The registry file is missing or malformed."""


def registry_path(root) -> Path:
    return Path(root) / REGISTRY_NAME


def _entries(raw: dict, key: str, required: bool) -> List[str]:
    items = raw.get(key, [])
    if not isinstance(items, list) or (required and not items):
        raise RegistryError("'%s' must be %s list" % (key, "a non-empty" if required else "a"))
    out = []
    for item in items:
        pattern = item.get("path") if isinstance(item, dict) else item
        if not isinstance(pattern, str) or not pattern.strip():
            raise RegistryError("'%s' has an entry without a path" % key)
        out.append(pattern.strip())
    return out


def _load_raw(root) -> dict:
    path = registry_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RegistryError("cannot read %s: %s" % (path.name, e))
    if not isinstance(raw, dict):
        raise RegistryError("%s must hold a JSON object" % path.name)
    return raw


def load_registry(root) -> Tuple[List[str], List[str]]:
    """Return (protect, exceptions) patterns, or raise RegistryError."""
    raw = _load_raw(root)
    return _entries(raw, "protect", True), _entries(raw, "except", False)


def load_volatile(root) -> List[str]:
    """Protected paths whose content changes at run time (tickets, locks, caches):
    protected from writes but left out of the content manifest."""
    return _entries(_load_raw(root), "volatile", False)


def _matches(root: Path, pattern: str, target: Path) -> bool:
    subtree = pattern.endswith("/")
    body = pattern.rstrip("/")
    if body.startswith("~") or Path(body).is_absolute():
        head, parts = (), Path(body).expanduser().parts
    else:
        head, parts = root.parts, Path(body).parts  # the root itself is a literal, never a pattern
    lit = next((i for i, p in enumerate(parts) if any(c in p for c in _GLOB_CHARS)), len(parts))
    base = Path(*(head + parts[:lit])).resolve()  # resolve the literal prefix so a symlinked directory still matches
    rest = parts[lit:]
    tparts = target.parts
    if tparts[:len(base.parts)] != base.parts:
        return False
    tail = tparts[len(base.parts):]
    if len(tail) < len(rest) or (len(tail) > len(rest) and not subtree):
        return False
    return all(fnmatch.fnmatchcase(t, r) for t, r in zip(tail, rest))


def _targets(root: Path, path) -> List[Path]:
    """Where a write to `path` would land: the fully resolved path, and the
    resolved parent plus the unresolved final name (replacing a symlink
    changes the directory it sits in, not its destination)."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = root / p
    return [p.resolve(), p.parent.resolve() / p.name]


def match_protected(root, path) -> Optional[str]:
    """Return why `path` is protected (the matching pattern), or None if it may
    be written. Never raises: any failure to evaluate protects the path."""
    try:
        root_p = Path(root).resolve()
        protect, exceptions = load_registry(root_p)
        targets = _targets(root_p, path)
        for pattern in protect:
            if any(_matches(root_p, pattern, t) for t in targets):
                if any(_matches(root_p, ex, t) for ex in exceptions for t in targets):
                    return None
                return pattern
        return None
    except (RegistryError, OSError, RuntimeError, ValueError) as e:
        return "registry unavailable: %s" % e


def is_protected(root, path) -> bool:
    return match_protected(root, path) is not None


# ---------------------------------------------------------------- lifecycle lock

class LockBusy(Exception):
    """Another lifecycle operation holds the lock."""


def acquire_lock(path, wait: float = 0.0):
    """Take an exclusive lock on `path`, waiting up to `wait` seconds.

    Returns the open file (the lock lasts until it is closed or the process
    dies), or None where locking is unavailable. Raises LockBusy on timeout.
    """
    fh = open(str(path), "a")
    if fcntl is None:
        return fh
    deadline = time.time() + max(wait, 0.0)
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except (IOError, OSError):
            if time.time() >= deadline:
                fh.close()
                raise LockBusy(str(path))
            time.sleep(0.2)


def run_locked(lock_path, wait: float, argv: List[str]) -> int:
    """Run `argv` while holding the lifecycle lock; return its exit status.

    The lock belongs to this supervisor, not to `argv` (whose descendants, such
    as a server it starts, must not inherit it). The child learns it is inside
    the lock from CHATBOT_LOCK_PPID == its own parent pid, which a leaked
    environment variable in an unrelated process cannot satisfy.
    """
    try:
        held = acquire_lock(lock_path, wait)
    except LockBusy:
        if wait <= 0:
            print("lifecycle busy: another start/doctor/repair is running; skipped")
            return 0
        print("lifecycle busy: gave up waiting %ds for another start/doctor/repair" % wait)
        return BUSY_EXIT
    except OSError as e:
        print("WARN lifecycle lock unavailable (%s); running without it" % e)
        held = None
    env = dict(os.environ)
    env["CHATBOT_LOCK_PPID"] = str(os.getpid())
    proc = subprocess.Popen(argv, env=env)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda n, _f: proc.send_signal(n))
    rc = proc.wait()
    if held is not None:
        held.close()
    return rc if rc >= 0 else 128 - rc


# ------------------------------------------------------------ maintenance flag

def maintenance_note(flag_path) -> Optional[str]:
    """None when there is no maintenance flag, else a short description."""
    try:
        st = Path(flag_path).stat()
    except OSError:
        return None
    return "age %ds" % max(int(time.time() - st.st_mtime), 0)


# ------------------------------------------------------------- hash manifest

def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_files(root) -> List[str]:
    """Root-relative paths of the existing protected files that belong in the
    manifest: registry patterns under `root`, minus exceptions and volatile
    paths. Patterns outside `root` (the home directory, absolute) are not hashed."""
    root_p = Path(root).resolve()
    protect, exceptions = load_registry(root_p)
    skip = exceptions + load_volatile(root_p)
    found = set()
    for pattern in protect:
        body = pattern.rstrip("/")
        if body.startswith("~") or Path(body).is_absolute():
            continue
        cands = root_p.glob(body) if any(c in body for c in _GLOB_CHARS) else [root_p / body]
        for cand in cands:
            if cand.is_file():
                files = [cand]
            elif cand.is_dir() and pattern.endswith("/"):
                files = [f for f in cand.rglob("*") if f.is_file()]
            else:
                files = []
            for f in files:
                rel = f.relative_to(root_p)
                if ".git" in rel.parts:
                    continue
                target = f.resolve()
                if any(_matches(root_p, sp, target) for sp in skip):
                    continue
                found.add(rel.as_posix())
    return sorted(found)


def build_manifest(root) -> Dict[str, str]:
    root_p = Path(root).resolve()
    return {rel: _hash_file(root_p / rel) for rel in protected_files(root_p)}


def write_manifest(root) -> int:
    root_p = Path(root).resolve()
    hashes = build_manifest(root_p)
    doc = {"version": 1, "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "sha256": hashes}
    dest = root_p / MANIFEST_NAME
    tmp = dest.with_name(".%s.%d.tmp" % (dest.name, os.getpid()))
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return len(hashes)


def check_manifest(root) -> Tuple[str, Dict[str, List[str]]]:
    """Compare the protected files with the manifest. Returns (status, diffs):
    status is "ok", "differs", "none" (no manifest yet) or "unreadable"."""
    root_p = Path(root).resolve()
    dest = root_p / MANIFEST_NAME
    if not dest.exists():
        return "none", {}
    try:
        recorded = json.loads(dest.read_text(encoding="utf-8"))["sha256"]
        if not isinstance(recorded, dict):
            raise ValueError("sha256 must be an object")
        current = build_manifest(root_p)
    except (OSError, ValueError, KeyError, TypeError, RegistryError) as e:
        return "unreadable", {"error": [str(e)]}
    diffs = {
        "modified": sorted(k for k in current if k in recorded and current[k] != recorded[k]),
        "missing": sorted(k for k in recorded if k not in current),
        "new": sorted(k for k in current if k not in recorded),
    }
    return ("differs" if any(diffs.values()) else "ok"), diffs


def _short(items: List[str], limit: int = 8) -> str:
    return ", ".join(items[:limit]) + (" (+%d more)" % (len(items) - limit) if len(items) > limit else "")


def manifest_report(root) -> str:
    """One line for doctor. Lines starting with WARN are logged; the rest are informational."""
    status, diffs = check_manifest(root)
    if status == "none":
        return "manifest: none yet (a human runs `python3 evolution.py manifest-update` after reviewing the protected files)"
    if status == "unreadable":
        return "WARN protected-file manifest unreadable: %s" % diffs["error"][0]
    if status == "ok":
        return "manifest OK"
    parts = ["%s=[%s]" % (k, _short(v)) for k, v in diffs.items() if v]
    return "WARN protected files differ from the manifest (warning only): " + " ".join(parts)


# ------------------------------------------------------------------ observation

def load_signal_config(root) -> Dict[str, List[str]]:
    """Patterns from observation_signals.json. Collection is best effort, so a
    missing or broken file yields an empty config instead of an error."""
    empty = {"correction": [], "ignore_user_prefixes": []}
    try:
        raw = json.loads((Path(root) / SIGNALS_NAME).read_text(encoding="utf-8"))
        return {k: [x for x in (raw.get(k) if isinstance(raw.get(k), list) else []) if isinstance(x, str) and x]
                for k in empty}
    except (OSError, ValueError, AttributeError, TypeError):
        return empty


def detect_correction(text: str, patterns: List[str]) -> Optional[str]:
    """The first pattern the user's message matches (the user is correcting the
    previous answer), or None. Invalid patterns are skipped."""
    for pat in patterns:
        try:
            if re.search(pat, text or "", re.IGNORECASE):
                return pat
        except re.error:
            continue
    return None


def record_candidate(obs_root, signal: str, sid: str, provider: str, detail: Optional[Dict] = None) -> bool:
    """Append one line to candidates.jsonl under `obs_root`. Only where that
    directory already exists (an instance that keeps observations); the file is
    trimmed to its newest lines when it grows large. Never raises."""
    try:
        base = Path(obs_root)
        if not base.is_dir():
            return False
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "epoch": round(time.time(), 3),
                 "sid": str(sid)[:80], "provider": str(provider)[:40], "signal": str(signal)[:40]}
        entry["detail"] = {str(k)[:40]: (v if isinstance(v, (int, float)) else str(v)[:_EXCERPT_CHARS + 40])
                           for k, v in (detail or {}).items()}
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        path = base / CANDIDATES_NAME
        with _candidates_lock:
            if path.exists() and path.stat().st_size > _CANDIDATES_MAX_BYTES:
                kept = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_CANDIDATES_KEEP_LINES:]
                tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
                tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
                tmp.replace(path)
            with open(str(path), "a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception:  # noqa: BLE001 -- observing must never disturb a turn
        return False


def turn_signals(cfg: Dict[str, List[str]], outcome: str, marks: List[str], user_text: str) -> List[Tuple[str, str]]:
    """(signal, note) pairs for a finished turn; empty for an ordinary one.

    outcome: how the host saw it end ("result", "error", "stopped", "steer",
    "interrupted", "process_died", "auto_stop"). marks: kinds of error/stopped/
    interrupted events emitted during the turn. Only the user's own words and
    host measurements are used -- never tool or web output (§4.4).
    """
    text = (user_text or "").strip()
    if any(text.startswith(p) for p in cfg.get("ignore_user_prefixes", [])):
        return []
    found: List[Tuple[str, str]] = []
    kinds = set(m for m in marks if m in ("error", "stopped", "interrupted"))
    if outcome in ("process_died", "stopped", "auto_stop"):
        kinds.add(outcome)
    elif outcome == "interrupted":
        kinds.add("interrupted")
    if "process_died" in kinds:
        kinds.discard("error")
    if outcome == "steer":  # the user adding an instruction mid-turn is normal use, not a failure
        kinds.discard("interrupted")
    if "auto_stop" in kinds:  # the host's own stop already explains its error/stopped events
        kinds -= {"error", "stopped"}
    for kind in sorted(kinds):
        found.append((kind, outcome))
    hit = detect_correction(text, cfg.get("correction", []))
    if hit:
        found.append(("correction", hit))
    return found


def on_turn_end(root, obs_root, sid: str, provider: str, outcome: str, marks: List[str], user_text: str) -> List[str]:
    """Record the candidates for one finished turn; returns the signals recorded."""
    try:
        cfg = load_signal_config(root)
        recorded = []
        for signal_name, note in turn_signals(cfg, outcome, marks, user_text):
            detail = {"outcome": outcome, "note": note, "user": (user_text or "").strip()[:_EXCERPT_CHARS]}
            if record_candidate(obs_root, signal_name, sid, provider, detail):
                recorded.append(signal_name)
        return recorded
    except Exception:  # noqa: BLE001
        return []


def _next_observation_id(obs_dir: Path) -> int:
    top = 0
    for d in (obs_dir, obs_dir / "archive"):
        try:
            for f in d.iterdir():
                m = re.match(r"^(\d+)", f.name)
                if m:
                    top = max(top, int(m.group(1)))
        except OSError:
            continue
    try:
        top = max(top, int((obs_dir / "archive" / ".id-floor").read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        pass
    return top + 1


def add_observation(obs_dir, title: str, body: str, area: str = "", recent_limit: Optional[int] = None,
                    window_sec: int = 3600) -> Path:
    """Create the next observation-log entry (status: open) and return its path.
    The caller vets the text; this only bounds its size and picks a free number.
    With `recent_limit`, refuse (TooManyObservations) once that many entries
    were created in the last `window_sec` seconds."""
    d = Path(obs_dir)
    d.mkdir(parents=True, exist_ok=True)
    if recent_limit is not None:
        cutoff = time.time() - window_sec
        recent = 0
        for f in d.iterdir():
            try:
                if re.match(r"^\d+-", f.name) and f.stat().st_mtime >= cutoff:
                    recent += 1
            except OSError:
                continue
        if recent >= recent_limit:
            raise TooManyObservations("%d observations in the last %d minutes" % (recent, window_sec // 60))
    title = re.sub(r"\s+", " ", str(title)).strip().lstrip("#").strip()[:120] or "observation"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "observation"
    area = re.sub(r"\s+", " ", str(area)).strip()[:60]
    number = _next_observation_id(d)
    for _ in range(50):
        path = d / ("%04d-%s.md" % (number, slug))
        text = ("---\nid: %d\ntitle: %s\nstatus: open\ntype: internal\nskill: []\nproposes_skill: []\narea: %s\n"
                "date: %s\nparked_until:\nresolved:\nresolution:\nreference:\n---\n\n%s\n"
                % (number, json.dumps(title, ensure_ascii=False), json.dumps(area, ensure_ascii=False),
                   time.strftime("%Y-%m-%d"), str(body).strip()[:4000]))
        try:
            with open(str(path), "x", encoding="utf-8") as f:  # exclusive: two writers never share a number
                f.write(text)
            return path
        except FileExistsError:
            number += 1
    raise OSError("no free observation number")


# ---------------------------------------------------------------- command line

def main(argv: List[str]) -> int:
    root = Path(__file__).resolve().parent
    cmd = argv[0] if argv else ""
    try:
        if cmd == "run-locked" and len(argv) >= 5 and argv[3] == "--":
            return run_locked(argv[1], float(argv[2]), argv[4:])
        if cmd == "maintenance" and len(argv) == 2:
            note = maintenance_note(argv[1])
            if note is None:
                return 1
            print(note)
            return 0
        if cmd == "manifest-check":
            print(manifest_report(root))
            return 0  # warning only, never a failure
        if cmd == "manifest-update":
            print("manifest updated: %d files" % write_manifest(root))
            return 0
        if cmd == "self-check" and len(argv) == 2:
            held = acquire_lock(argv[1], 0.0)
            if held is not None:
                held.close()
            return 0
    except LockBusy:
        return 0  # the lock file opens fine; someone else holds it
    except Exception as e:  # noqa: BLE001 -- the caller treats any failure as "helper unusable"
        print("evolution: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 70
    print(__doc__.split("Command line", 1)[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
