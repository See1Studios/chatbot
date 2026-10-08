#!/usr/bin/env python3
"""Read logs/events.jsonl (OBSLOG_v1) and say what happened, what is wrong, and where to look.

Views over the one event stream (OPERATIONS.md):
  logdigest.py [--since 24h]            findings first, then process / HTTP / errors / turns / ops / MCP
  logdigest.py --json                   the same digest as one JSON object (for agents)
  logdigest.py --sid SID                one session: global events + its events.jsonl, merged by time
  logdigest.py --rid RID | --fp FP      every line of one request / one error fingerprint
  logdigest.py --evt PREFIX             raw lines whose evt starts with PREFIX, human format
  logdigest.py -f                       follow new lines in human format (tail -f for people)
  --all                                 include rotated files older than --since window (for first-seen checks)
  --to-candidates                       findings -> observation candidates (host:<code>), at most hourly
Also: chatbot-ctl.sh logs [same flags].
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

if __package__ in (None, ""):   # run as a script (chatbot-ctl.sh): the engine folder is the import root
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent
# LOG_PATH_v1: the stream obslog writes and this reader parses come from one resolver (host_config),
# env override included. Tests still swap logdigest.LOG directly.
from host_config import EVENTS_LOG as LOG  # noqa: E402
from host_config import SESSIONS, WORKSPACE  # noqa: E402  -- one data-path resolver (uds/B)
import platform_compat
HEARTBEAT_SEC = int(os.environ.get("CHATBOT_OBSLOG_SUMMARY_SEC", "300"))

# Thresholds for findings. Tune here, and keep OPERATIONS.md "Findings" in step.
REPAIRS_PER_DAY_WARN = 6
ERR_RATE_WARN = 0.01
P95_SLOW_MS = 2000
RSS_GROWTH_MB = 150
TURN_FAIL_RATE_WARN = 0.2
CLIENT_ERR_REPEAT_WARN = 50
_CLIENT_GONE_TYPES = ("BrokenPipeError", "ConnectionResetError", "ConnectionAbortedError")

# Host signals (docs/plans/recursive-self-evolution.md §4.2/§4.4): findings become observation
# candidates so a review also sees what the host measured, not only what the operator said.
HOST_SIGNAL_EVERY_SEC = 3600
HOST_SIGNAL_WINDOW_SEC = 2 * 3600
HOST_SIGNAL_STAMP = LOG.with_name(".host-signals.stamp")
OBS_ROOT = WORKSPACE / "skill-observations"


def parse_since(text: str) -> float:
    m = re.fullmatch(r"(\d+)([smhd])", text or "24h")
    if not m:
        raise SystemExit("--since: use N[s|m|h|d], e.g. 6h")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def ts_of(rec: dict) -> float:
    t = rec.get("_t")
    if t is None:
        try:
            t = datetime.fromisoformat(str(rec.get("ts"))).timestamp()
        except Exception:
            t = 0.0
        rec["_t"] = t
    return t


def log_files() -> List[Path]:
    files = [LOG.with_name("%s.%d" % (LOG.name, i)) for i in range(9, 0, -1)]
    return [p for p in files + [LOG] if p.exists()]


def shape(rec: dict) -> dict:
    """DIGEST_SHAPE_v1 (#831): every reader here takes `err` as a dict and each `routes` value as a dict. Some writers
    put text in `err` (git.commit_failed), and obslog's size cap cuts a big `routes` to a "…" entry; the digest
    crashed on both (2026-10-08). Text becomes {"msg": text}; a cut entry is dropped."""
    if isinstance(rec.get("err"), str):
        rec["err"] = {"msg": rec["err"]}
    elif "err" in rec and not isinstance(rec["err"], dict):
        rec.pop("err")
    if isinstance(rec.get("routes"), dict):
        rec["routes"] = {k: v for k, v in rec["routes"].items() if isinstance(v, dict)}
    elif "routes" in rec:
        rec.pop("routes")
    return rec


def read_events(since_t: float = 0.0) -> Iterable[dict]:
    for p in log_files():
        try:
            if since_t and p.stat().st_mtime < since_t:
                continue
            last_t = p.stat().st_mtime  # a broken line is placed at the previous good line's time
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = shape(json.loads(line))
                        last_t = ts_of(rec) or last_t
                    except ValueError:
                        rec = {"ts": datetime.fromtimestamp(last_t).astimezone().isoformat(timespec="milliseconds"),
                               "lvl": "warn", "src": "logdigest", "evt": "log.bad_line", "msg": line[:200], "_t": last_t}
                    if ts_of(rec) >= since_t:
                        yield rec
        except OSError:
            continue


# -- human line -------------------------------------------------------------------------
_SKIP = {"ts", "lvl", "src", "evt", "pid", "msg", "_t", "err", "routes"}


def human(rec: dict) -> str:
    ts = str(rec.get("ts", ""))[5:23].replace("T", " ")
    parts = ["%s %-5s %-4s %-22s" % (ts, str(rec.get("lvl", "")).upper(), rec.get("src", ""), rec.get("evt", ""))]
    for k, v in rec.items():
        if k in _SKIP or v in (None, "", [], {}):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)[:160]
        parts.append("%s=%s" % (k, v))
    if rec.get("msg"):
        parts.append("| " + str(rec["msg"])[:300])
    err = rec.get("err")
    if isinstance(err, dict):
        parts.append("| %s: %s @%s fp=%s" % (err.get("type"), err.get("msg"), err.get("where"), err.get("fp")))
    if rec.get("evt") == "http.summary":
        parts.append("routes=%d" % len(rec.get("routes") or {}))
    return " ".join(parts)


# -- digest -----------------------------------------------------------------------------
def pct(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(q * len(v)))], 1)


CONTEXT_ALERT_HINTS = {
    "over_budget": ("warn", "static layers over bundle_budget.json",
                    "logdigest.py --evt context.inject shows the large layers; trim them, or the operator sets the bound"),
    "missing": ("warn", "a required layer is empty", "check that the charter (AGENTS.md) and the card exist"),
    "leak": ("error", "a work layer in a private bundle", "check the modes in instructions.LAYERS and context.alert's layers"),
}


def _context_summary(win: List[Dict[str, Any]], find=None) -> Dict[str, Any]:
    """CONTEXT_LOG_v1: what went into the agents -- injections by why and by mode, the largest; CONTEXT_ALERT_v1: each
    alert kind seen becomes a finding."""
    inj = [e for e in win if e.get("evt") == "context.inject"]
    alerts = Counter(str(e.get("kind")) for e in win if e.get("evt") == "context.alert")
    for kind, n in alerts.items():
        sev, title, hint = CONTEXT_ALERT_HINTS.get(kind, ("warn", kind, "logdigest.py --evt context.alert"))
        if find is not None:
            find(sev, "context_" + kind, "%s (%d)" % (title, n), hint, count=n)
    return {"injections": len(inj), "by_why": dict(Counter(str(e.get("why")) for e in inj)),
            "by_mode": dict(Counter(str(e.get("mode")) for e in inj)),
            "max_chars": max((int(e.get("chars") or 0) for e in inj), default=0), "alerts": dict(alerts)}


def _digest_processes(events, win, since_t, now, find):
    procs: Dict[str, Dict[str, Any]] = {}
    unclean = []
    last_by_src: Dict[str, dict] = {}
    last_by_pid: Dict[tuple, dict] = {}
    starts_by_src: Dict[str, List[dict]] = defaultdict(list)
    for e in events:
        src, evt = e.get("src"), e.get("evt")
        if src not in ("chat", "mcp"):
            continue
        last_by_pid[(src, e.get("pid"))] = e
        if evt == "proc.start":
            starts_by_src[src].append(e)
        last_by_src[src] = e
    for (src, pid), last_e in last_by_pid.items():
        if last_e.get("evt") == "proc.exit":
            continue
        later = [s for s in starts_by_src[src] if s.get("pid") != pid and ts_of(s) >= ts_of(last_e)]
        if later and ts_of(later[0]) >= since_t:
            unclean.append({"src": src, "prev_pid": pid, "last_seen": last_e.get("ts"), "restart_at": later[0].get("ts")})
    for src in ("chat", "mcp"):
        mine = [e for e in win if e.get("src") == src]
        starts = [e for e in mine if e.get("evt") == "proc.start"]
        hbs = [e for e in mine if e.get("evt") == "proc.heartbeat"]
        gaps = []
        seq = [e for e in mine if e.get("evt") in ("proc.start", "proc.heartbeat", "proc.exit")]
        for a, b in zip(seq, seq[1:]):
            if a.get("evt") == "proc.exit" or b.get("evt") == "proc.start":
                continue
            if ts_of(b) - ts_of(a) > 2.5 * HEARTBEAT_SEC:
                gaps.append({"from": a.get("ts"), "to": b.get("ts"), "min": round((ts_of(b) - ts_of(a)) / 60, 1)})
        last = last_by_src.get(src)
        rss = [(ts_of(h), h.get("rss_mb")) for h in hbs if isinstance(h.get("rss_mb"), (int, float))]
        info: Dict[str, Any] = {"starts": len(starts), "heartbeats": len(hbs), "gaps": gaps,
                                "last_event": last.get("ts") if last else None,
                                "last_pid": last.get("pid") if last else None,
                                "git": (starts[-1].get("git") if starts else None)}
        if rss:
            info["rss_mb"] = {"first": rss[0][1], "last": rss[-1][1], "max": max(r for _, r in rss)}
            cur_pid_hbs = [h for h in hbs if h.get("pid") == hbs[-1].get("pid")]
            r2 = [h.get("rss_mb") for h in cur_pid_hbs if isinstance(h.get("rss_mb"), (int, float))]
            if len(r2) >= 6 and r2[-1] - r2[0] > RSS_GROWTH_MB:
                find("warn", "rss_growth", "%s memory grew %.0fMB (within one process lifetime)" % (src, r2[-1] - r2[0]),
                     "suspected leak: look at the heartbeat sessions/subscribers/threads trend alongside", src=src, first=r2[0], last=r2[-1])
        if hbs:
            h = hbs[-1]
            info["last_heartbeat"] = {k: h.get(k) for k in ("ts", "uptime_s", "threads", "fds", "sessions", "busy",
                                                             "subscribers", "agent_procs", "log_write_errors") if k in h}
            if h.get("log_write_errors"):
                find("warn", "log_write_errors", "%s log write failed %s times" % (src, h["log_write_errors"]),
                     "check logs/ disk space and permissions", src=src)
        if last and now - ts_of(last) > 2.5 * HEARTBEAT_SEC and last.get("evt") != "proc.exit" and win:
            find("error", "silent_process", "%s: no events for %d min (heartbeat stopped)" % (src, (now - ts_of(last)) // 60),
                 "the process hung or died: check chatbot-ctl.sh status and the end of logs/chatbot.log", src=src, last=last.get("ts"))
        for g in gaps:
            find("warn", "heartbeat_gap", "%s heartbeat gap of %s min" % (src, g["min"]),
                 "the process may have stalled then (lock/GIL/swap): check the events just before the gap with --evt", src=src, **g)
        procs[src] = info
    for u in unclean:
        find("error", "unclean_restart", "%s restarted after an unclean exit (pid %s, no proc.exit)" % (u["src"], u["prev_pid"]),
             "kill -9 / OOM / crash: check the last event before it, dmesg and logs/chatbot.log", **u)
    return procs, unclean


def _digest_errors(before, win, find):
    seen_before = {((e.get("err") or {}).get("fp")) for e in before if isinstance(e.get("err"), dict)}
    groups: Dict[str, Dict[str, Any]] = {}
    for e in win:
        err = e.get("err")
        if not isinstance(err, dict) or not err.get("fp"):
            continue
        if e.get("status") == "gone" and err.get("type") in _CLIENT_GONE_TYPES:
            continue  # written before OBSLOG_v1.4: a client that left, not a server bug
        g = groups.setdefault(err["fp"], {"fp": err["fp"], "type": err.get("type"), "msg": err.get("msg"),
                                          "where": err.get("where"), "count": 0, "evts": Counter(), "routes": Counter(),
                                          "first": e.get("ts"), "last": None, "sample_trace": None, "sids": set(),
                                          "new": err["fp"] not in seen_before, "lvl": e.get("lvl")})
        g["count"] += int(e.get("count") or 0) if e.get("evt") == "log.suppressed" else 1 + int(e.get("repeat") or 0)
        g["evts"][e.get("of_evt") or e.get("evt")] += 1
        if e.get("evt") == "log.suppressed":
            g["suppressed"] = g.get("suppressed", 0) + int(e.get("count") or 0)
        if e.get("route"):
            g["routes"][e["route"]] += 1
        if e.get("sid"):
            g["sids"].add(e["sid"])
        g["last"] = e.get("ts")
        if err.get("trace"):
            g["sample_trace"] = err["trace"][-1500:]
    errs = sorted(groups.values(), key=lambda g: -g["count"])
    for g in errs:
        g["evts"] = dict(g["evts"])
        g["routes"] = dict(g["routes"].most_common(5))
        g["sids"] = sorted(g["sids"])[:10]
        if g["lvl"] == "error":
            storm = " (storm: %d lines counted only)" % g["suppressed"] if g.get("suppressed") else ""
            find("error" if g["new"] else "warn", "error_fp", "%s%s ×%d%s: %s @%s" % ("[new] " if g["new"] else "", g["type"], g["count"], storm, (g["msg"] or "")[:120], g["where"]),
                 "logdigest.py --fp %s shows the full trace and the requests" % g["fp"], fp=g["fp"], routes=g["routes"])
    for e in win:
        if e.get("evt") in ("proc.crash", "thread.crash"):
            find("error", e["evt"].replace(".", "_"), "%s: %s" % (e["evt"], (e.get("err") or {}).get("msg")),
                 "logdigest.py --fp %s" % (e.get("err") or {}).get("fp"), src=e.get("src"), ts=e.get("ts"), thread=e.get("thread"))
    return errs


def _digest_http(win, find):
    routes: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"n": 0, "codes": Counter(), "p95": [], "max": 0.0})
    for e in win:
        if e.get("evt") == "http.summary":
            for r, s in (e.get("routes") or {}).items():
                key = "%s %s" % (e.get("src"), r)
                t = routes[key]
                t["n"] += s.get("n", 0)
                t["codes"].update(s.get("codes") or {})
                if s.get("p95") is not None:
                    t["p95"].append(s["p95"])
                t["max"] = max(t["max"], s.get("max") or 0)
    http = []
    for key, t in routes.items():
        n = t["n"] or 1
        e5 = t["codes"].get("5xx", 0)
        row = {"route": key, "n": t["n"], "codes": dict(t["codes"]), "err5_rate": round(e5 / n, 4),
               "p95_ms_worst": max(t["p95"]) if t["p95"] else None, "max_ms": round(t["max"], 1)}
        http.append(row)
        if e5 and (e5 >= 3 or e5 / n >= ERR_RATE_WARN):
            find("error", "http_5xx", "%s 5xx %d/%d (%.1f%%)" % (key, e5, t["n"], 100 * e5 / n),
                 "logdigest.py --evt http.error shows the trace", route=key)
        stream = key.endswith("/events")
        if not stream and row["p95_ms_worst"] and row["p95_ms_worst"] > P95_SLOW_MS and t["n"] >= 10:
            find("warn", "http_slow", "%s p95 %.0fms" % (key, row["p95_ms_worst"]), "slow route: check the handler's outside calls (CLI/files/locks)", route=key)
    http.sort(key=lambda r: -r["n"])
    ce = Counter()
    for e in win:
        if e.get("evt") == "http.client_error":
            ce["%s %s %s" % (e.get("src"), e.get("route"), e.get("status"))] += 1 + int(e.get("repeat") or 0)
    for k, c in ce.items():
        if c >= CLIENT_ERR_REPEAT_WARN:
            find("warn", "client_error_repeat", "%s ×%d" % (k, c), "a client repeats the same failing request: check what the UI polls", key=k)
    return {"routes": http[:40], "total": sum(r["n"] for r in http), "client_errors": dict(ce.most_common(15))}


def _digest_turns(win, find):
    tp: Dict[str, Counter] = defaultdict(Counter)
    durs: Dict[str, List[float]] = defaultdict(list)
    bad_turns = []
    for e in win:
        if e.get("evt") == "turn.end":
            p = str(e.get("provider"))
            tp[p][e.get("outcome")] += 1
            if isinstance(e.get("dur_s"), (int, float)):
                durs[p].append(e["dur_s"])
            if e.get("outcome") not in ("result", "stopped", "interrupted"):
                bad_turns.append({k: e.get(k) for k in ("ts", "sid", "provider", "model", "outcome", "dur_s", "error_hint")})
    turns = {}
    for p, c in tp.items():
        total = sum(c.values())
        bad = total - c.get("result", 0) - c.get("stopped", 0) - c.get("interrupted", 0)
        turns[p] = {"total": total, "outcomes": dict(c), "fail_rate": round(bad / total, 3) if total else 0,
                    "p50_s": pct(durs[p], 0.5), "p95_s": pct(durs[p], 0.95)}
        if total >= 5 and bad / total >= TURN_FAIL_RATE_WARN:
            find("error", "turn_failures", "%s turn failure rate %.0f%% (%d/%d)" % (p, 100 * bad / total, bad, total),
                 "logdigest.py --evt turn.end shows outcome and stderr_tail; for quota/sign-in problems check accounts", provider=p, outcomes=dict(c))
    died = [e for e in win if e.get("evt") == "agent.exit" and e.get("died_mid_turn")]
    if died:
        find("warn", "agent_died_mid_turn", "agent process ended mid-turn %d times" % len(died),
             "check rc and the agent.reaped just before (who ended it)", samples=[{k: x.get(k) for k in ("ts", "sid", "provider", "rc")} for x in died[-5:]])
    sessions = {k: sum(1 for e in win if e.get("evt") == k) for k in
                ("session.error", "session.session_rotate", "session.session_heavy", "turn.loop_notice", "turn.quiet_close",
                 "agent.spawn", "agent.exit", "agent.recycle")}
    return {"by_provider": turns, "failed": bad_turns[-20:]}, sessions


def _digest_main(events, find):
    """MAIN_WATCH_v1 (#825): the last whole-suite check of main (tools/main_watch.py). Red stays a finding, whatever
    the window, until a later check is green: the commit hook does not run the whole suite."""
    checks = [e for e in events if e.get("evt") == "main.check" and e.get("ok") is not None]
    if not checks:
        return {}
    last = checks[-1]
    green = next((e for e in reversed(checks) if e.get("ok")), None)
    out = {k: last.get(k) for k in ("ts", "sha", "subject", "ok", "failed")}
    out["last_green"] = green.get("sha") if green else None
    if not last.get("ok"):
        since = ("since %s" % out["last_green"]) if green else "in the last 7 days"
        find("error", "main_red", "main is red at %s: %s" % (last.get("sha"), " ".join(last.get("failed") or []) or "?"),
             "the break is a commit %s (git log %s..%s); fix it before more work lands"
             % (since, out["last_green"] or "", last.get("sha")), subject=last.get("subject"))
    return out


def _digest_ops(events, win, since_s, find):
    rep = [e for e in win if e.get("evt") == "repair.begin"]
    rep_end = [e for e in win if e.get("evt") == "repair.end"]
    callers = Counter(str(e.get("caller")) for e in rep)
    ops = {"repairs": len(rep), "repair_callers": dict(callers), "repair_failed": sum(1 for e in rep_end if not e.get("ok")),
           "repair_dur_s_p50": pct([e["dur_s"] for e in rep_end if isinstance(e.get("dur_s"), (int, float))], 0.5),
           "doctor_probe": dict(Counter("ok" if e.get("ok") else "fail" for e in win if e.get("evt") == "doctor.probe")),
           "doctor_fail": dict(Counter(str(e.get("check")) for e in win if e.get("evt") == "doctor.fail")),
           "reaped": dict(Counter(str(e.get("reason")) for e in win if e.get("evt") == "agent.reaped")),
           "defibrillate_api": sum(1 for e in win if e.get("evt") == "host.defibrillate"),
           "manifest_drift": sum(1 for e in win if e.get("evt") == "manifest.drift")}
    days = max(since_s / 86400.0, 1.0)  # a short window is not extrapolated to a day (2 in 10 min != 288/day)
    if len(rep) / days >= REPAIRS_PER_DAY_WARN:
        find("warn", "repair_frequent", "repair %d times (%.1f/day) caller=%s" % (len(rep), len(rep) / days, dict(callers)),
             "the root cause restarts cover up: read http.error/turn.end/doctor.probe before each repair in time order", callers=dict(callers))
    if ops["repair_failed"]:
        find("error", "repair_failed", "probe still failed after repair %d times" % ops["repair_failed"], "check the end of logs/chatbot.log and the doctor.probe msg")
    if ops["doctor_probe"].get("fail"):
        find("error", "probe_fail", "doctor probe failed %d times" % ops["doctor_probe"]["fail"], "logdigest.py --evt doctor.probe")
    lives: Dict[Any, List[float]] = {}
    for e in events:
        if e.get("src") == "chat" and e.get("evt") in ("proc.start", "proc.exit"):
            span = lives.setdefault(e.get("pid"), [ts_of(e), float("inf")])
            if e["evt"] == "proc.exit":
                span[1] = ts_of(e)
    for e in win:
        if e.get("evt") != "agent.reaped" or e.get("ppid") in (None, 1):
            continue
        span = lives.get(e.get("ppid"))
        if span and span[0] <= ts_of(e) <= span[1]:
            find("warn", "agent_reaped_live", "a child agy %s of the live chat server (pid %s) was reaped (%s)" % (e.get("agent_pid"), e["ppid"], e.get("reason")),
                 "check ctl reap_orphan_agents: the server's descendants are the server's to manage", ppid=e["ppid"], agent_pid=e.get("agent_pid"),
                 key="%s/%s" % (e.get("ppid"), e.get("reason")))
    return ops


def _digest_mcp(win):
    calls = Counter()
    fails: Dict[str, Counter] = defaultdict(Counter)
    for e in win:
        if e.get("evt") == "mcp.call":
            calls[e.get("tool")] += 1
            if not e.get("ok"):
                fails[str(e.get("tool"))][str(e.get("msg"))[:80]] += 1
    return {"calls": dict(calls.most_common(20)),
            "failures": {t: dict(c.most_common(5)) for t, c in fails.items()}}


def digest(since_s: float, include_all: bool = False) -> Dict[str, Any]:
    now = time.time()
    since_t = now - since_s
    events = list(read_events(0.0 if include_all else since_t - 7 * 86400))
    events.sort(key=ts_of)
    before = [e for e in events if ts_of(e) < since_t]
    win = [e for e in events if ts_of(e) >= since_t]
    d: Dict[str, Any] = {"window": {"since": datetime.fromtimestamp(since_t).isoformat(timespec="seconds"),
                                    "until": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
                                    "hours": round(since_s / 3600, 1), "events": len(win)}}
    d["counts"] = {"by_level": dict(Counter(e.get("lvl") for e in win)),
                   "by_src": dict(Counter(e.get("src") for e in win)),
                   "by_evt": dict(Counter(e.get("evt") for e in win).most_common(40))}
    findings: List[Dict[str, Any]] = []

    def find(sev: str, code: str, title: str, hint: str, **ev: Any) -> None:
        findings.append({"severity": sev, "code": code, "title": title, "hint": hint, "evidence": ev})

    d["processes"], d["unclean_restarts"] = _digest_processes(events, win, since_t, now, find)
    d["errors"] = _digest_errors(before, win, find)
    d["http"] = _digest_http(win, find)
    d["turns"], d["sessions"] = _digest_turns(win, find)
    d["context"] = _context_summary(win, find)
    d["ops"] = _digest_ops(events, win, since_s, find)
    d["mcp"] = _digest_mcp(win)
    d["main"] = _digest_main(events, find)

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 3))
    d["findings"] = findings
    d["status"] = "error" if any(f["severity"] == "error" for f in findings) else ("warn" if findings else "ok")
    return d


def render(d: Dict[str, Any]) -> str:
    w = d["window"]
    out = ["# Log digest  %s → %s (%sh, %d events)  status: %s" % (w["since"], w["until"], w["hours"], w["events"], d["status"].upper())]
    out.append("\n## Findings (%d)" % len(d["findings"]))
    if not d["findings"]:
        out.append("- all clear")
    for f in d["findings"]:
        out.append("- [%s] %s\n    → %s" % (f["severity"].upper(), f["title"], f["hint"]))
    out.append("\n## Processes")
    for src, p in d["processes"].items():
        hb = p.get("last_heartbeat") or {}
        out.append("- %s: %d starts, heartbeat %d, last %s pid=%s git=%s rss=%s state=%s" % (
            src, p["starts"], p["heartbeats"], p["last_event"], p["last_pid"], p.get("git"), p.get("rss_mb"),
            {k: v for k, v in hb.items() if k != "ts"}))
    out.append("\n## Error fingerprints (top)")
    for g in d["errors"][:10]:
        out.append("- %s %s ×%d %s @%s  %s~%s routes=%s%s" % (g["fp"], g["type"], g["count"], (g["msg"] or "")[:100], g["where"],
                                                           g["first"][5:19], (g["last"] or "")[5:19], g["routes"], " [new]" if g["new"] else ""))
    if not d["errors"]:
        out.append("- none")
    out.append("\n## HTTP (%d in all)" % d["http"]["total"])
    for r in d["http"]["routes"][:15]:
        out.append("- %-45s n=%-6d %s p95≤%sms max=%sms" % (r["route"][:45], r["n"], r["codes"], r["p95_ms_worst"], r["max_ms"]))
    if d["http"]["client_errors"]:
        out.append("  4xx: %s" % d["http"]["client_errors"])
    out.append("\n## Turns")
    for p, t in d["turns"]["by_provider"].items():
        out.append("- %s: %d turns %s failure rate %.0f%% p50=%ss p95=%ss" % (p, t["total"], t["outcomes"], 100 * t["fail_rate"], t["p50_s"], t["p95_s"]))
    for b in d["turns"]["failed"][-5:]:
        out.append("  · %s %s %s %s %ss %s" % (str(b["ts"])[5:19], b["sid"], b["provider"], b["outcome"], b["dur_s"], b.get("error_hint") or ""))
    out.append("  session events: %s" % {k: v for k, v in d["sessions"].items() if v})
    out.append("\n## Operations (repair/doctor)")
    out.append("- %s" % d["ops"])
    out.append("\n## MCP tools")
    out.append("- calls: %s" % d["mcp"]["calls"])
    if d["mcp"]["failures"]:
        out.append("- failures: %s" % d["mcp"]["failures"])
    return "\n".join(out)


# -- host signals -> observation candidates ---------------------------------------------
_KEY_FIELDS = ("fp", "route", "provider", "src", "key")


def _finding_key(f: Dict[str, Any]) -> str:
    ev = f.get("evidence") or {}
    for k in _KEY_FIELDS:
        if ev.get(k):
            return str(ev[k])[:120]
    return ""


def _summary(f: Dict[str, Any], key: str) -> str:
    """Host-made text only: code, key and numbers. Never err.msg or titles, which can carry
    outside text (§4.4: tool/web output must not be copied into observations)."""
    nums = ["%s=%s" % (k, v) for k, v in sorted((f.get("evidence") or {}).items())
            if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return " ".join(x for x in [f["code"], key] + nums if x)[:200]


def host_candidates(obs_root: Path = None, since_s: float = HOST_SIGNAL_WINDOW_SEC, force: bool = False,
                    now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Record current findings as candidates (signal host:<code>, sid "host"), each (signal, key) at
    most once a day. Throttled by a stamp file unless `force`. Returns what was recorded."""
    import evolution  # core module: layers may use the core, never the reverse
    obs_root = Path(obs_root or OBS_ROOT)
    now = time.time() if now is None else now
    if not force:
        try:
            if now - HOST_SIGNAL_STAMP.stat().st_mtime < HOST_SIGNAL_EVERY_SEC:
                return []
        except OSError:
            pass
    try:
        HOST_SIGNAL_STAMP.parent.mkdir(parents=True, exist_ok=True)
        platform_compat.write_text(HOST_SIGNAL_STAMP, str(int(now)), encoding="utf-8")
    except OSError:
        pass
    if not LOG.exists() or not obs_root.is_dir():
        return []
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    seen = set()
    try:
        with open(obs_root / evolution.CANDIDATES_NAME, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if str(row.get("signal", "")).startswith("host:") and str(row.get("ts", "")).startswith(today):
                    seen.add((row["signal"], str((row.get("detail") or {}).get("key", ""))))
    except OSError:
        pass
    out = []
    for f in digest(since_s)["findings"]:
        signal, key = "host:" + f["code"], _finding_key(f)
        if (signal, key) in seen:
            continue
        seen.add((signal, key))
        ev = f.get("evidence") or {}
        detail: Dict[str, Any] = {"severity": f["severity"], "key": key, "summary": _summary(f, key),
                                  "window_h": round(since_s / 3600, 1)}
        if ev.get("fp"):
            detail["log_ref"] = "log:fp:%s" % ev["fp"]
        if evolution.record_candidate(obs_root, signal, "host", str(ev.get("src") or ev.get("provider") or "host"), detail):
            out.append(dict(detail, signal=signal))
    return out


# -- other views ------------------------------------------------------------------------
def session_timeline(sid: str, since_t: float) -> List[dict]:
    rows = [e for e in read_events(since_t) if e.get("sid") == sid or (isinstance(e.get("busy"), list) and sid in e["busy"])]
    p = SESSIONS / sid / "events.jsonl"
    if p.exists():
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                t = ev.get("ts") or ev.get("_ts") or 0
                try:
                    t = float(t)
                except (TypeError, ValueError):
                    t = 0.0
                if t < since_t:
                    continue
                rows.append({"ts": datetime.fromtimestamp(t).astimezone().isoformat(timespec="milliseconds") if t else "",
                             "_t": t, "lvl": "info", "src": "sess", "evt": "session." + str(ev.get("event")),
                             "msg": str(ev.get("text") or "")[:300]})
    rows.sort(key=ts_of)
    return rows


def follow() -> None:
    pos = LOG.stat().st_size if LOG.exists() else 0
    ino = LOG.stat().st_ino if LOG.exists() else None
    while True:
        try:
            st = LOG.stat()
            if st.st_ino != ino or st.st_size < pos:
                ino, pos = st.st_ino, 0
            if st.st_size > pos:
                with open(LOG, encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    for line in f:
                        try:
                            print(human(json.loads(line)), flush=True)
                        except ValueError:
                            pass
                    pos = f.tell()
        except FileNotFoundError:
            pass
        time.sleep(1)


def as_json_flag(flags: set) -> bool:
    return "--json" in flags


def main(argv: List[str]) -> int:
    args = list(argv)
    opts: Dict[str, Any] = {"--since": "24h"}
    flags = set()
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--since", "--sid", "--rid", "--fp", "--evt") and i + 1 < len(args):
            opts[a] = args[i + 1]
            i += 2
            continue
        if a in ("--json", "--all", "-f", "--follow", "-h", "--help", "--to-candidates", "--force"):
            flags.add(a)
            i += 1
            continue
        sys.stderr.write("logdigest: unknown argument %s\n" % a)
        return 2
    if flags & {"-h", "--help"}:
        print(__doc__)
        return 0
    if flags & {"-f", "--follow"}:
        try:
            follow()
        except KeyboardInterrupt:
            return 0
    if "--to-candidates" in flags:
        got = host_candidates(force="--force" in flags)
        print(json.dumps(got, ensure_ascii=False) if as_json_flag(flags) else "host candidates recorded: %d" % len(got))
        return 0
    since_s = parse_since(opts["--since"])
    since_t = time.time() - since_s
    as_json = "--json" in flags
    rows: Optional[List[dict]] = None
    if "--sid" in opts:
        rows = session_timeline(opts["--sid"], since_t)
    elif "--rid" in opts:
        rows = [e for e in read_events(since_t) if e.get("rid") == opts["--rid"]]
    elif "--fp" in opts:
        rows = [e for e in read_events(since_t) if (e.get("err") or {}).get("fp") == opts["--fp"]]
    elif "--evt" in opts:
        rows = [e for e in read_events(since_t) if str(e.get("evt", "")).startswith(opts["--evt"])]
    if rows is not None:
        for r in rows:
            r.pop("_t", None)
            print(json.dumps(r, ensure_ascii=False) if as_json else human(r))
            if not as_json and "--fp" in opts and (r.get("err") or {}).get("trace") and r is rows[-1]:
                print(r["err"]["trace"])
        if not rows:
            print("(no matching events in the last %s)" % opts["--since"])
        return 0
    if not LOG.exists():
        print("no %s yet (OBSLOG_v1 starts writing when chat/mcp restart)" % LOG)
        return 1
    d = digest(since_s, include_all="--all" in flags)
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str) if as_json else render(d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
