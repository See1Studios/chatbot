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
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import difflib

import tickets
from host_config import (AGENT_PATH_PREFIX, DATA, DELEGATE_MODEL, DELEGATE_PROVIDER, DELEGATE_REVIEWER,
                         DELEGATE_REVIEWER_MODEL, ROOT)

RUNNER_PATH = ROOT / "tools" / "worktree_runner.py"
PLAN_ROOT = ROOT             # where a plan's files must exist (DELEGATION_CLARITY_v1); tests point it elsewhere
SEEN_FILE = DATA / "delegation_seen.json"
ACTIVE_PHASES = ("starting", "running", "writing", "gates", "review", "merging")
PASS_ENV = ("CHATBOT_ROOT", "CHATBOT_DATA")   # where the runner finds this instance; nothing secret
MAX_RUNS = 20
QUEUE_POLL_SEC = 10          # how often a queued [실행] checks whether its files came free
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
        paths = _task_paths(n, t.get("paths"), t.get("creates"))
        out.append({"role": role, "title": title, "instruction": instruction, "paths": paths,
                    "reads": [p for p in _task_reads(n, t.get("reads")) if p not in paths]})
    return out


def _task_reads(n: int, reads) -> List[str]:
    """Files the task only reads: not leased, not in the tier or scope checks, so they must exist."""
    rels = tickets._norm_paths(_paths(reads), DATA) if reads else []
    for rel in rels:
        if not (PLAN_ROOT / rel).exists():
            raise DelegationError("task %d: reads %s does not exist%s" % (n, rel, _nearest(rel)))
    return rels


def _task_paths(n: int, paths, creates) -> List[str]:
    """A task's files: `paths` must exist, `creates` must not (its folder must). A guessed name is refused with the
    real files nearest to it -- #113 named static/style.css and ran 20 minutes; the file is static/chat.css."""
    have = tickets._norm_paths(_paths(paths), DATA) if paths else []
    new = tickets._norm_paths(_paths(creates), DATA) if creates else []
    if not have and not new:
        raise DelegationError("task %d: paths are required: the repo-relative files the work may change" % n)
    for rel in have:
        if not (PLAN_ROOT / rel).exists():
            raise DelegationError("task %d: %s does not exist%s. paths = existing files; new files go in creates."
                                  % (n, rel, _nearest(rel)))
    for rel in new:
        if (PLAN_ROOT / rel).exists():
            raise DelegationError("task %d: %s already exists; put it in paths" % (n, rel))
        if not (PLAN_ROOT / rel).parent.is_dir():
            raise DelegationError("task %d: folder %s does not exist" % (n, str(Path(rel).parent)))
    return have + [x for x in new if x not in have]


def _nearest(rel: str) -> str:
    """ ' (nearest: a, b)' from the same folder, or ''."""
    folder = (PLAN_ROOT / rel).parent
    if not folder.is_dir():
        return " (no folder %s)" % str(Path(rel).parent)
    names = sorted(x.name for x in folder.iterdir() if not x.name.startswith("."))
    near = difflib.get_close_matches(Path(rel).name, names, n=3, cutoff=0.3)
    base = str(Path(rel).parent)
    return " (nearest: %s)" % ", ".join((base + "/" + x) if base != "." else x for x in near) if near else ""


