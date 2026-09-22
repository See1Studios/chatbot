"""Evolution tickets: how an observation becomes work (docs/plans/recursive-self-evolution.md §4.2-4.3).

Work on the host itself starts only from the operator's own words or from a
ticket the operator approved. A ticket must carry evidence that really exists,
has a small attempt budget, and can be worked on by one author at a time.

- Evidence is verified, not trusted: `event:<sid>#<line>` must be a line of that
  session's events.jsonl, `candidate:<epoch>` a line of candidates.jsonl.
- Same target, same ticket: a proposal for a target that already has an open
  ticket adds its evidence to it instead of creating a second one.
- Budget: at most MAX_ATTEMPTS attempts; after that the ticket is closed as
  `wontfix` with reason `needs-human`. Two gate failures in a row advise
  changing the approach or stopping.
- One author: `claim` takes a lease (`author.lease`). Nobody waits: a busy
  claim leaves a note on the ticket and fails. Leases expire (LEASE_TTL_SEC),
  so a session that vanished does not block the work forever. The lease is
  identified by a random token that only the claimer holds (stored hashed).
- Paths: `claim(..., paths=[...])` records repo-relative files. A new claim is
  refused if those paths already have uncommitted leftover. `release(done)` is
  refused until those paths (or a filesystem-looking `target`) are clean in git.
- Approving, declining, reopening and dropping the lease are for the operator, at
  a terminal (`python3 tickets.py approve N`, which asks to retype the number);
  the agent-facing tool has no such action. The same functions refuse a call that
  does not say who is asking, so an agent with a shell cannot do it by accident
  by importing this module. It could still do it on purpose (same user account);
  this stops mistakes, not a determined process. The record says how it was
  asked: `operator (tty)` from the command line, `operator (api)` otherwise.

Standard library plus the core module `evolution`; the data directory is an
argument, nothing is read from the host.

Command line (operator):
  list [STATUS]      show tickets            show N       one ticket in full
  approve N          proposed -> approved    decline N    close as declined
  reopen N           a wontfix ticket gets a fresh budget
  drop-lease         clear the author lease (after a crashed session)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import evolution

OPERATOR_TTY = "tty"          # the command line, at a terminal, after retyping the number
OPERATOR_CONFIRMED = "api"    # a caller that states outright that it acts for the operator
OPERATOR_UI = "ui"            # the operator's own `/ticket ...` command in the host's chat page (same-origin POST)
MAX_ATTEMPTS = 3
GATE_FAILURES_ADVICE = 2
LEASE_TTL_SEC = 1800
MAX_PROPOSED = 10          # unreviewed proposals; more is a runaway, not a review
MAX_EVIDENCE = 20
MAX_NOTES = 40
MAX_PATHS = 20
OPEN_STATES = ("proposed", "approved", "in_progress")
CLOSED_STATES = ("done", "wontfix", "declined")
_SID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class TicketError(Exception):
    """A refusal the caller can show as is."""


# ------------------------------------------------------------------ storage

def tickets_dir(data) -> Path:
    return Path(data) / "workspace" / "skill-observations" / "tickets"


def _lease_path(data) -> Path:
    return tickets_dir(data) / "author.lease"


@contextmanager
def _locked(data, wait: float = 5.0) -> Iterator[None]:
    d = tickets_dir(data)
    d.mkdir(parents=True, exist_ok=True)
    try:
        fh = evolution.acquire_lock(d / ".lock", wait)
    except evolution.LockBusy:
        raise TicketError("ticket store is busy; try again")
    try:
        yield
    finally:
        if fh is not None:
            fh.close()


def _now(now: Optional[float]) -> float:
    return time.time() if now is None else now


def _operator_by(operator: Optional[str], what: str) -> str:
    """Who is asking, for the record. Refuses a call that does not say."""
    if operator not in (OPERATOR_TTY, OPERATOR_CONFIRMED, OPERATOR_UI):
        raise TicketError("%s is for the operator, at a terminal: run `python3 tickets.py ...` yourself, "
                          "or ask the operator. Agents do not decide tickets." % what)
    return "operator (%s)" % operator


def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def _path(data, ticket_id: int) -> Path:
    return tickets_dir(data) / ("%04d.json" % ticket_id)


def _load(data, ticket_id) -> Dict:
    try:
        tid = int(ticket_id)
        return json.loads(_path(data, tid).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise TicketError("no such ticket: %s" % (ticket_id,))


def _save(data, t: Dict) -> None:
    path = _path(data, t["id"])
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(json.dumps(t, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _all(data) -> List[Dict]:
    out = []
    d = tickets_dir(data)
    if d.is_dir():
        for f in sorted(d.glob("[0-9][0-9][0-9][0-9].json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return out


def _note(t: Dict, by: str, text: str, now: float) -> None:
    t.setdefault("notes", []).append({"ts": _stamp(now), "by": by, "text": str(text).strip()[:500]})
    del t["notes"][:-MAX_NOTES]
    t["updated"] = _stamp(now)


def _txt(value) -> str:
    """Text from a caller-supplied value; None is empty, not the word "None"."""
    return "" if value is None else str(value)


def _norm_target(target: str) -> str:
    return re.sub(r"\s+", " ", _txt(target)).strip().lower()[:80]


def public(t: Dict) -> Dict:
    """The ticket as an agent may see it (there is nothing secret in a ticket; the token lives in the lease)."""
    return dict(t)


# ----------------------------------------------------------------- evidence

def verify_evidence(data, ref: str) -> None:
    """Raise TicketError unless `ref` names something that exists."""
    ref = str(ref).strip()
    m = re.match(r"^event:([^#]+)#(\d{1,7})$", ref)
    if m:
        sid, line_no = m.group(1), int(m.group(2))
        if not _SID_RE.match(sid) or line_no < 1:
            raise TicketError("bad evidence reference: %s" % ref)
        path = Path(data) / "sessions" / sid / "events.jsonl"
        try:
            with open(str(path), encoding="utf-8", errors="replace") as f:
                for i, _ in enumerate(f, 1):
                    if i == line_no:
                        return
        except OSError:
            pass
        raise TicketError("evidence not found: %s" % ref)
    m = re.match(r"^candidate:(\d+(?:\.\d+)?)$", ref)
    if m:
        want = float(m.group(1))
        path = Path(data) / "workspace" / "skill-observations" / evolution.CANDIDATES_NAME
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    if abs(float(json.loads(line).get("epoch", -1)) - want) < 0.0005:
                        return
                except (ValueError, TypeError, AttributeError):
                    continue
        except OSError:
            pass
        raise TicketError("evidence not found: %s" % ref)
    raise TicketError("evidence must be event:<session>#<line> or candidate:<epoch>, got: %s" % ref[:60])


# ---------------------------------------------------------------- ship-gate

def _norm_paths(paths) -> List[str]:
    if not paths:
        return []
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list):
        raise TicketError("paths must be a list of repo-relative files")
    out = []
    for raw in paths[:MAX_PATHS]:
        s = _txt(raw).strip().replace("\\", "/")
        if not s or s.startswith("/") or ".." in s.split("/"):
            raise TicketError("path must be repo-relative, got: %s" % s[:60])
        if s not in out:
            out.append(s[:200])
    return out


def _git_root(data) -> Optional[Path]:
    p = Path(data).resolve()
    for _ in range(8):
        if (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


def _porcelain(root: Path, rels: List[str]) -> List[str]:
    if not rels:
        return []
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain", "--"] + list(rels),
            cwd=str(root), text=True, errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    dirty = []
    for line in out.splitlines():
        path = line[3:].strip() if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[-1]
        path = path.strip().strip('"')
        if path:
            dirty.append(path)
    return dirty


def _paths_of(t: Dict) -> List[str]:
    stored = t.get("paths") or []
    if stored:
        return list(stored)
    tgt = _txt(t.get("target")).strip()
    if "/" in tgt and " " not in tgt and not tgt.startswith("/") and ".." not in tgt.split("/"):
        return [tgt]
    return []


def _ship_blockers(data, t: Dict) -> List[str]:
    """Uncommitted paths that block `done`. Empty when there is no git or no paths."""
    rels = _paths_of(t)
    root = _git_root(data)
    if not rels or root is None:
        return []
    return _porcelain(root, rels)


# ---------------------------------------------------------------- proposals

def propose(data, title: str, target: str, evidence: List[str], now: Optional[float] = None) -> Tuple[Dict, bool]:
    """Create a ticket (status `proposed`) or merge into the open ticket for the same target.
    Returns (ticket, merged)."""
    t_now = _now(now)
    title = re.sub(r"\s+", " ", _txt(title)).strip()[:120]
    tgt = _norm_target(target)
    if not title or not tgt:
        raise TicketError("title and target are required")
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, list) or not evidence:
        raise TicketError("evidence is required: a ticket without evidence is an opinion")
    refs = []
    for ref in evidence[:MAX_EVIDENCE]:
        verify_evidence(data, ref)
        ref = str(ref).strip()
        if ref not in refs:
            refs.append(ref)
    with _locked(data):
        tickets = _all(data)
        for t in tickets:
            if t.get("status") in OPEN_STATES and t.get("target") == tgt:
                added = [r for r in refs if r not in t["evidence"]]
                t["evidence"] = (t["evidence"] + added)[:MAX_EVIDENCE]
                _note(t, "agent", "proposal merged (+%d evidence)" % len(added), t_now)
                _save(data, t)
                return public(t), True
        if sum(1 for t in tickets if t.get("status") == "proposed") >= MAX_PROPOSED:
            raise TicketError("%d proposals are waiting for the operator; do not add more" % MAX_PROPOSED)
        ticket = {"id": max([x["id"] for x in tickets] + [0]) + 1, "title": title, "target": tgt,
                  "status": "proposed", "attempts": 0, "gate_failures": 0, "evidence": refs, "notes": [],
                  "created": _stamp(t_now), "updated": _stamp(t_now)}
        d = tickets_dir(data)
        for _ in range(20):  # the store lock makes this a formality; exclusive create keeps it honest
            try:
                with open(str(_path(data, ticket["id"])), "x", encoding="utf-8"):
                    pass
                break
            except FileExistsError:
                ticket["id"] += 1
        _save(data, ticket)
        return public(ticket), False


# -------------------------------------------------------- operator decisions

def approve(data, ticket_id, now: Optional[float] = None, operator: Optional[str] = None) -> Dict:
    by = _operator_by(operator, "approving a ticket")
    with _locked(data):
        t = _load(data, ticket_id)
        if t["status"] != "proposed":
            raise TicketError("ticket %d is %s, not proposed" % (t["id"], t["status"]))
        t["status"] = "approved"
        t["approved_at"] = _stamp(_now(now))
        _note(t, by, "approved", _now(now))
        _save(data, t)
        return public(t)


def decline(data, ticket_id, now: Optional[float] = None, operator: Optional[str] = None) -> Dict:
    by = _operator_by(operator, "declining a ticket")
    with _locked(data):
        t = _load(data, ticket_id)
        if t["status"] not in ("proposed", "approved"):
            raise TicketError("ticket %d is %s" % (t["id"], t["status"]))
        t["status"] = "declined"
        t["closed_reason"] = "declined"
        _note(t, by, "declined", _now(now))
        _save(data, t)
        return public(t)


def reopen(data, ticket_id, now: Optional[float] = None, operator: Optional[str] = None) -> Dict:
    """A wontfix ticket the operator has looked at gets a fresh budget."""
    by = _operator_by(operator, "reopening a ticket")
    with _locked(data):
        t = _load(data, ticket_id)
        if t["status"] != "wontfix":
            raise TicketError("ticket %d is %s, not wontfix" % (t["id"], t["status"]))
        t.update(status="approved", attempts=0, gate_failures=0)
        t.pop("closed_reason", None)
        _note(t, by, "reopened with a fresh budget", _now(now))
        _save(data, t)
        return public(t)


def drop_lease(data, now: Optional[float] = None, operator: Optional[str] = None) -> Optional[Dict]:
    """Clear the author lease (a session crashed); its ticket goes back to approved."""
    by = _operator_by(operator, "dropping the author lease")
    with _locked(data):
        lease = _read_lease(data)
        if lease is None:
            return None
        _lease_path(data).unlink()
        try:
            t = _load(data, lease["ticket"])
            if t["status"] == "in_progress":
                t["status"] = "approved"
                _note(t, by, "author lease dropped", _now(now))
                _save(data, t)
        except TicketError:
            pass
        return lease


# ------------------------------------------------------------- the one author

def _hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _read_lease(data) -> Optional[Dict]:
    try:
        return json.loads(_lease_path(data).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_lease(data, ticket_id: int, token: str, now: float) -> float:
    expires = now + LEASE_TTL_SEC
    path = _lease_path(data)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(json.dumps({"ticket": ticket_id, "token_sha256": _hash(token), "taken": _stamp(now),
                               "expires": expires}) + "\n", encoding="utf-8")
    tmp.replace(path)
    return expires


def _holds(lease: Optional[Dict], ticket_id: int, token: Optional[str], now: float) -> bool:
    return bool(lease and token and lease.get("ticket") == ticket_id and lease.get("expires", 0) > now
                and lease.get("token_sha256") == _hash(token))


def _exhaust(t: Dict, now: float) -> None:
    t["status"] = "wontfix"
    t["closed_reason"] = "needs-human"
    _note(t, "host", "attempt budget used up (%d/%d): needs a human" % (t["attempts"], MAX_ATTEMPTS), now)


def claim(data, ticket_id, token: Optional[str] = None, now: Optional[float] = None,
          paths=None) -> Dict:
    """Become the single author of an approved ticket. Never waits.

    A new attempt is counted unless the caller already holds the lease (then this
    only extends it). Returns the ticket, the token to present later, attempts_left.
    Optional `paths` are repo-relative files this attempt will touch.
    """
    t_now = _now(now)
    norm_paths = _norm_paths(paths)
    with _locked(data):
        t = _load(data, ticket_id)
        tid = t["id"]
        lease = _read_lease(data)
        if _holds(lease, tid, token, t_now) and t["status"] == "in_progress":
            if norm_paths:
                t["paths"] = norm_paths
                _note(t, "agent", "paths: " + ", ".join(norm_paths), t_now)
                _save(data, t)
            expires = _write_lease(data, tid, token, t_now)
            return {"ticket": public(t), "token": token, "attempts_left": MAX_ATTEMPTS - t["attempts"],
                    "expires_in_sec": int(expires - t_now), "new_attempt": False}
        if t["status"] not in ("approved", "in_progress"):
            raise TicketError("ticket %d is %s; only an approved ticket can be worked on" % (tid, t["status"]))
        if lease and lease.get("expires", 0) > t_now:
            _note(t, "agent", "claim refused: author lock is held for ticket %s" % lease.get("ticket"), t_now)
            _save(data, t)
            raise TicketError("author lock is held for ticket %s until %s; not waiting (a note was left on ticket %d)"
                              % (lease.get("ticket"), _stamp(lease["expires"]), tid))
        if lease:  # expired: its session is gone
            try:
                stale = _load(data, lease["ticket"])
                if stale["status"] == "in_progress":
                    stale["status"] = "approved"
                    _note(stale, "host", "author lease expired", t_now)
                    if stale["id"] == tid:
                        t = stale
                    else:
                        _save(data, stale)
                        t = _load(data, tid)
            except TicketError:
                pass
        if t["attempts"] >= MAX_ATTEMPTS:
            _exhaust(t, t_now)
            _save(data, t)
            raise TicketError("ticket %d used up its %d attempts and is closed as wontfix (needs-human)" % (tid, MAX_ATTEMPTS))
        if norm_paths:
            leftover = _ship_blockers(data, {"paths": norm_paths})
            if leftover:
                _note(t, "agent", "claim refused: uncommitted leftover in %s" % ", ".join(leftover[:5]), t_now)
                _save(data, t)
                raise TicketError("claim refused: uncommitted leftover in %s; commit or revert before claiming"
                                  % ", ".join(leftover[:5]))
            t["paths"] = norm_paths
        t["attempts"] += 1
        t["status"] = "in_progress"
        new_token = secrets.token_hex(16)
        expires = _write_lease(data, tid, new_token, t_now)
        note = "claimed (attempt %d/%d)" % (t["attempts"], MAX_ATTEMPTS)
        if norm_paths:
            note += "; paths: " + ", ".join(norm_paths)
        _note(t, "agent", note, t_now)
        _save(data, t)
        return {"ticket": public(t), "token": new_token, "attempts_left": MAX_ATTEMPTS - t["attempts"],
                "expires_in_sec": int(expires - t_now), "new_attempt": True}


def add_note(data, ticket_id, text: str, token: Optional[str] = None, now: Optional[float] = None) -> Dict:
    """Leave a note. Anyone may; the author's note also keeps the lease alive."""
    t_now = _now(now)
    if not _txt(text).strip():
        raise TicketError("text is required")
    with _locked(data):
        t = _load(data, ticket_id)
        _note(t, "agent", text, t_now)
        _save(data, t)
        if _holds(_read_lease(data), t["id"], token, t_now):
            _write_lease(data, t["id"], token, t_now)
        return public(t)


