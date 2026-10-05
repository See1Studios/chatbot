#!/usr/bin/env python3
"""Handoff scenario drill (HANDOFF_DRILL_v1, docs/plans/director-handoff.md dir/drill).

One live handoff and one look missed what broke in practice: races (a restart, a busy receiver, a chain), silent
turns, token waste. This drill runs a fixed set of scenarios on a sandbox host -- its own data folder (settings copied
from the live one; no sessions, dialogs or handoffs), its own ports, this checkout's code -- so it never reaches the
operator's conversations, and checks each against the ledger, the sandbox's event log and the sessions' usage.

  python3 tools/handoff_drill.py                 every scenario (real model turns: minutes, tokens)
  python3 tools/handoff_drill.py refuse chain    the named ones
  python3 tools/handoff_drill.py --list          the scenarios
  python3 tools/handoff_drill.py --keep          leave the sandbox host running afterwards (port 3021)

Exit status 0 only when every scenario passed. The sandbox lives in $CHATBOT_DRILL_DATA (default ~/.pe-drill) and is
rebuilt on every run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import host_config  # noqa: E402  (the live data folder: read, never written)
import platform_compat  # noqa: E402

LIVE = Path(host_config.DATA)
DRILL = Path(os.environ.get("CHATBOT_DRILL_DATA") or Path.home() / ".pe-drill")
PORT, MCP_PORT = 3021, 3022
COPY = ("providers.json", "host.env", "secrets.env", "account_state.json", "work_talk.json", "persona", "workspace")
SKIP = {"artifacts", "skill-observations", "memory"}   # workspace parts that are the operator's records, not settings
WAIT_SEC = 900

os.environ["CHATBOT_HANDOFFS_FILE"] = str(DRILL / "handoffs.jsonl")   # dialog_handoff writes the sandbox ledger
import dialog_handoff as H  # noqa: E402


# ---- the sandbox host ----------------------------------------------------------------------------------------------

def _home() -> Path:
    """The sandbox's HOME: every entry of the real one linked (logins, git, provider state), except the agent CLI's
    config folder, copied with the tool server moved to the sandbox's port. agy reads its tool servers from
    ~/.gemini/config, not only the workspace: with the real HOME the first drill's agents called the live tool server
    (2026-10-05, refused there only because it could not tell who was calling)."""
    real, home = Path.home(), DRILL / "home"
    home.mkdir(parents=True, exist_ok=True)
    for e in real.iterdir():
        if e.name != ".gemini" and not (home / e.name).exists():
            (home / e.name).symlink_to(e)
    gem = home / ".gemini"
    gem.mkdir(exist_ok=True)
    for e in (real / ".gemini").iterdir():
        if e.name == "config":
            shutil.copytree(e, gem / "config", symlinks=True)
            for cfg in (gem / "config").rglob("mcp_config.json"):
                platform_compat.write_text(cfg, cfg.read_text(encoding="utf-8").replace(":3012/", ":%d/" % MCP_PORT), encoding="utf-8")
        elif not (gem / e.name).exists():
            (gem / e.name).symlink_to(e)
    return home


def _env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("PE_HOME", "PRIVATEENGINE_HOME", "AGY_CHAT_DATA")}
    env.update(CHATBOT_DATA=str(DRILL), CHATBOT_ROOT=str(CODE), CHATBOT_LOG_DIR=str(DRILL / "logs"),
               CHATBOT_OBSLOG_PATH=str(DRILL / "logs" / "events.jsonl"),
               CHATBOT_EVENTS_DIR=str(DRILL / "events"), CHATBOT_DIALOGS_DIR=str(DRILL / "dialogs"),
               HOME=str(DRILL / "home"), CHATBOT_HOST="127.0.0.1", CHATBOT_PORT=str(PORT), NAS_MCP_PORT=str(MCP_PORT))
    env.pop("CHATBOT_HANDOFFS_FILE", None)
    return env


def build() -> None:
    """A fresh sandbox data folder: the live settings, characters and roles; none of the live records."""
    if DRILL.resolve() == LIVE.resolve():
        raise SystemExit("drill: the sandbox folder is the live data folder")
    stop()
    shutil.rmtree(DRILL, ignore_errors=True)
    DRILL.mkdir(parents=True)
    for name in COPY:
        src = LIVE / name
        if src.is_dir():
            shutil.copytree(src, DRILL / name, symlinks=True,
                            ignore=lambda d, names: [n for n in names if Path(d) == LIVE / "workspace" and n in SKIP])
        elif src.is_file():
            shutil.copy2(src, DRILL / name)
    cfg = DRILL / "workspace" / ".gemini" / "config" / "mcp_config.json"
    if cfg.is_file():
        platform_compat.write_text(cfg, cfg.read_text(encoding="utf-8").replace(":3012/", ":%d/" % MCP_PORT), encoding="utf-8")
    _home()
    subprocess.run([sys.executable, str(CODE / "data_bootstrap.py"), "--data", str(DRILL), "--quiet"], env=_env(),
                   check=False)


def start() -> None:
    env = _env()
    (DRILL / "logs").mkdir(parents=True, exist_ok=True)
    for name, script in (("mcp", "mcp_server.py"), ("chat", "server.py")):
        with open(DRILL / "logs" / ("%s.out" % name), "ab") as log:   # binary: the child writes its own bytes
            p = subprocess.Popen([sys.executable, str(CODE / script)], cwd=str(CODE), env=env, stdout=log,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        platform_compat.write_text(DRILL / ("%s.pid" % name), str(p.pid), encoding="utf-8")
    for _ in range(60):
        try:
            if api("GET", "/healthz", timeout=2) is not None:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    raise SystemExit("drill: the sandbox host did not come up (see %s)" % (DRILL / "logs" / "chat.out"))


def stop() -> None:
    """Stop the sandbox host, then every agent left working in its workspace (ctl_proc reap)."""
    for name in ("chat", "mcp"):
        try:
            platform_compat.terminate(int((DRILL / ("%s.pid" % name)).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    time.sleep(2)
    if (DRILL / "workspace").is_dir():
        subprocess.run([sys.executable, str(CODE / "ctl_proc.py"), "reap", str(CODE), str(DRILL)], env=_env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def api(method: str, path: str, body: Optional[dict] = None, timeout: float = 15):
    base = "http://127.0.0.1:%d" % PORT
    hdrs = {"Origin": base, "X-Chatbot-Caller": "handoff-drill"}
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(base + path, data=data, method=method, headers=hdrs),
                                timeout=timeout) as r:
        raw = r.read().decode() or "{}"
        return json.loads(raw) if raw.lstrip().startswith(("{", "[")) else raw


# ---- facts ---------------------------------------------------------------------------------------------------------

class Cast:
    """Who plays what, from the sandbox team (roles are never named in code, TEAM_ROLES_v2): the sender is the team's
    default; the worker is the member holding the most other roles; the third is the member left."""

    def __init__(self, team: dict):
        members = team.get("members", {})
        self.sender = team.get("default") or next(iter(members))
        rest = sorted((c for c in members if c != self.sender), key=lambda c: -len(members[c]))
        if len(rest) < 2:
            raise SystemExit("drill: the team needs three members (a default and two more)")
        self.worker, self.third = rest[0], rest[1]
        self.roles = {c: list(members[c]) for c in members}

    def role(self, cid: str) -> str:
        return self.roles[cid][0]


def team() -> Cast:
    return Cast(json.loads((DRILL / "workspace" / "team.json").read_text(encoding="utf-8")))


def session_for(cid: str) -> str:
    return api("POST", "/api/sessions", {"character": cid, "mode": "work"})["session"]["id"]


def session(sid: str) -> dict:
    return api("GET", "/api/sessions/%s" % sid)


def events(since: float) -> List[dict]:
    out = []
    try:
        lines = (DRILL / "logs" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if _epoch(e.get("ts", "")) >= since:
            out.append(e)
    return out


def _live_events(since: float) -> List[dict]:
    out = []
    try:
        with open(host_config.EVENTS_LOG, encoding="utf-8") as f:
            for line in f:
                if '"mcp.' in line:
                    e = json.loads(line)
                    if _epoch(e.get("ts", "")) >= since:
                        out.append(e)
    except (OSError, ValueError):
        pass
    return out


def _epoch(ts: str) -> float:
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return 0.0


def wait_closed(hid: int, limit: float = WAIT_SEC) -> dict:
    end = time.time() + limit
    while time.time() < end:
        h = H.all_handoffs().get(hid, {})
        if h.get("state") in H.CLOSED:
            return h
        time.sleep(5)
    return H.all_handoffs().get(hid, {})


def wait_idle(sid: str, limit: float = 300) -> None:
    end = time.time() + limit
    while time.time() < end and session(sid).get("busy"):
        time.sleep(3)


def usage(sid: str, since: float) -> Dict[str, int]:
    """Fresh input, cached input and output tokens of the session's turns that ended after `since`."""
    tot = {"input": 0, "cached": 0, "output": 0}
    for h in session(sid).get("history") or []:
        u = h.get("usage") or {}
        if h.get("role") == "assistant" and float(h.get("ts") or 0) >= since and u:
            tot["input"] += int(u.get("input_tokens") or 0)
            tot["cached"] += int(u.get("cache_read_tokens") or 0)
            tot["output"] += int(u.get("output_tokens") or 0)
    return tot