def plan(title: str, tasks, evidence, actor: str, ticket_id: Optional[int] = None) -> Dict:
    """The PD submits a plan; it waits for the operator's [실행]. With `ticket_id`, it replaces the plan of a
    ticket still waiting for that, or of one that gate_failed/failed with attempts left (same id, attempts kept). Returns {ticket, tier, tasks}."""
    title = re.sub(r"\s+", " ", str(title or "")).strip()[:_TITLE_MAX]
    if not title:
        raise DelegationError("the plan needs a title")
    tasks = _tasks(tasks)
    paths = sorted({p for t in tasks for p in t["paths"]})
    tier = tier_of(paths)
    dirty = tickets._ship_blockers(PLAN_ROOT, {"paths": [p for p in paths if (PLAN_ROOT / p).exists()]})
    if dirty:   # [실행]'s claim would refuse them (#213); `creates` files do not exist yet, so they are exempt
        raise DelegationError("uncommitted: %s; commit or revert them first, then plan again" % ", ".join(dirty[:5]))
    if ticket_id:
        t = tickets.get(DATA, ticket_id)
        phase = runner().read_state(t["id"]).get("phase")
        if phase in ("gate_failed", "failed") and t["attempts"] >= tickets.MAX_ATTEMPTS:
            raise DelegationError("ticket %d used all %d attempts; open a new ticket" % (t["id"], tickets.MAX_ATTEMPTS))
        if not (t["status"] in ("proposed", "approved") and phase == "awaiting_go"
                or t["status"] == "approved" and phase in ("gate_failed", "failed")):
            raise DelegationError("ticket %d is %s/%s; only a plan waiting for [실행] or one that gate_failed/failed "
                                  "can be replaced" % (t["id"], t["status"], phase))
    else:
        t, _ = tickets.propose(DATA, title, ",".join(paths), evidence, actor=actor)
    tid = t["id"]
    runner().write_state(tid, phase="awaiting_go", title=title, paths=paths, tier=tier, requested_by=actor,
                         plan={"tasks": tasks}, transcript=[], reason="", task=0, tasks_total=len(tasks))
    return {"ticket": tid, "tier": tier, "tasks": len(tasks)}


def request(title: str, paths, instruction: str, evidence, actor: str, creates=None) -> Dict:
    """A one-task plan (the older `start` call); it waits for [실행] like any plan."""
    roles = experts()
    return plan(title, [{"role": roles[0] if roles else "", "title": title, "instruction": instruction,
                         "paths": paths, "creates": creates}], evidence, actor)


# ------------------------------------------------------------- the operator decides

def go(ticket_id: int, queue: bool = True) -> Dict:
    """`[실행]`: approve the ticket if it still waits for that, claim it and launch the plan. When another ticket
    holds some of its files, it waits in the queue (phase `queued`) and starts on its own once they are free
    (LEASE_SCOPE_v1)."""
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
        if queue and t["status"] in ("done", "declined", "wontfix"):
            target_phase = "done" if t["status"] == "done" else "declined"
            runner().write_state(tid, phase=target_phase, reason="ticket is already %s" % t["status"])
            mark_seen(tid)
            return {"ticket": tid, "tier": tier, "status": t["status"], "phase": target_phase, "healed": True}
        raise DelegationError("ticket %d is %s; only an approved ticket can be run" % (tid, t["status"]))
    try:
        c = tickets.claim(DATA, tid, paths=st["paths"], actor=worker_role())
    except tickets.TicketError as e:
        if not (queue and _lock_busy(e)):
            raise
        blocked = tickets.get(DATA, tid).get("blocked_by") or {}
        runner().write_state(tid, phase="queued", queued_at=time.time(), blocked_by=blocked, tier=tier, reason="")
        return {"ticket": tid, "tier": tier, "queued": True, "blocked_by": blocked}
    runner().write_state(tid, phase="starting", tier=tier, transcript=[], reason="", blocked_by={})
    args = ["run", "--ticket", str(tid), "--token", c["token"], "--plan-from-state"]
    if _has_attic(tid):   # a re-plan after gate_failed/failed goes on from the work that attempt left
        args.append("--from-attic")
    return {"ticket": tid, "tier": tier, "pid": _launch(tid, c["token"], args)}


