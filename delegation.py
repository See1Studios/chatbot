"""Worktree delegation, host side (docs/plans/multi-agent-worktree-delegation.md §9-10, PD_PLAN_v1).

The chatbot is the PD. The operator proposes; the PD (the chat agent, `delegate` tool) submits a plan:
tasks for its expert characters (`characters/<id>/`, by role). Nothing runs until the operator says so, and
nothing lands until the operator says so again:

  plan (awaiting_go) -> [실행] go -> tasks in order, each worked by its expert and confirmed by the PD
  (tools/worktree_runner.py) -> awaiting_merge -> [승인] merge | [반려] rework (a comment, same branch) | [폐기] discard

- One plan = one ticket = one worktree branch. Tier 3 paths are refused when the plan is submitted.
- The operator's decisions come from the chat page (`/ticket delegate|merge|rework|discard N`,
  same-origin POSTs); the tool only plans and reads.
- Runs are separate processes in their own session, so a host restart (⚡) does not cut them. Each
  keeps its state in the runner's state file, which is what the page's work cards show.

The provider doing the work is configuration (host_config.DELEGATE_PROVIDER), never named here.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tickets
from host_config import (AGENT_PATH_PREFIX, DATA, DELEGATE_MODEL, DELEGATE_PROVIDER, DELEGATE_REVIEWER,
                         DELEGATE_REVIEWER_MODEL, ROOT)

RUNNER_PATH = ROOT / "tools" / "worktree_runner.py"
SEEN_FILE = DATA / "delegation_seen.json"
ACTIVE_PHASES = ("starting", "running", "writing", "gates", "review", "merging")
PASS_ENV = ("CHATBOT_ROOT", "CHATBOT_DATA")   # where the runner finds this instance; nothing secret
MAX_RUNS = 20
_TITLE_MAX = 120
_INSTRUCTION_MAX = 8000
_lock = threading.Lock()
_runner = None


class DelegationError(Exception):
    """A refusal the caller can show as is."""


def runner():
    """tools/worktree_runner.py as a module (standard library only, no side effects on import)."""
    global _runner
    if _runner is None:
        spec = importlib.util.spec_from_file_location("worktree_runner", str(RUNNER_PATH))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _runner = mod
    return _runner


def worker_role() -> str:
    """The role id the delegated worker records on tickets (e.g. `claude-code`)."""
    try:
        return runner().PROVIDERS[DELEGATE_PROVIDER]["actor"]
    except KeyError:
        raise DelegationError("delegation provider %r is not one the runner knows" % DELEGATE_PROVIDER)


def _paths(raw) -> List[str]:
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    out = [str(p).strip().replace("\\", "/") for p in items if str(p).strip()]
    if not out:
        raise DelegationError("paths are required: the repo-relative files the work may change")
    for p in out:
        if p.startswith("/") or ".." in p.split("/"):
            raise DelegationError("path must be repo-relative: %s" % p[:80])
    return out


def tier_of(paths: List[str]) -> int:
    """0 or 2 for these paths (the same rule the runner applies); Tier 3 is refused."""
    r = runner()
    try:
        return r.check_tiers(ROOT, paths, r.gate_files(ROOT, r.DEFAULT_GATES), retryable=False)
    except r.Failure as f:
        raise DelegationError(f.reason)


# ------------------------------------------------------------------ the PD plans

MAX_TASKS = 8
_ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def experts() -> List[str]:
    """The roles experts can be asked by: every character's role except the PD's (characters.py)."""
    import characters
    return [r for r in characters.roles(DATA / "workspace") if r != "pd"]


def _tasks(raw) -> List[Dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TASKS:
        raise DelegationError("a plan has 1-%d tasks" % MAX_TASKS)
    roles = experts()
    out = []
    for n, t in enumerate(raw, 1):
        if not isinstance(t, dict):
            raise DelegationError("task %d must be an object {role, title, instruction, paths}" % n)
        role = str(t.get("role") or (roles[0] if len(roles) == 1 else "")).strip()
        if role not in roles:
            raise DelegationError("task %d: role must be one of your experts: %s" % (n, ", ".join(roles) or "(none)"))
        title = re.sub(r"\s+", " ", str(t.get("title") or "")).strip()[:_TITLE_MAX]
        instruction = str(t.get("instruction") or "").strip()[:_INSTRUCTION_MAX]
        if not title or not instruction:
            raise DelegationError("task %d needs a title and an instruction" % n)
        out.append({"role": role, "title": title, "instruction": instruction, "paths": _paths(t.get("paths"))})
    return out


def plan(title: str, tasks, evidence, actor: str, ticket_id: Optional[int] = None) -> Dict:
    """The PD submits a plan; it waits for the operator's [실행]. With `ticket_id`, it replaces the plan of a
    ticket still waiting for that (the operator asked for a new one). Returns {ticket, tier, tasks}."""
    title = re.sub(r"\s+", " ", str(title or "")).strip()[:_TITLE_MAX]
    if not title:
        raise DelegationError("the plan needs a title")
    tasks = _tasks(tasks)
    paths = sorted({p for t in tasks for p in t["paths"]})
    tier = tier_of(paths)
    if ticket_id:
        t = tickets.get(DATA, ticket_id)
        if t["status"] not in ("proposed", "approved") or runner().read_state(t["id"]).get("phase") != "awaiting_go":
            raise DelegationError("ticket %d is not a plan waiting for [실행]" % t["id"])
    else:
        t, _ = tickets.propose(DATA, title, ",".join(paths), evidence, actor=actor)
    tid = t["id"]
    runner().write_state(tid, phase="awaiting_go", title=title, paths=paths, tier=tier, requested_by=actor,
                         plan={"tasks": tasks}, transcript=[], reason="", task=0, tasks_total=len(tasks))
    return {"ticket": tid, "tier": tier, "tasks": len(tasks)}


def request(title: str, paths, instruction: str, evidence, actor: str) -> Dict:
    """A one-task plan (the older `start` call); it waits for [실행] like any plan."""
    roles = experts()
    return plan(title, [{"role": roles[0] if roles else "", "title": title, "instruction": instruction,
                         "paths": paths}], evidence, actor)


# ------------------------------------------------------------- the operator decides

def go(ticket_id: int) -> Dict:
    """`[실행]`: approve the ticket if it still waits for that, claim it and launch the plan."""
    t = tickets.get(DATA, ticket_id)
    tid = t["id"]
    st = runner().read_state(tid)
    if not (st.get("plan") or {}).get("tasks"):   # a ticket that came from elsewhere: one task from its own words
        paths = t.get("paths") or tickets._paths_of(t)
        if not paths:
            raise DelegationError("ticket %d names no files to change; ask the PD for a plan" % tid)
        roles = experts()
        runner().write_state(tid, title=t.get("title", ""), paths=_paths(paths), tier=tier_of(_paths(paths)),
                             plan={"tasks": [{"role": roles[0] if roles else "", "title": t.get("title", ""),
                                              "paths": _paths(paths), "instruction": "%s\n(target: %s)"
                                              % (t.get("title", ""), t.get("target", ""))}]})
        st = runner().read_state(tid)
    tier = tier_of(st["paths"])
    if t["status"] == "proposed":
        t = tickets.approve(DATA, tid, operator=tickets.OPERATOR_UI)
    if t["status"] != "approved":
        raise DelegationError("ticket %d is %s; only an approved ticket can be run" % (tid, t["status"]))
    c = tickets.claim(DATA, tid, paths=st["paths"], actor=worker_role())
    runner().write_state(tid, phase="starting", tier=tier, transcript=[], reason="")
    args = ["run", "--ticket", str(tid), "--token", c["token"], "--plan-from-state"]
    return {"ticket": tid, "tier": tier, "pid": _launch(tid, c["token"], args)}


def rework(ticket_id: int, comment: str) -> Dict:
    """`[반려]`: the operator sends the finished work back with a comment; the same branch is reworked."""
    tid = int(ticket_id)
    if runner().read_state(tid).get("phase") != "awaiting_merge":
        raise DelegationError("ticket %d has no finished work waiting for your confirmation" % tid)
    comment = str(comment or "").strip()[:_INSTRUCTION_MAX]
    r = tickets.rework(DATA, tid, comment, operator=tickets.OPERATOR_UI, actor=worker_role())
    runner().write_state(tid, phase="starting", reason="")
    args = ["run", "--ticket", str(tid), "--token", r["token"], "--resume", "--prompt", comment]
    return {"ticket": tid, "pid": _launch(tid, r["token"], args, back_to_waiting=True)}


def merge(ticket_id: int) -> Dict:
    """`[승인]`: the operator lets the reviewed change land; the runner merges it on its own. Also retries a merge
    whose process died (the card shows it stalled): the dead run's lease is freed first."""
    tid = int(ticket_id)
    st = runner().read_state(tid)
    raw, phase = st.get("phase"), _phase(st)
    if not (raw == "awaiting_merge" or (raw == "merging" and phase == "stalled")):
        raise DelegationError("ticket %d has no delegated change awaiting a merge" % tid)
    lease = tickets._read_lease(DATA)
    if raw == "merging" and lease and lease.get("ticket") == tid:
        tickets.drop_lease(DATA, operator=tickets.OPERATOR_UI)   # back to awaiting_merge
    m = tickets.merge_go(DATA, tid, operator=tickets.OPERATOR_UI, actor=worker_role())
    runner().write_state(tid, phase="merging")   # before the runner starts: it reads this state
    try:
        pid = _spawn(tid, ["merge", "--ticket", str(tid), "--token", m["token"], "--json"])
    except OSError as e:
        tickets.drop_lease(DATA, operator=tickets.OPERATOR_UI)   # back to awaiting_merge
        runner().write_state(tid, phase="awaiting_merge")
        raise DelegationError("could not start the merge: %s" % e)
    return {"ticket": tid, "pid": pid}


