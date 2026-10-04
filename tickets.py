"""Evolution tickets: how an observation becomes work (docs/plans/recursive-self-evolution.md §4.2-4.3).

Work on the host itself starts only from the operator's own words or from a
ticket the operator approved. A ticket must carry evidence that really exists,
has a small attempt budget, and each file can be worked on by one author at a time.

- Evidence is verified, not trusted: `event:<sid>#<line>` must be a line of that
  session's events.jsonl, `candidate:<epoch>` a line of candidates.jsonl.
- Same target, same ticket: a proposal for a target that already has an open
  ticket adds its evidence to it instead of creating a second one.
- Budget: at most MAX_ATTEMPTS attempts; after that the ticket is closed as
  `wontfix` with reason `needs-human`. Two gate failures in a row advise
  changing the approach or stopping.
- One author per file (LEASE_SCOPE_v1): `claim` takes a lease on the files it
  names (`leases.json`); a claim that names none takes every file. Two tickets
  whose files do not overlap run side by side (the runner rebases and gates its
  branch before it lands). Nobody waits: a busy claim records what blocks it
  (`blocked_by`), leaves a note and fails. Leases expire (LEASE_TTL_SEC), so a
  session that vanished does not block the work forever. A lease is identified
  by a random token that only the claimer holds (stored hashed).
- Owner: a ticket an agent opened to do itself (`ticket-quick start`) names its
  `owner`; nobody else may claim it until the operator hands it over (`disown`).
- Guards (pew/O): `release(done)` is refused while the repo's `run-tests.sh --fast` fails -- the backstop
  for a commit that skipped its hooks. The lease stays with the caller.
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
- Awaiting merge (AWAITING_MERGE_v1): work that passed its gates and review but may land only on
  the operator's word (Tier 2; docs/plans/multi-agent-worktree-delegation.md §9) waits as
  `awaiting_merge`. `await_merge` gives up the lease without spending an attempt, so other work is
  not blocked meanwhile; `merge_go` (operator) hands a lease back, again without an attempt, to
  whoever merges and releases `done`. If that lease lapses the ticket goes back to waiting; a failed
  release (e.g. main moved and the branch needs the gates again) makes it an ordinary approved ticket.
- Who (ACTOR_ATTRIBUTION_v1): callers may name the agent doing the work (`actor`, e.g.
  "claude-code", "grok", "chat-agent:agy" -- role ids, never a persona name or title); it is kept
  as `actor` (proposer), `worked_by`, `closed_by`,
  and notes read `agent:<actor>`. An operator decision relayed by an agent on the operator's word
  says so: `approved_by` = `operator (api) via <actor> <tool>`.

Standard library plus the core module `evolution`; the data directory is an
argument, nothing is read from the host.

Command line (operator):
  list [STATUS]      show tickets            show N       one ticket in full
  approve N          proposed -> approved    decline N    close as declined
  reopen N           a wontfix ticket gets a fresh budget
                     (decline also drops an awaiting_merge ticket's change)
  drop-lease [N]     clear ticket N's author lease, or all of them (after a crashed session)
  disown N           take the owner off a ticket so another agent may work on it
"""
from __future__ import annotations
import platform_compat

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import evolution

OPERATOR_TTY = "tty"          # the command line, at a terminal, after retyping the number
OPERATOR_CONFIRMED = "api"    # a caller that states outright that it acts for the operator
OPERATOR_UI = "ui"            # the operator's own `/ticket ...` command in the host's chat page (same-origin POST)
MAX_ATTEMPTS = 3
UNAVAILABLE_REFUNDS = 3    # attempts given back when no brain answered (quota, limit, timeout); then they count
GATE_FAILURES_ADVICE = 2
LEASE_TTL_SEC = 1800
MAX_PROPOSED = 10          # unreviewed proposals; more is a runaway, not a review
MAX_EVIDENCE = 20
GUARD_TIMEOUT_SEC = 300    # run-tests.sh --fast before `done` (pew/O); about 50 s on this NAS
MAX_NOTES = 40
MAX_PATHS = 20
OPEN_STATES = ("proposed", "approved", "in_progress", "awaiting_merge")
CLOSED_STATES = ("done", "wontfix", "declined")
_SID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class TicketError(Exception):
    """A refusal the caller can show as is."""


# ------------------------------------------------------------------ storage

def tickets_dir(data) -> Path:
    return Path(data) / "workspace" / "skill-observations" / "tickets"


def _lease_path(data) -> Path:
    """The single lease from before LEASE_SCOPE_v1; read once and moved into leases.json."""
    return tickets_dir(data) / "author.lease"


def _leases_path(data) -> Path:
    return tickets_dir(data) / "leases.json"


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


