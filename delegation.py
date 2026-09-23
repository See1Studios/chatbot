"""Worktree delegation, host side (docs/plans/multi-agent-worktree-delegation.md §9, DELEGATION_WIRING_v1).

The work itself runs in `tools/worktree_runner.py` (ticket -> isolated worktree -> writer and reviewer
characters -> gates -> merge); this module only decides who may start what and launches it:

- The chat agent asks (`delegate` tool, `request`), on the operator's request in the conversation.
  Tier 0 paths start at once (Tier 0 is the agent's own to change anyway); Tier 2 paths become a
  proposed ticket that waits for the operator's `[맡겨]`; Tier 3 is refused.
- The operator decides from the chat page (`/ticket delegate|merge|discard N`, same-origin POSTs):
  `go` approves if needed, claims and launches the run; `merge` relays the operator's word to an
  awaiting_merge ticket and launches the landing; `discard` declines it and drops its branch.
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
from host_config import AGENT_PATH_PREFIX, DATA, DELEGATE_PROVIDER, DELEGATE_REVIEWER, ROOT

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


# ------------------------------------------------------------------ the agent asks

def request(title: str, paths, instruction: str, evidence, actor: str) -> Dict:
    """The chat agent delegates work the operator asked for in the conversation. Tier 0 starts now;
    Tier 2 is proposed and waits for the operator. Returns {ticket, tier, started}."""
    title = re.sub(r"\s+", " ", str(title or "")).strip()[:_TITLE_MAX]
    instruction = str(instruction or "").strip()[:_INSTRUCTION_MAX]
    if not title or not instruction:
        raise DelegationError("title and instruction are required")
    paths = _paths(paths)
    tier = tier_of(paths)
    t, _ = tickets.propose(DATA, title, ",".join(paths), evidence, actor=actor)
    tid = t["id"]
    runner().write_state(tid, phase="awaiting_go" if tier >= 2 else "starting", title=title, paths=paths,
                         instruction=instruction, tier=tier, requested_by=actor, transcript=[])
    if tier >= 2:
        return {"ticket": tid, "tier": tier, "started": False}
    if t["status"] == "proposed":
        tickets.approve(DATA, tid, operator=tickets.OPERATOR_CONFIRMED,
                        on_behalf="%s delegate (Tier 0, on the operator's request in chat)" % actor)
    _launch(tid)
    return {"ticket": tid, "tier": tier, "started": True}


# ------------------------------------------------------------- the operator decides

def go(ticket_id: int) -> Dict:
    """`[맡겨]`: approve the ticket if it still waits for that, claim it and launch the run."""
    t = tickets.get(DATA, ticket_id)
    tid = t["id"]
    st = runner().read_state(tid)
    paths = st.get("paths") or t.get("paths") or tickets._paths_of(t)
    if not paths:
        raise DelegationError("ticket %d names no files to change; say which files, then delegate it" % tid)
    paths = _paths(paths)
    tier = tier_of(paths)
    if t["status"] == "proposed":
        t = tickets.approve(DATA, tid, operator=tickets.OPERATOR_UI)
    if t["status"] != "approved":
        raise DelegationError("ticket %d is %s; only an approved ticket can be delegated" % (tid, t["status"]))
    instruction = st.get("instruction") or "%s\n(target: %s)" % (t.get("title", ""), t.get("target", ""))
    runner().write_state(tid, phase="starting", title=st.get("title") or t.get("title", ""), paths=paths,
                         instruction=instruction, tier=tier, transcript=[], reason="")
    return {"ticket": tid, "tier": tier, "pid": _launch(tid)}


def merge(ticket_id: int) -> Dict:
    """`[병합·⚡]`: the operator lets the reviewed change land; the runner merges it on its own."""
    tid = int(ticket_id)
    if runner().read_state(tid).get("phase") != "awaiting_merge":
        raise DelegationError("ticket %d has no delegated change awaiting a merge" % tid)
    m = tickets.merge_go(DATA, tid, operator=tickets.OPERATOR_UI, actor=worker_role())
    try:
        pid = _spawn(tid, ["merge", "--ticket", str(tid), "--token", m["token"], "--json"])
    except OSError as e:
        tickets.drop_lease(DATA, operator=tickets.OPERATOR_UI)   # back to awaiting_merge
        raise DelegationError("could not start the merge: %s" % e)
    runner().write_state(tid, phase="merging")
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

def _launch(tid: int) -> int:
    """Claim the approved ticket for the worker and start the runner on it."""
    r = runner()
    st = r.read_state(tid)
    c = tickets.claim(DATA, tid, paths=st["paths"], actor=worker_role())
    args = ["run", "--ticket", str(tid), "--token", c["token"], "--provider", DELEGATE_PROVIDER,
            "--title", st["title"], "--paths", ",".join(st["paths"]), "--prompt", st["instruction"], "--json"]
    if DELEGATE_REVIEWER:
        args += ["--reviewer", DELEGATE_REVIEWER]
    if st.get("tier", 0) >= 2:
        args.append("--stop-before-merge")
    try:
        return _spawn(tid, args)
    except OSError as e:
        tickets.release(DATA, tid, c["token"], "failed", "could not start the runner: %s" % e, actor=worker_role())
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
                    "transcript": st.get("transcript", []), "active": phase in ACTIVE_PHASES,
                    "seen": seen.get(str(tid)) == st.get("rev")})
    return out


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
            return 200, {"ok": True, "runs": runs()}
        if method == "POST":
            m = re.fullmatch(r"(\d+)/(go|merge|discard|seen)", rest)
            if m:
                tid, action = int(m.group(1)), m.group(2)
                if action == "seen":
                    mark_seen(tid)
                    return 200, {"ok": True}
                return 200, {"ok": True, **{"go": go, "merge": merge, "discard": discard}[action](tid)}
    except (DelegationError, tickets.TicketError) as e:
        return (404 if str(e).startswith("no such ticket") else 400), {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}
