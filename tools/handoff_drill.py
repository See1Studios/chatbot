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
  python3 tools/handoff_drill.py --provider grok subagents   the receiving directors on another provider

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
TOOL_CONFIGS = (".gemini/config/mcp_config.json", ".grok/config.toml", ".mcp.json")
PROVIDER = ""   # --provider: the receiving directors' sessions run on it (the sender keeps the team's default)

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
    for rel in TOOL_CONFIGS:   # each CLI's record of the tool server, as the live host wrote it
        cfg = DRILL / "workspace" / rel
        if cfg.is_file():
            platform_compat.write_text(cfg, cfg.read_text(encoding="utf-8").replace(":3012/", ":%d/" % MCP_PORT),
                                       encoding="utf-8")
    _home()
    subprocess.run([sys.executable, str(CODE / "data_bootstrap.py"), "--data", str(DRILL), "--quiet"], env=_env(),
                   check=False)


def start(limits: Optional[Dict[str, str]] = None) -> None:
    """Start the sandbox host; `limits` are extra settings for this start only (a short turn limit or budget)."""
    env = dict(_env(), **(limits or {}))
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
    sid = api("POST", "/api/sessions", {"character": cid, "mode": "work"})["session"]["id"]
    if PROVIDER and cid != json.loads((DRILL / "workspace" / "team.json").read_text(encoding="utf-8")).get("default"):
        got = api("POST", "/api/sessions/%s/provider" % sid, {"provider": PROVIDER})["session"].get("provider")
        if got != PROVIDER:
            raise RuntimeError("the receiver's session did not switch to %s (it runs %s)" % (PROVIDER, got))
    return sid


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


def answers(sid: str, since: float) -> List[dict]:
    """The session's recorded answers since `since` (history entries: when, not what they say)."""
    return [h for h in session(sid).get("history") or [] if h.get("role") == "assistant"
            and float(h.get("ts") or 0) >= since]


def turns(sid: str, since: float) -> List[dict]:
    """The session's turn.start / turn.end events since `since`, in order."""
    return [e for e in events(since) if e.get("sid") == sid and e.get("evt") in ("turn.start", "turn.end")]


def from_its_turn(done: dict, sid: str) -> bool:
    """The handoff closed on its own turn: after it started, the receiver began a host turn (turn.start notice) and
    that turn ended with a result (turn.end outcome "result") before the handoff closed. Event order only -- what the
    model said is never read. A promise cut by a restart has no such end; the user's turn is not a notice turn."""
    started, closed = float(done.get("started") or 0), float(done.get("state_at") or time.time())
    ev = [e for e in turns(sid, started) if _epoch(e.get("ts", "")) <= closed + 2]
    first = next((i for i, e in enumerate(ev) if e["evt"] == "turn.start" and e.get("notice")), None)
    return started > 0 and first is not None and any(e["evt"] == "turn.end" and e.get("outcome") == "result"
                                                     for e in ev[first:])