def _operator_by(operator: Optional[str], what: str, on_behalf: Optional[str] = None) -> str:
    """Who is asking, for the record. Refuses a call that does not say. `on_behalf`: the agent and tool
    that relayed the operator's decision (e.g. "claude-code ticket-quick")."""
    if operator not in (OPERATOR_TTY, OPERATOR_CONFIRMED, OPERATOR_UI):
        raise TicketError("%s is for the operator, at a terminal: run `python3 tickets.py ...` yourself, "
                          "or ask the operator. Agents do not decide tickets." % what)
    by = "operator (%s)" % operator
    if on_behalf and _txt(on_behalf).strip():
        via = _txt(on_behalf).strip()[:80]
        if not re.fullmatch(r"[\x20-\x7e]+", via):  # role ids and tool names only (NAME_NEUTRAL_v1)
            raise TicketError("on_behalf must be plain ASCII (role id and tool), got %r" % via[:40])
        by += " via %s" % via
    return by


def _clean_actor(actor: Optional[str]) -> Optional[str]:
    try:
        return evolution.role_id(actor) or None
    except ValueError as e:
        raise TicketError(str(e))


def _agent_by(actor: Optional[str] = None, t: Optional[Dict] = None) -> str:
    """Note author: `agent:<actor>`, falling back to who works on the ticket, then plain `agent`."""
    a = _clean_actor(actor) or (t or {}).get("worked_by")
    return "agent:%s" % a if a else "agent"


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
    platform_compat.write_text(tmp, json.dumps(t, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
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
    m = re.match(r"^log:(fp|rid):([0-9a-f]+)$", ref)
    if m:
        kind, val = m.group(1), m.group(2)
        if len(val) != _LOG_ID_LEN[kind]:
            raise TicketError("bad evidence reference: %s" % ref)
        if _in_host_log(data, kind, val):
            return
        raise TicketError("evidence not found: %s" % ref)
    raise TicketError("evidence must be event:<session>#<line>, candidate:<epoch>, log:fp:<fp> or log:rid:<rid>, "
                      "got: %s" % ref[:60])


# Host log evidence (OBSLOG_v1, docs/LOGGING.md): an error fingerprint or a request id that is in
# logs/events.jsonl (or its rotations) next to the data directory. Read as plain JSON lines, so the
# core stays free of the log layer; a missing log means "not found", never an error.
_LOG_ID_LEN = {"fp": 10, "rid": 12}


def _in_host_log(data, kind: str, val: str) -> bool:
    logs = Path(data).resolve().parent / "logs"
    needle = '"%s":"%s"' % (kind, val)
    for name in ["events.jsonl"] + ["events.jsonl.%d" % i for i in range(1, 10)]:
        try:
            with open(str(logs / name), encoding="utf-8", errors="replace") as f:
                for line in f:
                    if needle not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    got = (rec.get("err") or {}).get("fp") if kind == "fp" else rec.get("rid")
                    if got == val:
                        return True
        except OSError:
            continue
    return False


# ---------------------------------------------------------------- ship-gate

def _norm_paths(paths, data=None) -> List[str]:
    """Repo-relative paths. With `data`, a path that starts with the repo's own folder names (e.g. `<dir>/<repo>/x`
    written from a parent folder) is cut to `x`, so leases compare and the ship gate asks git the right thing."""
    if not paths:
        return []
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list):
        raise TicketError("paths must be a list of repo-relative files")
    root = _repo_root(data) if data is not None else None
    tails = ["/".join(root.parts[-k:]) + "/" for k in range(len(root.parts) - 1, 0, -1)] if root else []
    out = []
    for raw in paths[:MAX_PATHS]:
        s = _txt(raw).strip().replace("\\", "/")
        if not s or s.startswith("/") or ".." in s.split("/"):
            raise TicketError("path must be repo-relative, got: %s" % s[:60])
        if tails and not (root / s).exists():
            s = next((s[len(t):] for t in tails if s.startswith(t) and len(s) > len(t)), s)
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


def _repo_root(data) -> Optional[Path]:
    """The engine repository a ticket's paths and guards are judged in. For the install's own data folder that is the
    engine checkout this module runs from: since the data moved out (~/.pe, uds) the data folder's git root is
    whatever encloses it -- a home folder that is a repo -- so `AGENTS.md` was checked as ~/AGENTS.md and the guard
    run found no runner and passed every `done` (split/H, #618). Any other folder (a test's fixture repo, a data
    folder inside the engine) is judged by its own git root, as before."""
    d = Path(data).resolve()
    if d == _data_dir().resolve():
        code = _git_root(_code_root())
        if code is not None:
            return code
    return _git_root(d)


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


def _guard_failure(data) -> str:
    """Why the repo's guard tests fail, or "" (pew/O: the backstop for a commit that skipped its hooks). Runs
    `run-tests.sh --fast` on the committed state (HEAD) of the engine repo (`_repo_root`); nothing to check without a
    git root or that script."""
    root = _repo_root(data)
    if root is None:
        return ""
    # #371/#387: run from the server, the guards inherited the live install's settings (CHATBOT_DATA, CHATBOT_ROOT,
    # ...) and judged the throwaway copy against the live folders -- every approve from the page failed, from a shell
    # it passed. The guards run as in a developer's shell: no instance settings.
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")
           and not k.startswith(("CHATBOT_", "PE_", "PRIVATEENGINE_", "AGY_CHAT_"))}
    # Only the engine's own repo is judged. A data folder inside some other git repo (a home folder that is itself a
    # repo: ~/.pe, or a test's temp dir under ~/tmp) used to get a worktree of that whole repo before the missing
    # runner was noticed -- 6 s vs 108 s for test_tickets (test-suite-speed, 2026-09-28).
    if not (root / "run-tests.sh").is_file() and subprocess.run(
            ["git", "cat-file", "-e", "HEAD:run-tests.sh"], cwd=str(root), env=env, capture_output=True).returncode:
        return ""
    # Judge what is committed (HEAD), not the shared working tree: other agents' unfinished work must not refuse
    # this ticket's `done` (pew/Q). A throwaway worktree at HEAD; the working tree only when HEAD is missing.
    base = Path.home() / ".cache" / "chatbot-release-snapshot"
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=str(base)))
    tree = tmp / "tree"
    added = subprocess.run(["git", "worktree", "add", "--detach", "--quiet", str(tree), "HEAD"], cwd=str(root),
                           env=env, capture_output=True, text=True)
    where = tree if added.returncode == 0 else root
    try:
        runner = where / "run-tests.sh"
        if not runner.is_file():
            return ""
        r = subprocess.run(["bash", str(runner), "--fast"], cwd=str(where), env=env, capture_output=True, text=True,
                           timeout=GUARD_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return "guard tests timed out after %ds" % GUARD_TIMEOUT_SEC
    finally:
        if added.returncode == 0:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=str(root), env=env, capture_output=True)
        shutil.rmtree(str(tmp), ignore_errors=True)
    if r.returncode == 0:
        return ""
    failed = [l for l in r.stdout.splitlines() if l.startswith("failed:")]
    return failed[-1] if failed else "run-tests.sh --fast exited %d" % r.returncode