def release(data, ticket_id, token: Optional[str], outcome: str, text: str = "", now: Optional[float] = None) -> Dict:
    """Give up the author lease. outcome: done | gate_failed | failed | abandoned."""
    t_now = _now(now)
    if outcome not in ("done", "gate_failed", "failed", "abandoned"):
        raise TicketError("outcome must be done, gate_failed, failed or abandoned")
    with _locked(data):
        t = _load(data, ticket_id)
        if not _holds(_read_lease(data), t["id"], token, t_now):
            raise TicketError("you do not hold the author lease for ticket %d (missing, wrong or expired token)" % t["id"])
        if outcome == "done":
            leftover = _ship_blockers(data, t)
            if leftover:
                raise TicketError("cannot mark done: uncommitted changes in %s" % ", ".join(leftover[:8]))
        _lease_path(data).unlink()
        advice = ""
        if _txt(text).strip():
            _note(t, "agent", "%s: %s" % (outcome, _txt(text)), t_now)
        if outcome == "done":
            t["status"] = "done"
            t["closed_reason"] = "done"
            _note(t, "agent", "done", t_now)
        else:
            if outcome == "gate_failed":
                t["gate_failures"] = t.get("gate_failures", 0) + 1
            t["status"] = "approved"
            if t["attempts"] >= MAX_ATTEMPTS:
                _exhaust(t, t_now)
                advice = "attempt budget used up: stop and tell the operator"
            elif outcome == "gate_failed" and t["gate_failures"] >= GATE_FAILURES_ADVICE:
                advice = "%d gate failures: change the approach or stop and ask the operator" % t["gate_failures"]
            else:
                advice = "%d attempt(s) left" % (MAX_ATTEMPTS - t["attempts"])
        _save(data, t)
        return {"ticket": public(t), "advice": advice}


