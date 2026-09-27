#!/usr/bin/env python3
"""Read logs/events.jsonl (OBSLOG_v1) and say what happened, what is wrong, and where to look.

Views over the one event stream (docs/LOGGING.md):
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

ROOT = Path(__file__).resolve().parent
# LOG_PATH_v1: the stream obslog writes and this reader parses come from one resolver (host_config),
# env override included. Tests still swap logdigest.LOG directly.
from host_config import EVENTS_LOG as LOG  # noqa: E402
SESSIONS = ROOT / "data" / "sessions"
HEARTBEAT_SEC = int(os.environ.get("CHATBOT_OBSLOG_SUMMARY_SEC", "300"))

# Thresholds for findings. Tune here, and keep docs/LOGGING.md "Findings" in step.
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
OBS_ROOT = Path(os.environ.get("CHATBOT_DATA") or os.environ.get("AGY_CHAT_DATA") or ROOT / "data") / "workspace" / "skill-observations"


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
                        rec = json.loads(line)
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

    # --- processes: starts, exits, unclean restarts, heartbeat gaps ---
    procs: Dict[str, Dict[str, Any]] = {}
    unclean = []
    last_by_src: Dict[str, dict] = {}
    # Per pid, not per stream: two processes of one src can overlap (a test server, a restart
    # racing the old one), so "the line before a start was not an exit" is not a crash. A pid is
    # unclean when its last line is not proc.exit and a newer pid of the same src started after it.
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
                find("warn", "rss_growth", "%s 메모리 증가 %.0fMB (한 프로세스 수명 안)" % (src, r2[-1] - r2[0]),
                     "누수 의심: heartbeat의 sessions/subscribers/threads 추이를 같이 보라", src=src, first=r2[0], last=r2[-1])
        if hbs:
            h = hbs[-1]
            info["last_heartbeat"] = {k: h.get(k) for k in ("ts", "uptime_s", "threads", "fds", "sessions", "busy",
                                                             "subscribers", "agent_procs", "log_write_errors") if k in h}
            if h.get("log_write_errors"):
                find("warn", "log_write_errors", "%s 로그 쓰기 실패 %s회" % (src, h["log_write_errors"]),
                     "logs/ 디스크 공간·권한 확인", src=src)
        if last and now - ts_of(last) > 2.5 * HEARTBEAT_SEC and last.get("evt") != "proc.exit" and win:
            find("error", "silent_process", "%s: %d분째 이벤트 없음 (heartbeat 중단)" % (src, (now - ts_of(last)) // 60),
                 "프로세스가 멈췄거나 죽었다: chatbot-ctl.sh status, logs/chatbot.log 끝부분 확인", src=src, last=last.get("ts"))
        for g in gaps:
            find("warn", "heartbeat_gap", "%s heartbeat %s분 공백" % (src, g["min"]),
                 "그 시간대 프로세스가 멈춤(락/GIL/스왑) 가능성: 공백 직전 이벤트를 --evt 로 확인", src=src, **g)
        procs[src] = info
    for u in unclean:
        find("error", "unclean_restart", "%s 비정상 종료 후 재시작 (pid %s, proc.exit 없음)" % (u["src"], u["prev_pid"]),
             "kill -9 / OOM / 크래시: 직전 마지막 이벤트와 dmesg·logs/chatbot.log 확인", **u)
    d["processes"] = procs
    d["unclean_restarts"] = unclean

    # --- errors grouped by fingerprint ---
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
            storm = " (폭주: %d줄은 건수만 기록)" % g["suppressed"] if g.get("suppressed") else ""
            find("error" if g["new"] else "warn", "error_fp", "%s%s ×%d%s: %s @%s" % ("[신규] " if g["new"] else "", g["type"], g["count"], storm, (g["msg"] or "")[:120], g["where"]),
                 "logdigest.py --fp %s 로 전체 trace·발생 요청 확인" % g["fp"], fp=g["fp"], routes=g["routes"])
    d["errors"] = errs
    for e in win:
        if e.get("evt") in ("proc.crash", "thread.crash"):
            find("error", e["evt"].replace(".", "_"), "%s: %s" % (e["evt"], (e.get("err") or {}).get("msg")),
                 "logdigest.py --fp %s" % (e.get("err") or {}).get("fp"), src=e.get("src"), ts=e.get("ts"), thread=e.get("thread"))

    # --- HTTP: summaries + individual lines ---
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
                 "logdigest.py --evt http.error 로 trace 확인", route=key)
        stream = key.endswith("/events")
        if not stream and row["p95_ms_worst"] and row["p95_ms_worst"] > P95_SLOW_MS and t["n"] >= 10:
            find("warn", "http_slow", "%s p95 %.0fms" % (key, row["p95_ms_worst"]), "느린 경로: 해당 핸들러의 외부 호출(CLI/파일/락) 확인", route=key)
    http.sort(key=lambda r: -r["n"])
    d["http"] = {"routes": http[:40], "total": sum(r["n"] for r in http)}
    ce = Counter()
    for e in win:
        if e.get("evt") == "http.client_error":
            ce["%s %s %s" % (e.get("src"), e.get("route"), e.get("status"))] += 1 + int(e.get("repeat") or 0)
    d["http"]["client_errors"] = dict(ce.most_common(15))
    for k, c in ce.items():
        if c >= CLIENT_ERR_REPEAT_WARN:
            find("warn", "client_error_repeat", "%s ×%d" % (k, c), "클라이언트가 같은 실패를 반복 요청: UI 폴링 대상/경로 확인", key=k)

    # --- turns / sessions ---
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
            find("error", "turn_failures", "%s 턴 실패율 %.0f%% (%d/%d)" % (p, 100 * bad / total, bad, total),
                 "logdigest.py --evt turn.end 로 outcome·stderr_tail 확인, 쿼터/로그인 문제면 accounts 확인", provider=p, outcomes=dict(c))
    d["turns"] = {"by_provider": turns, "failed": bad_turns[-20:]}
    d["sessions"] = {k: sum(1 for e in win if e.get("evt") == k) for k in
                     ("session.error", "session.session_rotate", "session.session_heavy", "turn.loop_notice", "turn.quiet_close",
                      "agent.spawn", "agent.exit", "agent.recycle")}
    died = [e for e in win if e.get("evt") == "agent.exit" and e.get("died_mid_turn")]
    if died:
        find("warn", "agent_died_mid_turn", "에이전트 프로세스가 턴 도중 종료 %d회" % len(died),
             "rc와 직전 agent.reaped(누가 죽였나) 확인", samples=[{k: x.get(k) for k in ("ts", "sid", "provider", "rc")} for x in died[-5:]])

    # --- ops: repair / doctor / reaping ---
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
        find("warn", "repair_frequent", "repair %d회 (%.1f/일) caller=%s" % (len(rep), len(rep) / days, dict(callers)),
             "재시작으로 덮는 근본 원인: repair 직전 http.error/turn.end/doctor.probe 를 시간순으로 보라", callers=dict(callers))
    if ops["repair_failed"]:
        find("error", "repair_failed", "repair 후에도 probe 실패 %d회" % ops["repair_failed"], "logs/chatbot.log 끝부분과 doctor.probe msg 확인")
    if ops["doctor_probe"].get("fail"):
        find("error", "probe_fail", "doctor probe 실패 %d회" % ops["doctor_probe"]["fail"], "logdigest.py --evt doctor.probe")
    d["ops"] = ops
    # A live chat server's own child reaped by ctl: ctl must leave those to the server (STANDBY_REAP_v1).
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
            find("warn", "agent_reaped_live", "살아 있는 채팅 서버(pid %s)의 자식 agy %s 가 정리됨 (%s)" % (e["ppid"], e.get("agent_pid"), e.get("reason")),
                 "ctl reap_orphan_agents 판단 확인: 서버 자손은 서버 소관이어야 한다", ppid=e["ppid"], agent_pid=e.get("agent_pid"),
                 key="%s/%s" % (e.get("ppid"), e.get("reason")))

    # --- MCP tool calls ---
    calls = Counter()
    fails: Dict[str, Counter] = defaultdict(Counter)
    for e in win:
        if e.get("evt") == "mcp.call":
            calls[e.get("tool")] += 1
            if not e.get("ok"):
                fails[str(e.get("tool"))][str(e.get("msg"))[:80]] += 1
    d["mcp"] = {"calls": dict(calls.most_common(20)),
                "failures": {t: dict(c.most_common(5)) for t, c in fails.items()}}

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 3))
    d["findings"] = findings
    d["status"] = "error" if any(f["severity"] == "error" for f in findings) else ("warn" if findings else "ok")
    return d


def render(d: Dict[str, Any]) -> str:
    w = d["window"]
    out = ["# 로그 다이제스트  %s → %s (%sh, 이벤트 %d)  상태: %s" % (w["since"], w["until"], w["hours"], w["events"], d["status"].upper())]
    out.append("\n## 발견 사항 (%d)" % len(d["findings"]))
    if not d["findings"]:
        out.append("- 이상 없음")
    for f in d["findings"]:
        out.append("- [%s] %s\n    → %s" % (f["severity"].upper(), f["title"], f["hint"]))
    out.append("\n## 프로세스")
    for src, p in d["processes"].items():
        hb = p.get("last_heartbeat") or {}
        out.append("- %s: 시작 %d회, heartbeat %d, 마지막 %s pid=%s git=%s rss=%s 상태=%s" % (
            src, p["starts"], p["heartbeats"], p["last_event"], p["last_pid"], p.get("git"), p.get("rss_mb"),
            {k: v for k, v in hb.items() if k != "ts"}))
    out.append("\n## 오류 지문 (상위)")
    for g in d["errors"][:10]:
        out.append("- %s %s ×%d %s @%s  %s~%s routes=%s%s" % (g["fp"], g["type"], g["count"], (g["msg"] or "")[:100], g["where"],
                                                           g["first"][5:19], (g["last"] or "")[5:19], g["routes"], " [신규]" if g["new"] else ""))
    if not d["errors"]:
        out.append("- 없음")
    out.append("\n## HTTP (총 %d)" % d["http"]["total"])
    for r in d["http"]["routes"][:15]:
        out.append("- %-45s n=%-6d %s p95≤%sms max=%sms" % (r["route"][:45], r["n"], r["codes"], r["p95_ms_worst"], r["max_ms"]))
    if d["http"]["client_errors"]:
        out.append("  4xx: %s" % d["http"]["client_errors"])
    out.append("\n## 턴")
    for p, t in d["turns"]["by_provider"].items():
        out.append("- %s: %d턴 %s 실패율 %.0f%% p50=%ss p95=%ss" % (p, t["total"], t["outcomes"], 100 * t["fail_rate"], t["p50_s"], t["p95_s"]))
    for b in d["turns"]["failed"][-5:]:
        out.append("  · %s %s %s %s %ss %s" % (str(b["ts"])[5:19], b["sid"], b["provider"], b["outcome"], b["dur_s"], b.get("error_hint") or ""))
    out.append("  세션 이벤트: %s" % {k: v for k, v in d["sessions"].items() if v})
    out.append("\n## 운영 (repair/doctor)")
    out.append("- %s" % d["ops"])
    out.append("\n## MCP 도구")
    out.append("- 호출: %s" % d["mcp"]["calls"])
    if d["mcp"]["failures"]:
        out.append("- 실패: %s" % d["mcp"]["failures"])
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
        HOST_SIGNAL_STAMP.write_text(str(int(now)))
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