def _has_attic(tid: int) -> bool:
    r = runner()
    return r.git(r.CHATBOT_REPO, "rev-parse", "--verify", "--quiet", r.attic_ref(tid))[0] == 0


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
    if raw == "merged-ticket-open":
        return _close_merged(tid, st)
    if not (raw == "awaiting_merge" or (raw == "merging" and phase == "stalled")):
        raise DelegationError("ticket %d has no delegated change awaiting a merge" % tid)
    if raw == "merging" and tickets._read_lease(DATA, tid):
        tickets.drop_lease(DATA, operator=tickets.OPERATOR_UI, ticket_id=tid)   # back to awaiting_merge
    m = tickets.merge_go(DATA, tid, operator=tickets.OPERATOR_UI, actor=worker_role())
    runner().write_state(tid, phase="merging")   # before the runner starts: it reads this state
    try:
        pid = _spawn(tid, ["merge", "--ticket", str(tid), "--token", m["token"], "--json"])
    except OSError as e:
        tickets.drop_lease(DATA, operator=tickets.OPERATOR_UI, ticket_id=tid)   # back to awaiting_merge
        runner().write_state(tid, phase="awaiting_merge")
        raise DelegationError("could not start the merge: %s" % e)
    return {"ticket": tid, "pid": pid}


def _close_merged(tid: int, st: Dict) -> Dict:
    """MERGED_CLOSE_v1: the change landed but closing the ticket failed (its lease ran out mid-merge, 2026-09-29
    #371), so the card still offered its approve button and the merge was refused. Approving now finishes the job: when the run's
    merge commit is on the main branch, the operator's lease closes the ticket through the ordinary done gate."""
    r = runner()
    head = st.get("head") or ""
    if not head or r.git(r.CHATBOT_REPO, "merge-base", "--is-ancestor", head, "HEAD")[0] != 0:
        raise DelegationError("ticket %d: its merge commit is not on the main branch; nothing to close" % tid)
    m = tickets.merge_go(DATA, tid, operator=tickets.OPERATOR_UI, actor=worker_role())
    try:
        tickets.release(DATA, tid, m["token"], "done", "merged %s earlier; closed on the operator's word" % head[:7],
                        actor=worker_role())
    except tickets.TicketError:
        tickets.drop_lease(DATA, operator=tickets.OPERATOR_UI, ticket_id=tid)   # back to awaiting_merge, as it was
        raise
    r.write_state(tid, phase="done", reason="")
    mark_seen(tid)
    return {"ticket": tid, "status": "done", "phase": "done", "healed": True}


def discard(ticket_id: int) -> Dict:
    """`[폐기]`: decline the ticket and drop its worktree and branch."""
    tid = int(ticket_id)
    r = runner()
    st = r.read_state(tid)
    if _phase(st) in ACTIVE_PHASES:
        raise DelegationError("ticket %d is still running; wait for it to stop" % tid)
    if tickets._read_lease(DATA, tid):   # a stalled run still holds it
        tickets.drop_lease(DATA, operator=tickets.OPERATOR_UI, ticket_id=tid)
    try:
        t = tickets.decline(DATA, tid, operator=tickets.OPERATOR_UI)
        status = t.get("status", "declined")
        title = t.get("title", "")
    except tickets.TicketError:
        try:
            t = tickets.get(DATA, tid)
            status = t.get("status", "declined")
            title = t.get("title", "")
        except tickets.TicketError:
            status = "declined"
            title = st.get("title", "")
    branch, wt_dir = r.names(tid)
    r.cleanup_worktree(r.CHATBOT_REPO, branch, wt_dir)
    provider = st.get("provider") or DELEGATE_PROVIDER
    if provider in r.PROVIDERS:
        try:
            r.commit_ticket_record(r.CHATBOT_REPO, tid, provider,
                                   "chore(tickets): #%d declined -- %s" % (tid, str(title)[:80]))
        except Exception:
            pass
    r.write_state(tid, phase="declined")
    mark_seen(tid)
    return {"ticket": tid, "status": status}