# ------------------------------------------------------------------- reading

def get(data, ticket_id) -> Dict:
    return public(_load(data, ticket_id))


def list_tickets(data, status: Optional[str] = None) -> List[Dict]:
    """Ticket summaries, newest last."""
    rows = [t for t in _all(data) if status in (None, "", t.get("status"))]
    return [{k: t.get(k) for k in ("id", "title", "target", "status", "attempts", "gate_failures", "updated")}
            for t in rows]


# -------------------------------------------------------------- command line

def _data_dir() -> Path:
    return Path(os.environ.get("AGY_CHAT_DATA") or (Path(__file__).resolve().parent / "data"))


def _confirm_at_terminal(cmd: str, what: str) -> None:
    """The operator's commands need a person: a terminal, and the number typed back."""
    if not sys.stdin.isatty():
        raise TicketError("%s is for the operator at a terminal, and this shell has none. Do not run it yourself; "
                          "ask the operator." % cmd)
    sys.stdout.write("%s -- type %s to confirm: " % (cmd, what))
    sys.stdout.flush()
    if sys.stdin.readline().strip() != what:
        raise TicketError("not confirmed; nothing changed")


def main(argv: List[str]) -> int:
    cmd = argv[0] if argv else ""
    data = _data_dir()
    try:
        if cmd == "list":
            for r in list_tickets(data, argv[1] if len(argv) > 1 else None):
                print("%04d  %-11s attempts=%d/%d  %s  [%s]" % (r["id"], r["status"], r["attempts"], MAX_ATTEMPTS,
                                                              r["title"], r["target"]))
            return 0
        if cmd == "show" and len(argv) == 2:
            print(json.dumps(get(data, argv[1]), indent=1, ensure_ascii=False))
            return 0
        if cmd in ("approve", "decline", "reopen") and len(argv) == 2:
            shown = get(data, argv[1])
            print("ticket %04d [%s] %s (%s)" % (shown["id"], shown["status"], shown["title"], ", ".join(shown["evidence"])))
            _confirm_at_terminal("%s ticket %d" % (cmd, shown["id"]), str(shown["id"]))
            t = {"approve": approve, "decline": decline, "reopen": reopen}[cmd](data, argv[1], operator=OPERATOR_TTY)
            print("ticket %d is now %s" % (t["id"], t["status"]))
            return 0
        if cmd == "drop-lease":
            _confirm_at_terminal("drop-lease", "drop-lease")
            lease = drop_lease(data, operator=OPERATOR_TTY)
            print("lease dropped (ticket %s)" % lease["ticket"] if lease else "no lease")
            return 0
    except TicketError as e:
        print("tickets: %s" % e, file=sys.stderr)
        return 1
    print(__doc__.split("Command line (operator):", 1)[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