def layer_hashes(character: str, mode: str = "work", talk: str = "") -> Dict[str, str]:
    """Each layer's hash as the sandbox builds it now, and the hash of the lore `talk` matches: what an injection
    record must carry (instructions.build_instruction_bundle, session_turn._context_lore). Run in the sandbox's env so
    instructions reads the sandbox workspace, not the live one."""
    code = ("import hashlib, json, sys\n"
            "import instructions as I\n"
            "c, m, talk = sys.argv[1:4]\n"
            "h = lambda t: hashlib.sha256(t.encode('utf-8')).hexdigest()[:8] if t else ''\n"
            "out = {layer.id: h(t) for layer, t in I.layer_texts(m, c)}\n"
            "out['lore_match'] = h(I.lore_matches(c, talk))\n"
            "print(json.dumps(out))")
    p = subprocess.run([sys.executable, "-c", code, character, mode, talk], cwd=str(CODE), env=_env(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60,
                       check=False)
    return json.loads(p.stdout or "{}")


def ledger_states(hid: int) -> List[str]:
    out = []
    for line in Path(os.environ["CHATBOT_HANDOFFS_FILE"]).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("id") == hid:
            if r.get("state"):   # a cancel request carries no state
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
    run.check(from_its_turn(done, dev_sid), "it carries its own turn's answer")
    run.facts["tokens"] = usage(dev_sid, run.t0)
    _silence(run, run.t0)
    wait_idle(lead)
    run.check(any(float(h.get("ts") or 0) >= run.t0 and h.get("role") == "assistant"
                  for h in session(lead).get("history") or []), "the lead told the user")


def sc_chain(run: Run, t: Cast, lead: str) -> None:
    """A handoff that hands part on: the first waits for its child and finishes after it (HANDOFF_CHAIN_v1). The drill
    hands the part on itself, from the receiver's session while its handoff runs -- the engine's chaining is under
    test, not whether a model chose to hand off."""
    dev_sid = session_for(t.worker)
    session_for(t.third)
    h = H.create(t.sender, lead, t.worker, "dev",
                 "Research only. Use one subagent to list the functions in services/chatbot/dialog_handoff.py with one "
                 "line each.", "the list")
    run.facts["id"] = h["id"]
    end = time.time() + 120
    while time.time() < end and H.all_handoffs()[h["id"]].get("state") != "running":
        time.sleep(0.5)
    kid = H.create(t.worker, dev_sid, t.third, t.role(t.third), "Research only: name one file in services/chatbot.")
    run.check(kid.get("parent") == h["id"] and kid.get("hops") == 2, "the engine ties the part to the running handoff")
    done = wait_closed(h["id"])
    child = wait_closed(kid["id"], 60)
    states = ledger_states(h["id"])
    run.facts["states"] = "→".join(states)
    run.facts["child"] = "#%d %s" % (kid["id"], child.get("state"))
    run.check(child.get("state") == "done", "the child is done")
    run.check("waiting" in states or "resume" in states, "the first one waited for its child")
    run.check(done.get("state") == "done" and states[-1] == "done"
              and float(done.get("state_at") or 0) >= float(child.get("state_at") or 0),
              "the first one finished after the child")
    _silence(run, run.t0)


def sc_busy(run: Run, t: Cast, lead: str) -> None:
    """A handoff arriving while its receiver is in the user's turn starts after it, and answers its own task."""
    dev_sid = session_for(t.worker)
    asked = time.time()
    api("POST", "/api/sessions/%s/message" % dev_sid, {"text": "In one line: what is 17 * 23? No tools."})
    time.sleep(1)
    busy_at = time.time()
    done = _handoff(run, lead, t.sender, t.worker, "dev",
                    "Research only. In one line: which function in services/chatbot/dialog_handoff.py starts a "
                    "waiting handoff's turn?", "the function name")
    user_end = min((float(h["ts"]) for h in answers(dev_sid, busy_at - 1)), default=0)
    run.facts["user_turn_end"] = round(user_end - busy_at, 1)
    run.check(float(done.get("started", 0)) >= user_end > 0, "the handoff started after the user's turn ended")
    order = [(e["evt"], e.get("notice")) for e in turns(dev_sid, asked - 1)][:4]
    run.facts["turns"] = order
    run.check(order == [("turn.start", False), ("turn.end", None), ("turn.start", True), ("turn.end", None)],
              "the receiver ran the user's turn, then the handoff's")
    run.check(from_its_turn(done, dev_sid), "its result is the handoff turn's answer, not the user's")


def sc_restart(run: Run, t: Cast, lead: str) -> None:
    """The host restarts mid-handoff: it ends (done or failed with a reason), never stays open."""
    dev_sid = session_for(t.worker)
    h = H.create(t.sender, lead, t.worker, t.role(t.worker),
                 "Research only. Use one subagent to list the functions in services/chatbot/session_turn.py with one "
                 "line each.", "the list")
    run.facts["id"] = h["id"]
    end = time.time() + 120
    while time.time() < end and H.all_handoffs()[h["id"]].get("state") != "running":
        time.sleep(3)
    time.sleep(20)
    restart_at = time.time()
    stop()
    start()
    done = wait_closed(h["id"], 600)
    run.facts["states"] = "→".join(ledger_states(h["id"]))
    run.facts["reason"] = str(done.get("reason") or "")[:120]
    run.check(done.get("state") in ("done", "failed"), "it closed after the restart")
    run.check(done.get("state") == "done" or bool(done.get("reason")), "a failure says why")
    run.facts["resent"] = float(done.get("started") or 0) >= restart_at
    run.check(done.get("state") != "done" or from_its_turn(done, dev_sid),
              "a done one carries a finished turn's answer, not a promise cut by the restart")


def sc_cancel(run: Run, t: Cast, lead: str) -> None:
    """The operator cancels a running handoff (its turn stops, it never comes back done) and a waiting one (it never
    starts, and the receiver's own turn goes on) (HANDOFF_CANCEL_v1)."""
    dev_sid = session_for(t.worker)
    h = H.create(t.sender, lead, t.worker, t.role(t.worker),
                 "Research only. Use two subagents to read services/chatbot/session.py and session_turn.py whole and "
                 "list every method with one line each.", "the full list")
    end = time.time() + 120
    while time.time() < end and H.all_handoffs()[h["id"]].get("state") != "running":
        time.sleep(2)
    time.sleep(20)
    t0 = time.time()
    api("POST", "/api/handoffs/%d/cancel" % h["id"], {"reason": "drill: called off"})
    done = wait_closed(h["id"], 30)
    wait_idle(dev_sid, 30)
    run.facts["running_id"] = h["id"]
    run.facts["stop_sec"] = round(time.time() - t0, 1)
    run.check(done.get("state") == "cancelled" and done.get("reason") == "drill: called off",
              "a running one closes as cancelled, with the reason given")
    run.check(not session(dev_sid).get("busy"), "its turn stopped")
    time.sleep(40)
    run.check(ledger_states(h["id"])[-1] == "cancelled", "it does not come back done afterwards")
    asked = time.time()
    api("POST", "/api/sessions/%s/message" % dev_sid, {"text": "In one line: what is 19 * 21? No tools."})
    time.sleep(1)
    w = H.create(t.sender, lead, t.worker, t.role(t.worker), "Research only: name one file in services/chatbot.")
    api("POST", "/api/handoffs/%d/cancel" % w["id"], {"reason": "drill: not needed"})
    wait_idle(dev_sid, 120)
    run.facts["waiting_id"] = w["id"]
    run.check("running" not in ledger_states(w["id"]) and H.all_handoffs()[w["id"]].get("state") == "cancelled",
              "a waiting one never starts")
    after = turns(dev_sid, asked)
    run.facts["turns_after"] = [(e["evt"], e.get("notice"), e.get("outcome")) for e in after]
    run.check([e.get("notice") for e in after if e["evt"] == "turn.start"] == [False]
              and any(e["evt"] == "turn.end" and e.get("outcome") == "result" for e in after)
              and bool(answers(dev_sid, asked)), "the receiver's own turn went on and ended with its answer")
    _silence(run, run.t0)


def _with_limits(limits: Dict[str, str], t: Cast) -> str:
    """Restart the sandbox host with `limits`; the lead's new session there."""
    stop()
    start(limits)
    return session_for(t.sender)


def _restore() -> None:
    stop()
    start()


def sc_timeout(run: Run, t: Cast, lead: str) -> None:
    """A handoff whose turn runs out of time (a 60 s limit here) closes as failed saying so -- not done with what it said
    before the wait (the 8-minute limit, handoff #5 2026-10-05)."""
    try:
        lead = _with_limits({"CHATBOT_AGY_TURN_TIMEOUT_SEC": "60"}, t)
        session_for(t.worker)
        done = _handoff(run, lead, t.sender, t.worker, t.role(t.worker),
                        "Research only. Use two subagents: one reads services/chatbot/session.py whole, the other "
                        "services/chatbot/session_turn.py whole; each lists every method with one line. Merge both lists.",
                        "both full lists")
        run.facts["reason"] = str(done.get("reason") or "")[:90]
        run.check(done.get("state") == "failed", "it is not done")
        run.check("out of time" in str(done.get("reason") or ""), "the reason says it ran out of time")
        run.check(float(run.facts.get("sec", 999)) < 200, "it closed soon after the limit")
        _silence(run, run.t0)
    finally:
        _restore()


def sc_budget(run: Run, t: Cast, lead: str) -> None:
    """A handoff turn past its tool-call budget (warn 3, stop 6 here) is stopped and closes as partial or failed with
    the budget as its reason, never as done (HANDOFF_PARTIAL_v1)."""
    try:
        lead = _with_limits({"CHATBOT_TURN_BUDGET_CALLS": "3,6"}, t)
        session_for(t.worker)
        done = _handoff(run, lead, t.sender, t.worker, t.role(t.worker),
                        "Research only, no subagents: open these ten files one by one, each with its own tool call, and "
                        "give each one's first line: services/chatbot/session.py, session_turn.py, turn_watchdog.py, "
                        "dialog_handoff.py, dialog_tool.py, event_react.py, loop_guard.py, write_guard.py, "
                        "role_guard.py, mcp_server.py.", "ten first lines")
        ev = [e for e in events(run.t0) if "loop" in str(e.get("evt")) or "budget" in json.dumps(e)]
        run.facts["guard_events"] = sorted({str(e.get("evt")) for e in ev})
        run.facts["reason"] = str(done.get("reason") or "")[:90]
        run.check(bool(ev), "the budget stopped the turn")
        run.check(done.get("state") in ("partial", "failed"), "it closes as partial or failed, never done")
        run.check("budget" in str(done.get("reason") or ""), "the reason says it was the budget")
        _silence(run, run.t0)
        time.sleep(25)   # the reactor's next pass starts the lead's report turn
        wait_idle(lead, 180)
        said = answers(lead, run.t0)
        run.facts["lead_answers"] = len(said)
        run.check(bool(said), "the lead told the user")
    finally:
        _restore()


def _say(sid: str, text: str) -> None:
    """Send one message and wait for its turn to end."""
    api("POST", "/api/sessions/%s/message" % sid, {"text": text})
    time.sleep(2)
    wait_idle(sid, 240)


def _carried(sid: str, inject: dict) -> bool:
    """The injection went into a turn of `sid` that started and ended with a result: its request id is a turn.start's,
    and a turn.end (outcome "result") follows."""
    ev = turns(sid, _epoch(inject.get("ts", "")) - 1)
    starts = [i for i, e in enumerate(ev) if e["evt"] == "turn.start" and e.get("rid") == inject.get("rid")]
    return bool(starts) and any(e["evt"] == "turn.end" and e.get("outcome") == "result" for e in ev[starts[0]:])


def _injected(sid: str, since: float) -> List[dict]:
    return [e for e in events(since) if e.get("evt") == "context.inject" and e.get("sid") == sid]


def sc_context(run: Run, t: Cast, lead: str) -> None:
    """What a conversation's agent is given (layered-context-architecture lca/G): the whole bundle on the first turn, a
    memory edit refreshes only that layer and the agent answers from it, a keyword adds its lore once, a private
    session takes no work layer, the status tab's record matches, and no context alert."""
    import characters
    import instructions
    ws = DRILL / "workspace"
    characters.save_lorebook(t.sender, {"entries": [{"keys": ["office cat"], "position": "after_char",
                                                     "content": "The office cat is named Moka. It sleeps by the "
                                                                "window plant."}]}, ws)
    _say(lead, "In one line: hello?")
    first = _injected(lead, run.t0)
    ids = [x["id"] for x in (first[0]["layers"] if first else [])]
    run.facts["first"] = "%s %d chars" % (first[0]["why"], first[0]["chars"]) if first else "none"
    run.check(bool(first) and first[0]["why"] == "first" and {"charter", "persona"} <= set(ids),
              "the first turn takes the whole bundle")
    was = {x["id"]: x.get("hash") for x in (first[0]["layers"] if first else [])}
    mem = ws / "memory" / "MEMORY.md"
    mem.parent.mkdir(parents=True, exist_ok=True)
    platform_compat.write_text(mem, (mem.read_text(encoding="utf-8") if mem.is_file() else "# Memory\n")
                               + "- [2026-10-06] The operator's code word is teal\n", encoding="utf-8")
    t1 = time.time()
    _say(lead, "In one line: what is my code word?")
    refresh = _injected(lead, t1)
    run.facts["refresh"] = [(e["why"], [x["id"] for x in e["layers"]]) for e in refresh]
    run.check([e["why"] for e in refresh] == ["refresh"] and [x["id"] for x in refresh[0]["layers"]] == ["house_memory"],
              "a memory edit refreshes that layer only")
    now = layer_hashes(t.sender, talk="office cat")
    got = refresh[0]["layers"][0].get("hash") if refresh and refresh[0]["layers"] else ""
    run.check(bool(got) and got == now.get("house_memory") != was.get("house_memory"),
              "the refresh carries the edited memory as the sandbox builds it")
    run.check(bool(refresh) and _carried(lead, refresh[0]), "that turn carried it and ended with an answer")
    t2 = time.time()
    _say(lead, "In one line: what is the office cat's name?")
    lore = _injected(lead, t2)
    run.check([e["why"] for e in lore] == ["lore"], "a keyword adds its lore")
    run.check(bool(lore) and bool(now.get("lore_match")) and lore[0]["layers"][0].get("hash") == now["lore_match"],
              "the lore block is the entry the keyword matches")
    run.check(bool(lore) and _carried(lead, lore[0]), "that turn carried it and ended with an answer")
    t3 = time.time()
    _say(lead, "In one line: where does the office cat sleep?")
    run.check(_injected(lead, t3) == [], "the same keyword again adds nothing")
    record = api("GET", "/api/sessions/%s/context" % lead).get("records") or []
    run.check([r["why"] for r in record] == ["first", "refresh", "lore"], "the status tab's record matches")
    private = api("POST", "/api/sessions", {"character": t.sender, "mode": "private"})["session"]["id"]
    t4 = time.time()
    _say(private, "In one line: hello?")
    got = _injected(private, t4)
    work_only = {layer.id for layer in instructions.LAYERS if "private" not in layer.modes}
    pids = {x["id"] for x in (got[0]["layers"] if got else [])}
    run.facts["private_layers"] = sorted(pids)
    run.check(bool(got) and got[0]["mode"] == "private" and not (pids & work_only), "a private session takes no work layer")
    alerts = [e for e in events(run.t0) if e.get("evt") == "context.alert"]
    run.facts["alerts"] = len(alerts)
    run.check(not alerts, "no context alert")


def _tool(args: dict, who: dict) -> dict:
    """The dialog tool as `who` would call it, run in a process with the sandbox's settings: this one's modules read
    the live data folder."""
    code = ("import json, sys; sys.path.insert(0, %r); import dialog_tool; "
            "env = lambda ok, msg, data: {'success': ok, 'message': msg, 'data': data}; "
            "print(json.dumps(dialog_tool.call(json.loads(sys.argv[1]), env, json.loads(sys.argv[2]))))" % str(CODE))
    env = dict(_env(), CHATBOT_HANDOFFS_FILE=str(DRILL / "handoffs.jsonl"))
    r = subprocess.run([sys.executable, "-c", code, json.dumps(args), json.dumps(who)], cwd=str(CODE), env=env,
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"success": False, "message": (r.stderr or r.stdout)[-300:]}


def sc_default_role(run: Run, t: Cast, lead: str) -> None:
    """A handoff to a role nobody holds goes to the team's default character, says so, and is done there; the default
    handing one off itself is told it is its own (DEFAULT_ROLE_v1)."""
    unheld = next((p.name for p in sorted((DRILL / "workspace" / "roles").iterdir())
                   if (p / "ROLE.md").is_file() and p.name not in {r for rs in t.roles.values() for r in rs}), "")
    run.facts["role"] = unheld
    if not unheld:
        run.check(False, "the team has a role pack nobody holds")
        return
    worker_sid = session_for(t.worker)
    ask = "Research only: in one line, what does the file services/chatbot/dialog_handoff.py do?"
    out = _tool({"action": "handoff", "to": unheld, "text": ask},
                {"id": worker_sid, "character": t.worker, "mode": "work", "private": False})
    run.check(bool(out.get("success")), "the handoff is accepted (%s)" % str(out.get("message"))[:80])
    hid = (out.get("data") or {}).get("handoff")
    done = wait_closed(hid) if hid else {}
    run.facts["states"] = "→".join(ledger_states(hid)) if hid else "-"
    run.check(done.get("to") == t.sender and "Nobody holds" in str(done.get("task")), "it went to the default, saying so")
    run.check(done.get("state") == "done", "the default did it")
    mine = _tool({"action": "handoff", "to": unheld, "text": "x"},
                 {"id": lead, "character": t.sender, "mode": "work", "private": False})
    run.check(not mine.get("success") and "yours" in str(mine.get("message")), "the default is told it is its own")


SCENARIOS: Dict[str, Callable] = {"refuse": sc_refuse, "subagents": sc_subagents, "chain": sc_chain,
                                  "busy": sc_busy, "restart": sc_restart,
                                  "cancel": sc_cancel, "timeout": sc_timeout, "budget": sc_budget,
                                  "context": sc_context, "default_role": sc_default_role}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--provider", default="", help="run the receiving directors on this provider (e.g. grok)")
    a = ap.parse_args(argv)
    global PROVIDER
    PROVIDER = a.provider
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