def allow(ticket_id: int) -> Dict:
    """`[경로 허용]`: the worker asked for files outside its task (NEED_PATH_v1, phase `paused`); add them to that task
    and run the plan again -- it picks up the kept work where it stopped. Tier 3 files and missing folders are refused."""
    tid = int(ticket_id)
    r = runner()
    st = r.read_state(tid)
    asked = st.get("need_paths") or []
    if st.get("phase") != "paused" or not asked:
        raise DelegationError("ticket %d is not waiting for paths" % tid)
    new = tickets._norm_paths([x.get("path", "") for x in asked], DATA)
    for rel in new:
        if not ((PLAN_ROOT / rel).exists() or (PLAN_ROOT / rel).parent.is_dir()):
            raise DelegationError("%s: folder %s does not exist" % (rel, str(Path(rel).parent)))
    paths = sorted(set(st.get("paths") or []) | set(new))
    tier = tier_of(paths)                                   # refuses Tier 3
    plan = st.get("plan") or {"tasks": []}
    n = int(st.get("need_task") or 1)
    if 1 <= n <= len(plan["tasks"]):
        plan["tasks"][n - 1]["paths"] = list(plan["tasks"][n - 1]["paths"]) + [p for p in new
                                                                             if p not in plan["tasks"][n - 1]["paths"]]
    r.write_state(tid, paths=paths, plan=plan, tier=tier, need_paths=[], allowed=new)
    return dict(go(tid, queue=True), allowed=new)


def unqueue(ticket_id: int) -> Dict:
    """`[취소]` on a queued [실행]: back to a plan waiting for [실행]."""
    tid = int(ticket_id)
    if runner().read_state(tid).get("phase") != "queued":
        raise DelegationError("ticket %d is not waiting in the queue" % tid)
    runner().write_state(tid, phase="awaiting_go", blocked_by={}, queued_at=0)
    return {"ticket": tid, "phase": "awaiting_go"}


def _lock_busy(e: Exception) -> bool:
    return "author lock is held" in str(e)


def advance_queue() -> List[int]:
    """Start queued runs whose files came free, oldest first. Returns the tickets started."""
    d = runner().state_path(0).parent
    if not d.is_dir():
        return []
    queued = []
    for f in d.glob("ticket-*.json"):
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if st.get("phase") == "queued" and st.get("ticket"):
            queued.append((float(st.get("queued_at") or 0), int(st["ticket"])))
    started = []
    for _, tid in sorted(queued):
        try:
            go(tid, queue=False)
            started.append(tid)
        except (DelegationError, tickets.TicketError) as e:
            if _lock_busy(e):                              # still waiting; keep what blocks it current
                try:
                    blocked = tickets.get(DATA, tid).get("blocked_by") or {}
                    if blocked != runner().read_state(tid).get("blocked_by"):
                        runner().write_state(tid, blocked_by=blocked)
                except tickets.TicketError:
                    pass
                continue
            runner().write_state(tid, phase="failed", reason="could not start from the queue: %s" % e)
    return started


def queue_loop(stop: Optional[threading.Event] = None) -> None:
    """The chat server's watcher for queued runs (the tool server does not run it)."""
    stop = stop or threading.Event()
    while not stop.wait(QUEUE_POLL_SEC):
        try:
            advance_queue()
        except Exception:  # noqa: BLE001 -- a bad state file must not end the watcher
            pass


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


_changed_cache: Dict[int, Tuple[float, int]] = {}
CHANGED_TTL_SEC = 10


def _files_changed(tid: int, base: str) -> Optional[int]:
    """How many files the run's worktree changed since `base` (committed or not, new ones too); None when unknown.
    Cached for CHANGED_TTL_SEC: the page asks every few seconds while a run is active."""
    hit = _changed_cache.get(tid)
    if hit and time.monotonic() - hit[0] < CHANGED_TTL_SEC:
        return hit[1]
    _, wt_dir = runner().names(tid)
    if not base or not Path(wt_dir).is_dir():
        return None
    run = runner().git
    c1, diff, _ = run(Path(wt_dir), "diff", "--name-only", base, timeout=10)
    c2, new, _ = run(Path(wt_dir), "ls-files", "--others", "--exclude-standard", timeout=10)
    if c1 != 0 or c2 != 0:
        return None
    n = len({x for x in (diff + "\n" + new).splitlines() if x.strip()})
    _changed_cache[tid] = (time.monotonic(), n)
    return n


