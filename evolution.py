"""Core of the self-evolution system: the protected-path registry.

Which paths an agent may never write is decided here, from a data file
(`protected_paths.json` in the service root), not from code. Tool servers and
API handlers ask `is_protected()`; they do not keep a list of their own.

It also owns the host-lifecycle safety pieces the control script only calls
into (docs/plans/recursive-self-evolution.md §3 0-6): one shared lock for
start/doctor/repair, a maintenance flag, and the check `doctor` warns with: protected files
that differ from git HEAD (edited, deleted or new and uncommitted).

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
- The lock sits behind one function (`acquire_lock`), which takes it through
  platform_compat (flock on POSIX, msvcrt on Windows; a core module too).

Command line (used by chatbot-ctl.sh, which stays thin):
  run-locked LOCK WAIT -- CMD...   run CMD holding LOCK (WAIT 0: skip when busy)
  maintenance FLAG                 exit 0 when the flag file exists
  protected-check                  warn-only: protected files that differ from git HEAD
  self-check LOCK                  can the lock helper run at all?
"""
from __future__ import annotations

import fnmatch
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

import platform_compat   # a core module too (core_modules.json, PP5): the lock's POSIX and Windows sides
import platform_compat

REGISTRY_NAME = "protected_paths.json"
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
    protected from writes but left out of the uncommitted-change check."""
    return _entries(_load_raw(root), "volatile", False)


_DATA_ENV = ("CHATBOT_DATA", "PE_HOME", "PRIVATEENGINE_HOME")   # host_config.DATA_ENV's order


def _live_data(root: Path) -> Optional[Path]:
    """The user-data dir this process runs on (uds/F: ~/.pe), when it is not the repo's own data/. chatbot-ctl.sh
    exports CHATBOT_DATA to the server, the tool server and every child, so the environment is enough here."""
    val = next((os.environ[k] for k in _DATA_ENV if os.environ.get(k)), "")
    if not val:
        return None
    live = Path(val).expanduser().resolve()
    return None if live == (root / "data").resolve() else live


def _matches(root: Path, pattern: str, target: Path) -> bool:
    subtree = pattern.endswith("/")
    body = pattern.rstrip("/")
    if body.startswith("~") or Path(body).is_absolute():
        head, parts = (), Path(body).expanduser().parts
    else:
        head, parts = root.parts, Path(body).parts  # the root itself is a literal, never a pattern
        if parts[:1] == ("data",):   # a data/ pattern names user data: it also holds where that data now lives
            live = _live_data(root)
            if live is not None and _matches(root, str(live.joinpath(*parts[1:])) + ("/" if subtree else ""), target):
                return True
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


def match_governance(root, path) -> Optional[str]:
    """Return why `path` is governance (Tier 3: guards, gates, approval rules, the charter, this
    registry), or None. Never raises: any failure to evaluate counts as governance."""
    try:
        root_p = Path(root).resolve()
        patterns = _entries(_load_raw(root_p), "governance", False)
        targets = _targets(root_p, path)
        return next((pat for pat in patterns if any(_matches(root_p, pat, t) for t in targets)), None)
    except (RegistryError, OSError, RuntimeError, ValueError) as e:
        return "registry unavailable: %s" % e


def delegation_tier(root, path) -> Tuple[int, str]:
    """How a change to `path` may land when delegated (docs/plans/multi-agent-worktree-delegation.md §9):
    3 governance (refused), 2 protected (the operator lets it land), 0 otherwise (lands on its gates).
    Returns (tier, the matching pattern or '')."""
    why = match_governance(root, path)
    if why:
        return 3, why
    why = match_protected(root, path)
    return (2, why) if why else (0, "")


# ---------------------------------------------------------------- lifecycle lock

class LockBusy(Exception):
    """Another lifecycle operation holds the lock."""


def acquire_lock(path, wait: float = 0.0):
    """Take an exclusive lock on `path`, waiting up to `wait` seconds.

    Returns the open file (the lock lasts until it is closed or the process
    dies), or None where locking is unavailable. Raises LockBusy on timeout.
    """
    fh = open(str(path), "a", encoding="utf-8", newline="\n")
    deadline = time.time() + max(wait, 0.0)
    while not platform_compat.lock_file(fh, blocking=False):
        if time.time() >= deadline:
            fh.close()
            raise LockBusy(str(path))
        time.sleep(0.2)
    return fh


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
    def forward(signum, _frame):
        try:
            proc.send_signal(signum)
        except (OSError, ValueError):   # Windows forwards only some signals to a child: stop it instead
            proc.terminate()

    for name in ("SIGTERM", "SIGINT", "SIGHUP"):   # SIGHUP does not exist on Windows (#411)
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, forward)
            except (OSError, ValueError):
                pass
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


# ------------------------------------------------------------- protected changes

# A reviewed change arrives as a commit (tickets, hooks); an unreviewed one leaves a protected file that differs from
# git HEAD -- edited, deleted, or new and never committed. That is what doctor warns about. Until split/E (2026-10-02)
# this compared content hashes with protected_manifest.json, a baseline a human re-took by hand: it went stale the day
# after it was taken and the warning stayed on for every ordinary commit, hiding any real one.

def protected_changes(root) -> Tuple[str, Dict[str, List[str]]]:
    """Protected files that differ from git HEAD, minus exceptions and volatile paths. Returns (status, diffs): status
    is "ok", "differs", "nogit" (`root` is not the top of a git work tree -- a parent repository's HEAD is not this
    service's baseline -- so nothing to compare with) or "unreadable"; diffs holds "modified", "missing" (deleted)
    and "new" (added or untracked) lists of paths relative to `root`."""
    root_p = Path(root).resolve()
    try:
        top = subprocess.run(["git", "-C", str(root_p), "rev-parse", "--show-toplevel"], capture_output=True,
                             timeout=30)
        if top.returncode != 0 or Path(top.stdout.decode("utf-8").strip()).resolve() != root_p:
            return "nogit", {}
        st = subprocess.run(["git", "-C", str(root_p), "status", "--porcelain=v1", "-z", "--untracked-files=all",
                             "--no-renames"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "nogit", {}
    if st.returncode != 0:
        return "unreadable", {"error": [st.stderr.decode("utf-8", "replace").strip() or "git status failed"]}
    try:
        protect, exceptions = load_registry(root_p)
        skip = exceptions + load_volatile(root_p)
    except (RegistryError, OSError, ValueError) as e:
        return "unreadable", {"error": [str(e)]}
    diffs: Dict[str, List[str]] = {"modified": [], "missing": [], "new": []}
    for entry in st.stdout.decode("utf-8", "replace").split("\0"):
        if len(entry) < 4:
            continue
        xy, rel = entry[:2], entry[3:]
        targets = _targets(root_p, rel)
        if not any(_matches(root_p, p, t) for p in protect for t in targets):
            continue
        if any(_matches(root_p, p, t) for p in skip for t in targets):
            continue
        kind = "new" if (xy == "??" or "A" in xy) else ("missing" if "D" in xy else "modified")
        diffs[kind].append(rel)
    return ("differs" if any(diffs.values()) else "ok"), {k: sorted(v) for k, v in diffs.items()}


def _short(items: List[str], limit: int = 8) -> str:
    return ", ".join(items[:limit]) + (" (+%d more)" % (len(items) - limit) if len(items) > limit else "")


def protected_report(root) -> str:
    """One line for doctor. Lines starting with WARN are logged; the rest are informational."""
    status, diffs = protected_changes(root)
    if status == "nogit":
        return "protected files: not a git work tree, nothing to compare with"
    if status == "unreadable":
        return "WARN protected-file check unreadable: %s" % diffs["error"][0]
    if status == "ok":
        return "protected files OK (all committed)"
    parts = ["%s=[%s]" % (k, _short(v)) for k, v in diffs.items() if v]
    return "WARN protected files differ from git HEAD (warning only): " + " ".join(parts)


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
                platform_compat.write_text(tmp, "\n".join(kept) + "\n", encoding="utf-8")
                tmp.replace(path)
            with open(str(path), "a", encoding="utf-8", newline="\n") as f:
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


# NAME_NEUTRAL_v1: who did something is stored as a role id -- "claude-code", "grok", "operator",
# "chat-agent:agy" -- never as a persona name or the persona's word for the user. Those are display,
# per instance, from the identity files; the pattern keeps them out structurally (ASCII only).
ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,30}(?::[a-z0-9._?-]{1,20})?$")


def role_id(value) -> str:
    """"" for nothing; the value if it is a role id; ValueError otherwise."""
    v = str(value or "").strip()
    if v and not ROLE_ID_RE.match(v):
        raise ValueError("actor must be a role id like claude-code, operator or chat-agent:agy "
                         "(not a persona name or title): %r" % v[:40])
    return v


def add_observation(obs_dir, title: str, body: str, area: str = "", recent_limit: Optional[int] = None,
                    window_sec: int = 3600, actor: str = "") -> Path:
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
    actor = role_id(actor)  # who recorded it (ACTOR_ATTRIBUTION_v1); a role id (NAME_NEUTRAL_v1)
    number = _next_observation_id(d)
    for _ in range(50):
        path = d / ("%04d-%s.md" % (number, slug))
        text = ("---\nid: %d\ntitle: %s\nstatus: open\ntype: internal\nskill: []\nproposes_skill: []\narea: %s\n"
                "date: %s\nparked_until:\nresolved:\nresolution:\nreference:\n%s---\n\n%s\n"
                % (number, json.dumps(title, ensure_ascii=False), json.dumps(area, ensure_ascii=False),
                   time.strftime("%Y-%m-%d"), ("actor: %s\n" % json.dumps(actor, ensure_ascii=False)) if actor else "",
                   str(body).strip()[:4000]))
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
        if cmd == "protected-check":
            print(protected_report(root))
            return 0  # warning only, never a failure
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