def ledger_states(hid: int) -> List[str]:
    out = []
    for line in Path(os.environ["CHATBOT_HANDOFFS_FILE"]).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("id") == hid:
            out.append(r.get("state"))
    return out


# ---- scenarios -----------------------------------------------------------------------------------------------------

class Run:
    """One scenario's facts and checks."""

    def __init__(self, name: str):
        self.name, self.t0, self.checks, self.facts = name, time.time(), [], {}

    def check(self, ok: bool, what: str) -> None:
        self.checks.append((bool(ok), what))

    @property
    def ok(self) -> bool:
        return all(ok for ok, _ in self.checks) and bool(self.checks)


def _silence(run: Run, since: float) -> None:
    ev = [e.get("evt") for e in events(since)]
    run.facts["silent"] = "%d notice, %d hang" % (ev.count("turn.silent_notice"), ev.count("turn.silent_hang"))
    run.check("turn.silent_hang" not in ev, "no working turn closed as silent")
    run.check("turn.silent_notice" not in ev, "no silence notice while the receiver worked")


def _handoff(run: Run, lead_sid: str, frm: str, to: str, role: str, task: str, done_when: str = "") -> dict:
    h = H.create(frm, lead_sid, to, role, task, done_when)
    run.facts["id"] = h["id"]
    done = wait_closed(h["id"])
    run.facts["states"] = "→".join(ledger_states(h["id"]))
    run.facts["sec"] = round(float(done.get("state_at", time.time())) - float(h["at"]))
    return done