def _seen() -> Dict[str, int]:
    try:
        raw = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _need_paths_view(asked: List[Dict]) -> List[Dict]:
    """A paused run's requests for the page: a Tier 3 path is marked `operator_only`, so the page offers no
    allow button that allow() would refuse anyway (#381)."""
    if not asked:
        return []
    r = runner()
    gated = r.gate_files(ROOT, r.DEFAULT_GATES)
    out = []
    for x in asked:
        try:
            tier, why = r.tier_of(ROOT, x.get("path", ""), gated)
        except Exception:
            tier, why = 0, ""
        out.append(dict(x, operator_only=True, blocked_why=why) if tier >= 3 else dict(x))
    return out


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
        if tid is not None:
            try:
                t = tickets.get(DATA, tid)
                t_status = t.get("status")
            except tickets.TicketError:
                t_status = None
            if t_status in ("done", "declined", "wontfix"):
                target_phase = "done" if t_status == "done" else "declined"
                if phase != target_phase and phase not in ACTIVE_PHASES:
                    runner().write_state(tid, phase=target_phase, reason="ticket is %s" % t_status)
                    mark_seen(tid)
                    st = runner().read_state(tid)
                    phase = target_phase
                    seen[str(tid)] = st.get("rev")
        out.append({"ticket": tid, "title": st.get("title", ""), "phase": phase, "round": st.get("round", 0),
                    "tier": st.get("tier", 0), "paths": st.get("paths", []), "reason": st.get("reason", ""),
                    "head": st.get("head", ""), "updated": st.get("updated", ""),
                    "started": st.get("started", 0), "phase_since": st.get("phase_since", 0),
                    "task": st.get("task", 0), "tasks_total": st.get("tasks_total", 0),
                    "brain": st.get("brain", ""), "timeout_sec": st.get("timeout_sec", 0),
                    "files_changed": _files_changed(tid, st.get("base", "")) if phase in ACTIVE_PHASES else None,
                    "stalled_in": st.get("phase", "") if phase == "stalled" else "",
                    "tasks": [{k: t.get(k) for k in ("role", "title", "paths")}
                              for t in (st.get("plan") or {}).get("tasks", [])],
                    "transcript": st.get("transcript", []), "active": phase in ACTIVE_PHASES,
                    "blocked_by": (st.get("blocked_by") or {}) if phase == "queued" else {},
                    "need_paths": _need_paths_view(st.get("need_paths") or []) if phase == "paused" else [],
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
            m = re.fullmatch(r"(\d+)/(go|merge|rework|discard|seen|unqueue|allow)", rest)
            if m:
                tid, action = int(m.group(1)), m.group(2)
                if action == "seen":
                    mark_seen(tid)
                    return 200, {"ok": True}
                if action == "rework":
                    return 200, {"ok": True, **rework(tid, str((body or {}).get("comment") or ""))}
                return 200, {"ok": True, **{"go": go, "merge": merge, "discard": discard,
                                            "unqueue": unqueue, "allow": allow}[action](tid)}
    except (DelegationError, tickets.TicketError) as e:
        return (404 if str(e).startswith("no such ticket") else 400), {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}


# ----------------------------------------------------------------- the `delegate` tool (served by mcp_server)

def latest_request_ref() -> Optional[str]:
    """`event:<session>#<line>` of the operator's latest message in the live session: the evidence a
    delegation started on the operator's request carries when the agent gives none. None when unknown."""
    try:
        import urllib.request
        port = int(os.environ.get("CHATBOT_PORT") or os.environ.get("AGY_CHAT_PORT") or "3011")
        with urllib.request.urlopen("http://127.0.0.1:%d/api/sessions/active" % port, timeout=1.5) as r:
            sid = str(json.loads(r.read().decode("utf-8") or "{}").get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", sid):
            return None
        last = 0
        with open(DATA / "sessions" / sid / "events.jsonl", encoding="utf-8", errors="replace") as f:
            for no, line in enumerate(f, 1):
                if '"user_ack"' in line:
                    last = no
        return "event:%s#%d" % (sid, last) if last else None
    except Exception:
        return None


# An adapter like mcp_core: the tool server only lists TOOL_DEFS and hands calls to tool_call.

NAMES = ("delegate",)
_DELEGATE_TOOL = {
    "name": "delegate",
    "description": ("You are the producer (PD): you do not change files yourself. For work the operator proposes, "
                    "plan it and hand it to your experts. plan (title, tasks=[{role, title, instruction, paths=[existing repo-"
                    "relative files it changes][, creates=[new files]][, reads=[existing files to read only; they do not raise the tier]]}][, ticket to replace a plan still waiting, or one that gate_failed/failed with attempts left][, evidence; defaults to the operator's "
                    "latest message]): the plan appears as a card and runs only when the operator presses [실행]; each "
                    "task is worked by its expert (role = a character's role, e.g. staff; see data/workspace/characters/) in an "
                    "isolated worktree, then you confirm it; the finished plan lands only when the operator presses "
                    "[승인] (or sends it back with [반려]). Tier 3 paths (guards, gates, approval rules, the charter) "
                    "are refused. start (title, paths, instruction[, creates]): a one-task plan. A path that does not exist is refused with the nearest real files: look before you name one. status: the work cards. "
                    "Running, landing, reworking and discarding are the operator's, not a tool's."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["plan", "start", "status"]},
            "title": {"type": "string"},
            "tasks": {"type": "array", "items": {"type": "object", "properties": {
                "role": {"type": "string"}, "title": {"type": "string"}, "instruction": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
                "creates": {"type": "array", "items": {"type": "string"}},
                "reads": {"type": "array", "items": {"type": "string"}}}}},
            "ticket": {"type": "integer"},
            "paths": {"type": "array", "items": {"type": "string"}},
            "creates": {"type": "array", "items": {"type": "string"}},
            "instruction": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action"],
    },
}
TOOL_DEFS = [_DELEGATE_TOOL]


def tool_call(name: str, args: dict, actor: str, secret_re, envelope, private: bool = False,
              staff: bool = False) -> dict:
    """One `delegate` call from the chat agent; evidence defaults to the operator's latest message. A private
    session delegates nothing (work stays out of it); neither does another character talking with the user
    directly -- plans and delegation are the PD's (CHARACTER_PICKER_v1)."""
    if private:
        return envelope(False, "private session: no work is delegated from here", None)
    if staff:
        return envelope(False, "only a character whose role grants delegate (the PD) plans and delegates; ask the "
                               "user to take this to the PD", None)
    action = str(args.get("action") or "")
    if secret_re.search("\n".join(str(args.get(k) or "") for k in ("title", "instruction", "tasks"))):
        return envelope(False, "refusing to record secret-like content", None)
    try:
        if action in ("plan", "start"):
            evidence = args.get("evidence") or [ref for ref in [latest_request_ref()] if ref]
            if action == "plan":
                res = plan(args.get("title"), args.get("tasks"), evidence, actor=actor, ticket_id=args.get("ticket") or None)
            else:
                res = request(args.get("title"), args.get("paths"), args.get("instruction"), evidence, actor=actor,
                              creates=args.get("creates"))
            return envelope(True, "plan #%d (%d task(s)) is on the operator's card; it runs when they press [실행]. "
                            "Tell them in a line or two." % (res["ticket"], res["tasks"]), res)
        if action == "status":
            return envelope(True, "ok", {"runs": [{k: r[k] for k in ("ticket", "title", "phase", "task", "tasks_total",
                                                                     "round", "tier", "reason", "head")}
                                                  for r in runs()]})
    except (DelegationError, tickets.TicketError) as e:
        return envelope(False, str(e), None)
    return envelope(False, "unknown action (plan, start, status); running, landing and discarding are the operator's",
                    None)