def is_content(data, paths) -> bool:
    """CONTENT_WORK_v1 (plan dlg/E): every path is user data -- under the data folder: a picture for the gallery, a
    note, a character file. Content is not code: no guard tests and no commit stand before its done (#371 was one
    picture and went through the whole code pipeline). False when the data folder is the repo itself (no line)."""
    rels = [p for p in (paths or []) if p]
    d = Path(data).resolve()
    root = _git_root(data)
    if not rels or root is None or root == d:
        return False
    for p in rels:
        q = Path(p)
        full = (q if q.is_absolute() else root / q).resolve()
        if full != d and d not in full.parents:
            return False
    return True


def _ship_blockers(data, t: Dict) -> List[str]:
    """Uncommitted paths that block `done`. Empty when there is no git or no paths."""
    rels = _paths_of(t)
    root = _repo_root(data)
    if not rels or root is None:
        return []
    return _porcelain(root, rels)


# ---------------------------------------------------------------- proposals

def propose(data, title: str, target: str, evidence: List[str], now: Optional[float] = None,
            actor: Optional[str] = None) -> Tuple[Dict, bool]:
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
                _note(t, _agent_by(actor), "proposal merged (+%d evidence)" % len(added), t_now)
                _save(data, t)
                return public(t), True
        if sum(1 for t in tickets if t.get("status") == "proposed") >= MAX_PROPOSED:
            raise TicketError("%d proposals are waiting for the operator; do not add more" % MAX_PROPOSED)
        ticket = {"id": max([x["id"] for x in tickets] + [0]) + 1, "title": title, "target": tgt,
                  "status": "proposed", "attempts": 0, "gate_failures": 0, "evidence": refs, "notes": [],
                  "created": _stamp(t_now), "updated": _stamp(t_now)}
        if _clean_actor(actor):
            ticket["actor"] = _clean_actor(actor)
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

def approve(data, ticket_id, now: Optional[float] = None, operator: Optional[str] = None,
                on_behalf: Optional[str] = None) -> Dict:
    by = _operator_by(operator, "approving a ticket", on_behalf)
    with _locked(data):
        t = _load(data, ticket_id)
        if t["status"] != "proposed":
            raise TicketError("ticket %d is %s, not proposed" % (t["id"], t["status"]))
        t["status"] = "approved"
        t["approved_at"] = _stamp(_now(now))
        t["approved_by"] = by
        _note(t, by, "approved", _now(now))
        _save(data, t)
        return public(t)


def decline(data, ticket_id, now: Optional[float] = None, operator: Optional[str] = None,
                on_behalf: Optional[str] = None) -> Dict:
    by = _operator_by(operator, "declining a ticket", on_behalf)
    with _locked(data):
        t = _load(data, ticket_id)
        if t["status"] not in ("proposed", "approved", "awaiting_merge"):
            raise TicketError("ticket %d is %s" % (t["id"], t["status"]))
        t["status"] = "declined"
        t["closed_reason"] = "declined"
        t.pop("merge_pending", None)
        _note(t, by, "declined", _now(now))
        _save(data, t)
        return public(t)