def sc_refuse(run: Run, t: Cast, lead: str) -> None:
    """The engine refuses a second open handoff to the same director, and one to oneself (no model turn)."""
    a = H.create(t.sender, lead, t.worker, t.role(t.worker), "drill: hold")
    try:
        H.create(t.sender, lead, t.worker, t.role(t.worker), "drill: second")
        run.check(False, "a second open handoff to one director is refused")
    except H.HandoffError:
        run.check(True, "a second open handoff to one director is refused")
    try:
        H.create(t.sender, lead, t.sender, t.role(t.sender), "drill: self")
        run.check(False, "a handoff to oneself is refused")
    except H.HandoffError:
        run.check(True, "a handoff to oneself is refused")
    H.mark(a["id"], "cancelled", reason="drill")


def sc_subagents(run: Run, t: Cast, lead: str) -> None:
    """Research split over parallel subagents: done with a result, never cut as silent, report back to the lead."""
    dev_sid = session_for(t.worker)
    done = _handoff(run, lead, t.sender, t.worker, "dev",
                    "Research only, change nothing. Use two subagents in parallel: (A) summarize the silent-turn "
                    "notice and close flow in services/chatbot/turn_watchdog.py; (B) summarize the state changes "
                    "in services/chatbot/dialog_handoff.py. Merge into five lines each.",
                    "both summaries, five lines each")
    run.check(done.get("state") == "done", "the handoff is done")
    run.check(len(str(done.get("result") or "")) > 200, "it carries a result")
    run.facts["tokens"] = usage(dev_sid, run.t0)
    _silence(run, run.t0)
    wait_idle(lead)
    run.check(any(float(h.get("ts") or 0) >= run.t0 and h.get("role") == "assistant"
                  for h in session(lead).get("history") or []), "the lead told the user")


def sc_chain(run: Run, t: Cast, lead: str) -> None:
    """A handoff that hands part on: the first waits for its child and finishes after it (HANDOFF_CHAIN_v1)."""
    session_for(t.worker), session_for(t.third)
    done = _handoff(run, lead, t.sender, t.worker, "dev",
                    "Two parts. Part 1 is not yours: hand it to the %s role -- one line describing a mood image for "
                    "a rainy office, no image made. Part 2 is yours: once that line is back, say in one line which "
                    "file in services/chatbot defines the handoff prompt." % t.role(t.third),
                    "the mood line and the file name")
    kids = [c for c in H.all_handoffs().values() if c.get("parent") == done.get("id")]
    run.facts["children"] = ["#%d %s" % (c["id"], c.get("state")) for c in kids]
    run.check(bool(kids), "it handed a part on (a child handoff)")
    run.check(all(c.get("state") == "done" for c in kids), "the child is done")
    states = ledger_states(done["id"])
    run.check("waiting" in states or "resume" in states, "the first one waited for its child")
    run.check(done.get("state") == "done" and states[-1] == "done", "the first one finished after the child")
    _silence(run, run.t0)