def discard(ticket_id: int) -> Dict:
    """`[폐기]`: decline the ticket and drop its worktree and branch."""
    tid = int(ticket_id)
    r = runner()
    st = r.read_state(tid)
    if _phase(st) in ACTIVE_PHASES:
        raise DelegationError("ticket %d is still running; wait for it to stop" % tid)
    lease = tickets._read_lease(DATA)
    if lease and lease.get("ticket") == tid:   # a stalled run still holds it
        tickets.drop_lease(DATA, operator=tickets.OPERATOR_UI)
    t = tickets.decline(DATA, tid, operator=tickets.OPERATOR_UI)
    branch, wt_dir = r.names(tid)
    r.cleanup_worktree(r.CHATBOT_REPO, branch, wt_dir)
    provider = st.get("provider") or DELEGATE_PROVIDER
    if provider in r.PROVIDERS:
        r.commit_ticket_record(r.CHATBOT_REPO, tid, provider,
                               "chore(tickets): #%d declined -- %s" % (tid, str(t.get("title", ""))[:80]))
    r.write_state(tid, phase="declined")
    return {"ticket": tid, "status": t["status"]}


# ------------------------------------------------------------------- launching

def _launch(tid: int, token: str, args: List[str], back_to_waiting: bool = False) -> int:
    """Start the runner on a ticket already claimed for the worker. Everything waits for the operator's
    final confirmation (--stop-before-merge). If it cannot start, the claim is given back."""
    st = runner().read_state(tid)
    args = args + ["--provider", DELEGATE_PROVIDER, "--title", st["title"], "--paths", ",".join(st["paths"]),
                   "--stop-before-merge", "--json"]
    if DELEGATE_REVIEWER:
        args += ["--reviewer", DELEGATE_REVIEWER]
    if DELEGATE_MODEL:
        args += ["--model", DELEGATE_MODEL]
    if DELEGATE_REVIEWER_MODEL:
        args += ["--reviewer-model", DELEGATE_REVIEWER_MODEL]
    try:
        return _spawn(tid, args)
    except OSError as e:
        if back_to_waiting:
            tickets.await_merge(DATA, tid, token, "could not start the rework: %s" % e, actor=worker_role())
            runner().write_state(tid, phase="awaiting_merge")
        else:
            tickets.release(DATA, tid, token, "failed", "could not start the runner: %s" % e, actor=worker_role())
            runner().write_state(tid, phase="failed", reason="could not start the runner")
        raise DelegationError("could not start the runner: %s" % e)