def reopen(data, ticket_id, now: Optional[float] = None, operator: Optional[str] = None,
               on_behalf: Optional[str] = None) -> Dict:
    """A wontfix ticket the operator has looked at gets a fresh budget."""
    by = _operator_by(operator, "reopening a ticket", on_behalf)
    with _locked(data):
        t = _load(data, ticket_id)
        if t["status"] != "wontfix":
            raise TicketError("ticket %d is %s, not wontfix" % (t["id"], t["status"]))
        t.update(status="approved", attempts=0, gate_failures=0)
        t.pop("closed_reason", None)
        _note(t, by, "reopened with a fresh budget", _now(now))
        _save(data, t)
        return public(t)


def drop_lease(data, now: Optional[float] = None, operator: Optional[str] = None,
               ticket_id=None) -> Optional[Dict]:
    """Clear ticket `ticket_id`'s author lease, or every lease when None (a session crashed); the ticket goes back
    to approved. Returns the (last) lease dropped."""
    by = _operator_by(operator, "dropping the author lease")
    with _locked(data):
        leases = _read_leases(data)
        gone = [x for x in leases if ticket_id is None or x.get("ticket") == int(ticket_id)]
        if not gone:
            return None
        _write_leases(data, [x for x in leases if x not in gone])
        for lease in gone:
            try:
                t = _load(data, lease["ticket"])
                if t["status"] == "in_progress":
                    t["status"] = _unleased_status(t)
                    _note(t, by, "author lease dropped", _now(now))
                    _save(data, t)
            except TicketError:
                pass
        return gone[-1]


def disown(data, ticket_id, now: Optional[float] = None, operator: Optional[str] = None,
           on_behalf: Optional[str] = None) -> Dict:
    """The operator hands an owned ticket over: anyone may claim it afterwards."""
    by = _operator_by(operator, "handing a ticket over", on_behalf)
    with _locked(data):
        t = _load(data, ticket_id)
        owner = t.pop("owner", None)
        if not owner:
            raise TicketError("ticket %d has no owner" % t["id"])
        if t["status"] == "in_progress":
            raise TicketError("ticket %d is being worked on by %s; wait for it to stop" % (t["id"], owner))
        _note(t, by, "handed over (was %s's)" % owner, _now(now))
        _save(data, t)
        return public(t)


def set_owner(data, ticket_id, actor: str, now: Optional[float] = None) -> Dict:
    """An agent that opened a ticket to do itself marks it as its own (`ticket-quick start`). Only an unowned,
    open ticket; the proposer and the owner must be the same agent."""
    who = _clean_actor(actor)
    if not who:
        raise TicketError("say who owns it (actor)")
    with _locked(data):
        t = _load(data, ticket_id)
        if t.get("owner") and t["owner"] != who:
            raise TicketError("ticket %d is %s's" % (t["id"], t["owner"]))
        if t["status"] not in ("proposed", "approved", "in_progress"):
            raise TicketError("ticket %d is %s" % (t["id"], t["status"]))
        if t.get("actor") and t["actor"] != who:
            raise TicketError("ticket %d was proposed by %s" % (t["id"], t["actor"]))
        if t.get("owner") != who:
            t["owner"] = who
            _note(t, _agent_by(who), "owner: %s" % who, _now(now))
            _save(data, t)
        return public(t)


# ------------------------------------------------------------- one author per file

def _hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _read_leases(data) -> List[Dict]:
    """Every lease, live or expired: {ticket, token_sha256, taken, expires, paths, actor}. `paths` [] = every file.
    The single author.lease from before LEASE_SCOPE_v1 is moved in on first read (under the store lock)."""
    try:
        leases = list(json.loads(_leases_path(data).read_text(encoding="utf-8")).get("leases") or [])
    except (OSError, ValueError, AttributeError):
        leases = []
    old = _lease_path(data)
    if old.exists():
        try:
            lease = json.loads(old.read_text(encoding="utf-8"))
            if not any(x.get("ticket") == lease.get("ticket") for x in leases):
                try:
                    lease.setdefault("paths", _load(data, lease["ticket"]).get("paths") or [])
                except (TicketError, KeyError):
                    lease.setdefault("paths", [])
                leases.append(lease)
            _write_leases(data, leases)
        except (OSError, ValueError):
            pass
        try:
            old.unlink()
        except OSError:
            pass
    return leases