def sc_busy(run: Run, t: Cast, lead: str) -> None:
    """A handoff arriving while its receiver is in the user's turn starts after it, and answers its own task."""
    dev_sid = session_for(t.worker)
    api("POST", "/api/sessions/%s/message" % dev_sid, {"text": "In one line: what is 17 * 23? No tools."})
    time.sleep(1)
    busy_at = time.time()
    done = _handoff(run, lead, t.sender, t.worker, "dev",
                    "Research only. In one line: which function in services/chatbot/dialog_handoff.py starts a "
                    "waiting handoff's turn? Name it as DRILL-ANSWER: <name>.", "the function name")
    hist = [h for h in session(dev_sid).get("history") or [] if h.get("role") == "assistant"]
    user_end = min((float(h["ts"]) for h in hist if float(h.get("ts") or 0) >= busy_at - 1), default=0)
    run.facts["user_turn_end"] = round(user_end - busy_at, 1)
    run.check(float(done.get("started", 0)) >= user_end > 0, "the handoff started after the user's turn ended")
    run.check("DRILL-ANSWER" in str(done.get("result") or ""), "its result answers the handoff, not the user")


def sc_restart(run: Run, t: Cast, lead: str) -> None:
    """The host restarts mid-handoff: it ends (done or failed with a reason), never stays open."""
    session_for(t.worker)
    h = H.create(t.sender, lead, t.worker, t.role(t.worker),
                 "Research only. Use one subagent to list the functions in services/chatbot/session_turn.py with one "
                 "line each.", "the list")
    run.facts["id"] = h["id"]
    end = time.time() + 120
    while time.time() < end and H.all_handoffs()[h["id"]].get("state") != "running":
        time.sleep(3)
    time.sleep(20)
    stop()
    start()
    done = wait_closed(h["id"], 600)
    run.facts["states"] = "→".join(ledger_states(h["id"]))
    run.facts["reason"] = str(done.get("reason") or "")[:120]
    run.check(done.get("state") in ("done", "failed"), "it closed after the restart")
    run.check(done.get("state") == "done" or bool(done.get("reason")), "a failure says why")
    run.check(done.get("state") != "done" or "_start_turn" in str(done.get("result") or ""),
              "a done one carries the list, not a promise")


SCENARIOS: Dict[str, Callable] = {"refuse": sc_refuse, "subagents": sc_subagents, "chain": sc_chain,
                                  "busy": sc_busy, "restart": sc_restart}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        for n, f in SCENARIOS.items():
            print("%-10s %s" % (n, (f.__doc__ or "").strip()))
        return 0
    names = a.names or list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        print("drill: no scenario %s (see --list)" % ", ".join(unknown), file=sys.stderr)
        return 2
    t_start = time.time()
    build()
    start()
    runs = []
    try:
        t = team()
        for n in names:
            lead = session_for(t.sender)
            run = Run(n)
            try:
                SCENARIOS[n](run, t, lead)
            except Exception as e:  # noqa: BLE001 -- a broken scenario is a failed one, the rest still run
                run.check(False, "ran without error (%s: %s)" % (type(e).__name__, str(e)[:160]))
            for h in H.all_handoffs().values():   # leave nothing open for the next scenario
                if h.get("state") in H.OPEN:
                    H.mark(h["id"], "cancelled", reason="drill: scenario %s ended" % n)
            runs.append(run)
            print(report(run), flush=True)
    finally:
        if not a.keep:
            stop()
    leak = Run("isolation")
    seen = [e for e in _live_events(t_start) if e.get("evt") == "mcp.caller_unknown"]
    leak.facts["live_unknown_callers"] = len(seen)
    leak.check(not seen, "no drill agent reached the live tool server")
    runs.append(leak)
    print(report(leak), flush=True)
    passed = sum(r.ok for r in runs)
    print("---\n%d/%d scenarios passed" % (passed, len(runs)))
    return 0 if passed == len(runs) else 1


def report(run: Run) -> str:
    lines = ["%s %-10s %s" % ("ok  " if run.ok else "FAIL", run.name,
                              "  ".join("%s=%s" % kv for kv in run.facts.items()))]
    lines += ["     %s %s" % ("✓" if ok else "✗", what) for ok, what in run.checks]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