def _spawn(tid: int, args: List[str]) -> int:
    """The runner in its own session (a host restart does not cut it), with a clean environment."""
    r = runner()
    log_path = r.state_path(tid).with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    extra = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env = r.clean_env(**extra)
    env["PATH"] = AGENT_PATH_PREFIX + ":" + env.get("PATH", "")
    with open(log_path, "ab") as log:
        p = subprocess.Popen([sys.executable, str(RUNNER_PATH)] + args, cwd=str(ROOT), env=env,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True, close_fds=True)
    threading.Thread(target=p.wait, daemon=True).start()   # reap it if it ends while this process lives
    r.write_state(tid, pid=p.pid)
    return p.pid


# ---------------------------------------------------------------------- reading

def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _phase(st: Dict) -> str:
    """The run's phase, or `stalled` when it says it is active but its process is gone."""
    phase = st.get("phase", "")
    if phase in ACTIVE_PHASES and phase != "starting" and not _alive(st.get("pid")):
        return "stalled"
    return phase


def _seen() -> Dict[str, int]:
    try:
        raw = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def runs(limit: int = MAX_RUNS) -> List[Dict]:
    """The work cards: newest first. `stalled` when a run says it is active but its process is gone."""
    d = runner().state_path(0).parent
    if not d.is_dir():
        return []
    seen = _seen()
    files = sorted(d.glob("ticket-*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    out = []
    for f in files:
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tid = st.get("ticket")
        phase = _phase(st)
        out.append({"ticket": tid, "title": st.get("title", ""), "phase": phase, "round": st.get("round", 0),
                    "tier": st.get("tier", 0), "paths": st.get("paths", []), "reason": st.get("reason", ""),
                    "head": st.get("head", ""), "updated": st.get("updated", ""),
                    "started": st.get("started", 0), "phase_since": st.get("phase_since", 0),
                    "task": st.get("task", 0), "tasks_total": st.get("tasks_total", 0),
                    "brain": st.get("brain", ""),
                    "stalled_in": st.get("phase", "") if phase == "stalled" else "",
                    "tasks": [{k: t.get(k) for k in ("role", "title", "paths")}
                              for t in (st.get("plan") or {}).get("tasks", [])],
                    "transcript": st.get("transcript", []), "active": phase in ACTIVE_PHASES,
                    "seen": seen.get(str(tid)) == st.get("rev")})
    return out


def display_names() -> Dict[str, str]:
    """Role id -> the character's display name, for the page (the PD is ''). Display only (NAME_NEUTRAL_v1)."""
    try:
        import identity
        return {role: identity.get_identity(role)["name"] for role in [""] + experts()}
    except Exception:  # noqa: BLE001
        return {}


def mark_seen(ticket_id: int) -> None:
    tid = int(ticket_id)
    rev = runner().read_state(tid).get("rev", 0)
    with _lock:
        seen = _seen()
        seen[str(tid)] = rev
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEEN_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen), encoding="utf-8")
        tmp.replace(SEEN_FILE)


def delegation_api(method: str, path: str, body: Optional[dict]) -> Optional[Tuple[int, dict]]:
    """The /api/delegations routes. Returns None when `path` is not one of ours. A POST is the operator
    deciding from the chat page, so the caller must have checked that it came from this server's own page."""
    if not (path == "/api/delegations" or path.startswith("/api/delegations/")):
        return None
    rest = path[len("/api/delegations"):].strip("/")
    try:
        if method == "GET" and rest == "":
            return 200, {"ok": True, "runs": runs(), "names": display_names()}
        if method == "POST":
            m = re.fullmatch(r"(\d+)/(go|merge|rework|discard|seen)", rest)
            if m:
                tid, action = int(m.group(1)), m.group(2)
                if action == "seen":
                    mark_seen(tid)
                    return 200, {"ok": True}
                if action == "rework":
                    return 200, {"ok": True, **rework(tid, str((body or {}).get("comment") or ""))}
                return 200, {"ok": True, **{"go": go, "merge": merge, "discard": discard}[action](tid)}
    except (DelegationError, tickets.TicketError) as e:
        return (404 if str(e).startswith("no such ticket") else 400), {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}