def _write_leases(data, leases: List[Dict]) -> None:
    path = _leases_path(data)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    platform_compat.write_text(tmp, json.dumps({"leases": leases}, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_lease(data, ticket_id=None) -> Optional[Dict]:
    """Ticket `ticket_id`'s lease (live or expired), or with None any one lease; None when there is none."""
    for lease in _read_leases(data):
        if ticket_id is None or lease.get("ticket") == int(ticket_id):
            return lease
    return None


def _write_lease(data, ticket_id: int, token: str, now: float, paths: Optional[List[str]] = None,
                 actor: Optional[str] = None) -> float:
    """Take or renew ticket_id's lease. `paths` None keeps the files it already had."""
    expires = now + LEASE_TTL_SEC
    leases = _read_leases(data)
    mine = next((x for x in leases if x.get("ticket") == ticket_id), None)
    lease = {"ticket": ticket_id, "token_sha256": _hash(token), "taken": _stamp(now), "expires": expires,
             "paths": list(paths if paths is not None else (mine or {}).get("paths") or []),
             "actor": _clean_actor(actor) or (mine or {}).get("actor") or ""}
    _write_leases(data, [x for x in leases if x.get("ticket") != ticket_id] + [lease])
    return expires


def _drop_own_lease(data, ticket_id: int) -> None:
    _write_leases(data, [x for x in _read_leases(data) if x.get("ticket") != ticket_id])


def _holds(lease: Optional[Dict], ticket_id: int, token: Optional[str], now: float) -> bool:
    return bool(lease and token and lease.get("ticket") == ticket_id and lease.get("expires", 0) > now
                and lease.get("token_sha256") == _hash(token))


def holds(data, ticket_id, token: Optional[str], now: Optional[float] = None) -> bool:
    """Does `token` hold ticket_id's live lease?"""
    tid = int(ticket_id)
    return _holds(_read_lease(data, tid), tid, token, _now(now))


def _overlap(a: List[str], b: List[str]) -> List[str]:
    """The files two leases share: an empty list of paths means every file; a folder covers what is in it."""
    if not a or not b:
        return list(a or b or ["*"])
    out = []
    for x in a:
        for y in b:
            xs, ys = x.rstrip("/"), y.rstrip("/")
            if xs == ys or xs.startswith(ys + "/") or ys.startswith(xs + "/"):
                out.append(x if len(xs) >= len(ys) else y)
    return out


def _conflicts(data, ticket_id: int, paths: List[str], now: float) -> Optional[Dict]:
    """The first live lease of another ticket that shares files with `paths`, as {ticket, paths, until}; expired
    leases are cleared on the way (their tickets go back to waiting)."""
    leases = _read_leases(data)
    live = []
    for lease in leases:
        if lease.get("expires", 0) > now:
            live.append(lease)
            continue
        try:
            stale = _load(data, lease["ticket"])
            if stale["status"] == "in_progress":
                stale["status"] = _unleased_status(stale)
                _note(stale, "host", "author lease expired", now)
                _save(data, stale)
        except (TicketError, KeyError):
            pass
    if len(live) != len(leases):
        _write_leases(data, live)
    for lease in live:
        if lease.get("ticket") == ticket_id:
            continue
        shared = _overlap(paths, lease.get("paths") or [])
        if shared:
            return {"ticket": lease.get("ticket"), "paths": shared[:5], "until": _stamp(lease["expires"]),
                    "actor": lease.get("actor") or ""}
    return None


def _blocked(data, t: Dict, by: str, what: str, block: Dict, now: float) -> TicketError:
    """Record on `t` what blocks it and return the error to raise."""
    t["blocked_by"] = dict(block, at=_stamp(now))
    files = ", ".join(block["paths"])
    _note(t, by, "%s refused: author lock is held for ticket %s (%s)" % (what, block["ticket"], files), now)
    _save(data, t)
    return TicketError("author lock is held for ticket %s on %s until %s; not waiting (a note was left on ticket %d)"
                       % (block["ticket"], files, block["until"], t["id"]))


def leases(data, now: Optional[float] = None) -> List[Dict]:
    """The live leases, for the page: ticket, files, until, who (no token hashes)."""
    t_now = _now(now)
    return [{"ticket": x.get("ticket"), "paths": x.get("paths") or [], "until": _stamp(x["expires"]),
             "actor": x.get("actor") or ""} for x in _read_leases(data) if x.get("expires", 0) > t_now]


def _unleased_status(t: Dict) -> str:
    """Where an in_progress ticket goes when its lease is gone: back to waiting for the merge if it was."""
    return "awaiting_merge" if t.get("merge_pending") else "approved"


def _exhaust(t: Dict, now: float) -> None:
    t["status"] = "wontfix"
    t["closed_reason"] = "needs-human"
    _note(t, "host", "attempt budget used up (%d/%d): needs a human" % (t["attempts"], MAX_ATTEMPTS), now)


def claim(data, ticket_id, token: Optional[str] = None, now: Optional[float] = None,
          paths=None, actor: Optional[str] = None) -> Dict:
    """Become the author of an approved ticket for the files in `paths` (none = every file). Never waits.

    A new attempt is counted unless the caller already holds the lease (then this
    only extends it). Returns the ticket, the token to present later, attempts_left.
    Optional `paths` are repo-relative files this attempt will touch.
    """
    t_now = _now(now)
    norm_paths = _norm_paths(paths, data)
    with _locked(data):
        t = _load(data, ticket_id)
        tid = t["id"]
        if _holds(_read_lease(data, tid), tid, token, t_now) and t["status"] == "in_progress":
            if norm_paths:
                block = _conflicts(data, tid, norm_paths, t_now)
                if block:
                    raise _blocked(data, t, _agent_by(actor, t), "paths", block, t_now)
                t["paths"] = norm_paths
                _note(t, _agent_by(actor, t), "paths: " + ", ".join(norm_paths), t_now)
                _save(data, t)
            expires = _write_lease(data, tid, token, t_now, paths=norm_paths or None, actor=actor)
            return {"ticket": public(t), "token": token, "attempts_left": MAX_ATTEMPTS - t["attempts"],
                    "expires_in_sec": int(expires - t_now), "new_attempt": False}
        if t["status"] not in ("approved", "in_progress"):
            raise TicketError("ticket %d is %s; only an approved ticket can be worked on" % (tid, t["status"]))
        who = _clean_actor(actor)
        if t.get("owner") and who != t["owner"]:
            _note(t, _agent_by(actor), "claim refused: the ticket is %s's" % t["owner"], t_now)
            _save(data, t)
            raise TicketError("ticket %d is %s's; the operator can hand it over (disown) first" % (tid, t["owner"]))
        block = _conflicts(data, tid, norm_paths, t_now)    # also clears expired leases
        t = _load(data, tid)                                  # an expired lease of this very ticket changed it
        if block:
            raise _blocked(data, t, _agent_by(actor), "claim", block, t_now)
        stale = _read_lease(data, tid)                        # this ticket's own lease, held by a stranger
        if stale and stale.get("expires", 0) > t_now:
            block = {"ticket": tid, "paths": stale.get("paths") or ["*"], "until": _stamp(stale["expires"]),
                     "actor": stale.get("actor") or ""}
            raise _blocked(data, t, _agent_by(actor), "claim", block, t_now)
        if t["attempts"] >= MAX_ATTEMPTS:
            _exhaust(t, t_now)
            _save(data, t)
            raise TicketError("ticket %d used up its %d attempts and is closed as wontfix (needs-human)" % (tid, MAX_ATTEMPTS))
        if norm_paths:
            # user data is never committed (CONTENT_WORK_v1): uncommitted files there are not someone's leftover
            leftover = [] if is_content(data, norm_paths) else _ship_blockers(data, {"paths": norm_paths})
            if leftover:
                _note(t, _agent_by(actor), "claim refused: uncommitted leftover in %s" % ", ".join(leftover[:5]), t_now)
                _save(data, t)
                raise TicketError("claim refused: uncommitted leftover in %s; commit or revert before claiming"
                                  % ", ".join(leftover[:5]))
            t["paths"] = norm_paths
        t["attempts"] += 1
        t["status"] = "in_progress"
        t.pop("blocked_by", None)
        if who:
            t["worked_by"] = who
        new_token = secrets.token_hex(16)
        expires = _write_lease(data, tid, new_token, t_now, paths=norm_paths, actor=who)
        note = "claimed (attempt %d/%d)" % (t["attempts"], MAX_ATTEMPTS)
        if norm_paths:
            note += "; paths: " + ", ".join(norm_paths)
        _note(t, _agent_by(actor, t), note, t_now)
        _save(data, t)
        return {"ticket": public(t), "token": new_token, "attempts_left": MAX_ATTEMPTS - t["attempts"],
                "expires_in_sec": int(expires - t_now), "new_attempt": True}


def widen(data, ticket_id, token: Optional[str], paths, now: Optional[float] = None,
          actor: Optional[str] = None) -> Dict:
    """Add files to the ticket the caller holds (TICKET_WIDEN_v1). The alternative -- give the ticket up and open a
    new one -- leaves the old one approved and open, and only the operator may close it (#382). The added files pass
    the same checks as a claim (another live lease, uncommitted leftover); the lease is renewed, no attempt counted,
    and the note says what was added so the operator sees the scope grow."""
    t_now = _now(now)
    asked = _norm_paths(paths, data)
    if not asked:
        raise TicketError("paths are required")
    with _locked(data):
        t = _load(data, ticket_id)
        tid = t["id"]
        if not (_holds(_read_lease(data, tid), tid, token, t_now) and t["status"] == "in_progress"):
            raise TicketError("you do not hold ticket %d (missing, wrong or expired token); only its author widens it"
                              % tid)
        have = list(t.get("paths") or [])
        if not have:
            raise TicketError("ticket %d already covers every file" % tid)
        added = [p for p in asked if not any(p == h or p.startswith(h.rstrip("/") + "/") for h in have)]
        if added:
            block = _conflicts(data, tid, added, t_now)
            if block:
                raise _blocked(data, t, _agent_by(actor, t), "widen", block, t_now)
            leftover = [] if is_content(data, added) else _ship_blockers(data, {"paths": added})
            if leftover:
                raise TicketError("widen refused: uncommitted leftover in %s; commit or revert before adding it"
                                  % ", ".join(leftover[:5]))
            t["paths"] = have + added
            _note(t, _agent_by(actor, t), "paths widened: + " + ", ".join(added), t_now)
            _save(data, t)
        expires = _write_lease(data, tid, token, t_now, paths=t["paths"], actor=actor)
        return {"ticket": public(t), "added": added, "expires_in_sec": int(expires - t_now)}


def add_note(data, ticket_id, text: str, token: Optional[str] = None, now: Optional[float] = None,
             actor: Optional[str] = None) -> Dict:
    """Leave a note. Anyone may; the author's note also keeps the lease alive."""
    t_now = _now(now)
    if not _txt(text).strip():
        raise TicketError("text is required")
    with _locked(data):
        t = _load(data, ticket_id)
        mine = _holds(_read_lease(data, t["id"]), t["id"], token, t_now)
        _note(t, _agent_by(actor) if actor or not mine else _agent_by(None, t), text, t_now)
        _save(data, t)
        if mine:
            _write_lease(data, t["id"], token, t_now)
        return public(t)


def release(data, ticket_id, token: Optional[str], outcome: str, text: str = "", now: Optional[float] = None,
            actor: Optional[str] = None) -> Dict:
    """Give up the author lease. outcome: done | gate_failed | failed | abandoned | unavailable (no brain answered:
    the attempt is given back, at most UNAVAILABLE_REFUNDS times per ticket -- DELEGATION_HARDENING_v1) | paused
    (the worker asked for files outside its scope, NEED_PATH_v1: given back; only the operator's allow resumes it)."""
    t_now = _now(now)
    if outcome not in ("done", "gate_failed", "failed", "abandoned", "unavailable", "paused"):
        raise TicketError("outcome must be done, gate_failed, failed, abandoned, unavailable or paused")
    content = outcome == "done" and is_content(data, _paths_of(_load(data, ticket_id)))
    if outcome == "done" and not content:
        guard = _guard_failure(data)   # before the lock: ~50 s must not hold up everyone else's ticket calls
        if guard:
            raise TicketError("cannot mark done: guard tests fail (%s); fix them and release again, "
                              "the lease is still yours" % guard)
    with _locked(data):
        t = _load(data, ticket_id)
        if not _holds(_read_lease(data, t["id"]), t["id"], token, t_now):
            raise TicketError("you do not hold the author lease for ticket %d (missing, wrong or expired token)" % t["id"])
        if outcome == "done" and not content:
            leftover = _ship_blockers(data, t)
            if leftover:
                raise TicketError("cannot mark done: uncommitted changes in %s" % ", ".join(leftover[:8]))
        _drop_own_lease(data, t["id"])
        advice = ""
        if _txt(text).strip():
            _note(t, _agent_by(actor, t), "%s: %s" % (outcome, _txt(text)), t_now)
        if outcome == "done":
            t["status"] = "done"
            t["closed_reason"] = "done"
            t.pop("merge_pending", None)
            if _clean_actor(actor) or t.get("worked_by"):
                t["closed_by"] = _clean_actor(actor) or t.get("worked_by")
            _note(t, _agent_by(actor, t), "done", t_now)
        else:
            if outcome == "gate_failed":
                t["gate_failures"] = t.get("gate_failures", 0) + 1
            if outcome == "paused" and t["attempts"] > 0:
                t["attempts"] -= 1
                _note(t, "host", "waiting for the operator to allow more paths: attempt given back", t_now)
            if outcome == "unavailable" and t.get("unavailable", 0) < UNAVAILABLE_REFUNDS and t["attempts"] > 0:
                t["unavailable"] = t.get("unavailable", 0) + 1
                t["attempts"] -= 1
                _note(t, "host", "no brain answered: attempt given back (%d/%d)" % (t["unavailable"], UNAVAILABLE_REFUNDS),
                      t_now)
            t.pop("merge_pending", None)
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


def await_merge(data, ticket_id, token: Optional[str], text: str = "", now: Optional[float] = None,
                actor: Optional[str] = None) -> Dict:
    """The author's work passed its gates and review; it lands only on the operator's word. Gives up the
    lease without spending or refunding an attempt; the ticket waits as `awaiting_merge`."""
    t_now = _now(now)
    with _locked(data):
        t = _load(data, ticket_id)
        if not _holds(_read_lease(data, t["id"]), t["id"], token, t_now) or t["status"] != "in_progress":
            raise TicketError("you do not hold the author lease for ticket %d (missing, wrong or expired token)" % t["id"])
        _drop_own_lease(data, t["id"])
        t["status"] = "awaiting_merge"
        t["merge_pending"] = True
        _note(t, _agent_by(actor, t), "awaiting merge" + (": " + _txt(text) if _txt(text).strip() else ""), t_now)
        _save(data, t)
        return public(t)


def merge_go(data, ticket_id, now: Optional[float] = None, operator: Optional[str] = None,
             on_behalf: Optional[str] = None, actor: Optional[str] = None) -> Dict:
    """The operator lets an awaiting_merge ticket land: the author lease comes back without a new attempt,
    for whoever merges and then releases `done`. Never waits for a busy lease."""
    by = _operator_by(operator, "letting a change land", on_behalf)
    t_now = _now(now)
    with _locked(data):
        t = _load(data, ticket_id)
        if t["status"] != "awaiting_merge":
            raise TicketError("ticket %d is %s, not awaiting_merge" % (t["id"], t["status"]))
        paths = _paths_of(t)
        block = _conflicts(data, t["id"], paths, t_now)
        if block:
            raise _blocked(data, t, by, "merge", block, t_now)
        t["status"] = "in_progress"
        t["merge_approved_by"] = by
        t.pop("blocked_by", None)
        if _clean_actor(actor):
            t["worked_by"] = _clean_actor(actor)
        token = secrets.token_hex(16)
        expires = _write_lease(data, t["id"], token, t_now, paths=paths, actor=actor)
        _note(t, by, "merge approved", t_now)
        _save(data, t)
        return {"ticket": public(t), "token": token, "expires_in_sec": int(expires - t_now)}


def rework(data, ticket_id, text: str, now: Optional[float] = None, operator: Optional[str] = None,
           on_behalf: Optional[str] = None, actor: Optional[str] = None) -> Dict:
    """The operator sends waiting work back with a comment (PD_PLAN_v1): a new attempt on the same ticket,
    with the author lease for whoever reworks it. Refused when the attempt budget is used up."""
    by = _operator_by(operator, "sending work back", on_behalf)
    t_now = _now(now)
    if not _txt(text).strip():
        raise TicketError("say what to change")
    with _locked(data):
        t = _load(data, ticket_id)
        if t["status"] != "awaiting_merge":
            raise TicketError("ticket %d is %s, not awaiting_merge" % (t["id"], t["status"]))
        if t["attempts"] >= MAX_ATTEMPTS:
            raise TicketError("ticket %d used up its %d attempts; land it, drop it, or reopen it at a terminal"
                              % (t["id"], MAX_ATTEMPTS))
        paths = _paths_of(t)
        block = _conflicts(data, t["id"], paths, t_now)
        if block:
            raise _blocked(data, t, by, "rework", block, t_now)
        t["status"] = "in_progress"
        t["attempts"] += 1
        t.pop("merge_pending", None)
        t.pop("blocked_by", None)
        if _clean_actor(actor):
            t["worked_by"] = _clean_actor(actor)
        token = secrets.token_hex(16)
        expires = _write_lease(data, t["id"], token, t_now, paths=paths, actor=actor)
        _note(t, by, "sent back (attempt %d/%d): %s" % (t["attempts"], MAX_ATTEMPTS, _txt(text)[:300]), t_now)
        _save(data, t)
        return {"ticket": public(t), "token": token, "expires_in_sec": int(expires - t_now)}


# ------------------------------------------------------------------- reading

def get(data, ticket_id) -> Dict:
    return public(_load(data, ticket_id))


def list_tickets(data, status: Optional[str] = None) -> List[Dict]:
    """Ticket summaries, newest last."""
    rows = [t for t in _all(data) if status in (None, "", t.get("status"))]
    return [{k: t.get(k) for k in ("id", "title", "target", "status", "attempts", "gate_failures", "updated")}
            for t in rows]


# -------------------------------------------------------------- command line

def _code_root() -> Path:
    """Same root host_config.ROOT uses (CHATBOT_ROOT, else AGY_CHAT_ROOT, else this file's directory)."""
    for k in ("CHATBOT_ROOT", "AGY_CHAT_ROOT"):
        if os.environ.get(k):
            return Path(os.environ[k])
    return Path(__file__).resolve().parent



def _pinned_chatbot_data(root: Path) -> str:
    """Dev pin file (data-pin.env) used only when no DATA_ENV variable is set. Literal CHATBOT_DATA only;
    a value with $ is ignored so this reader and chatbot-ctl.sh (which sources the file) cannot disagree."""
    try:
        lines = (Path(root) / "data-pin.env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, sep, val = line.partition("=")
        if not sep or key.strip() != "CHATBOT_DATA":
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        if val and "$" not in val:
            return val
        return ""
    return ""

def _data_dir() -> Path:
    """Same order as host_config.DATA_ENV (a core module may not import host_config; test_data_paths keeps them equal).
    LIVE_DATA_GUARD_v1, as host_config.test_run_outside_runner: a test process run-tests.sh did not start never
    gets an install's data."""
    a0 = (sys.argv[0] if sys.argv else "") or ""
    if os.environ.get("CHATBOT_TEST_RUNNER") != "1" and (
            "-m unittest" in a0 or os.path.basename(a0).startswith(("pytest", "py.test"))):
        return _code_root() / "data"
    for k in ("CHATBOT_DATA", "PE_HOME", "PRIVATEENGINE_HOME", "AGY_CHAT_DATA"):
        if os.environ.get(k):
            return Path(os.environ[k])
    pinned = _pinned_chatbot_data(_code_root())
    if pinned:
        return Path(pinned)
    return Path(os.environ.get("HOME") or Path.home()) / ".pe"


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
        if cmd == "drop-lease" and len(argv) <= 2:
            _confirm_at_terminal("drop-lease", "drop-lease")
            lease = drop_lease(data, operator=OPERATOR_TTY, ticket_id=argv[1] if len(argv) == 2 else None)
            print("lease dropped (ticket %s)" % lease["ticket"] if lease else "no lease")
            return 0
        if cmd == "disown" and len(argv) == 2:
            _confirm_at_terminal("disown ticket %s" % argv[1], str(argv[1]))
            t = disown(data, argv[1], operator=OPERATOR_TTY)
            print("ticket %d has no owner now" % t["id"])
            return 0
    except TicketError as e:
        print("tickets: %s" % e, file=sys.stderr)
        return 1
    print(__doc__.split("Command line (operator):", 1)[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
