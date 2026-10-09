#!/usr/bin/env python3
"""Daily rollups (docs/plans/telemetry.md tl/C): one small summary per day, kept forever, so weeks and months can be
compared after the raw events are gone (KEEP_DAYS). Built from the event log by the engine -- counts, sums and
percentiles, never a model's reading of it.

  logs/metrics/YYYY-MM-DD.json   one day (the day of each event's own local timestamp)

Dimensions (telemetry D2): provider, model, character, mode (work/private) and HTTP route; a session's id only in the
raw log. A turn's character and mode come from its session's context.inject line (turn.end does not carry them).
Metadata only, like the log.

  python3 engine/telemetry/rollup.py build          # write every missing finished day (not today)
  python3 engine/telemetry/rollup.py show [--days 7] [--json]

The long-running processes' background thread builds missing days about once an hour (obslog.rollup_tick).
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

if __package__ in (None, ""):   # run as a script: the engine folder is the import root
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import platform_compat

VERSION = 4   # 2: tokens, tool calls and read KB per turn group (tl/D); 3: memory (tl/E); 4: turn phases (tl/D)
PHASES = ("prep_ms", "spawn_ms", "first_tool_ms")
MEMORY_LAYERS = ("house_memory", "own_memory", "private_memory")   # instructions.LAYERS that carry remembered things
TOP_FP = 20
TOKENS = ("tok_in", "tok_out", "tok_think", "tok_cache_read", "tok_total")
USAGE_TO_TOKENS = (("input_tokens", "tok_in"), ("output_tokens", "tok_out"), ("thinking_tokens", "tok_think"),
                   ("cache_read_tokens", "tok_cache_read"), ("total_tokens", "tok_total"))


def dir_for(log_path) -> Path:
    return Path(log_path).parent / "metrics"


def _pct(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))], 1)


def _dist(values: List[float]) -> Dict[str, Any]:
    return {"n": len(values), "p50": _pct(values, 0.5), "p95": _pct(values, 0.95),
            "max": round(max(values), 1) if values else None}


class Day:
    """Accumulates one day's events."""

    def __init__(self) -> None:
        self.events = 0
        self.by_evt: Dict[str, int] = defaultdict(int)
        self.turns: Dict[str, Dict[str, Any]] = {}
        self.http: Dict[str, Dict[str, Any]] = {}
        self.errors: Dict[str, Any] = {"error": 0, "warn": 0, "by_fp": defaultdict(int)}
        self.proc: Dict[str, Any] = {"starts": defaultdict(int), "repairs": defaultdict(int),
                                     "repairs_failed": 0, "rss_mb_max": {}}
        self.mcp: Dict[str, Dict[str, Any]] = {}
        self.context: Dict[str, List[float]] = defaultdict(list)
        self.messages: Dict[str, Any] = {"published": defaultdict(int), "delivered": 0, "react_turn": 0,
                                         "react_defer": defaultdict(int), "react_skip": defaultdict(int),
                                         "room_turns": 0}
        self.sessions: Dict[str, Any] = {"spawn": 0, "rotate": defaultdict(int)}
        self.main: Dict[str, int] = {"checks": 0, "red": 0}
        self.turn_tokens_seen = False   # a day whose turn.end lines carry tokens is never backfilled
        self.memory: Dict[str, Any] = {"calls": defaultdict(int), "search_hits": [], "added": 0,
                                       "injected_chars": defaultdict(list)}

    def _group(self, key: str) -> Dict[str, Any]:
        return self.turns.setdefault(key, {"outcomes": defaultdict(int), "dur_s": [], "ttft_ms": [], "tool_calls": [],
                                           "read_kb": [], "tok": defaultdict(int), "tok_in": [], "tok_source": "",
                                           **{p: [] for p in PHASES}})

    def add_usage(self, key: str, usage: Dict[str, Any]) -> None:
        """A turn's tokens from a session's history (backfill for days before turn.end carried them)."""
        t = self._group(key)
        t["tok_source"] = "sessions"
        for src, dst in USAGE_TO_TOKENS:
            if isinstance(usage.get(src), (int, float)):
                t["tok"][dst] += int(usage[src])
        if isinstance(usage.get("input_tokens"), (int, float)):
            t["tok_in"].append(float(usage["input_tokens"]))

    def add(self, e: Dict[str, Any], who: Dict[str, Dict[str, str]]) -> None:
        evt = str(e.get("evt") or "")
        self.events += 1
        self.by_evt[evt] += 1
        lvl = e.get("lvl")
        if lvl in ("error", "warn"):
            self.errors[lvl] += 1
            fp = (e.get("err") or {}).get("fp") if isinstance(e.get("err"), dict) else None
            if fp:
                self.errors["by_fp"][fp] += 1
        if evt == "context.inject" and e.get("sid"):
            who[e["sid"]] = {"character": str(e.get("character") or ""), "mode": str(e.get("mode") or "")}
            self.context["%s|%s" % (e.get("provider") or "", e.get("mode") or "")].append(float(e.get("chars") or 0))
            for layer in e.get("layers") or []:
                if isinstance(layer, dict) and layer.get("id") in MEMORY_LAYERS:
                    self.memory["injected_chars"][layer["id"]].append(float(layer.get("chars") or 0))
        elif evt == "turn.end":
            w = who.get(str(e.get("sid") or ""), {})
            key = "|".join([str(e.get("provider") or ""), str(e.get("model") or ""), w.get("mode", ""),
                            w.get("character", "")])
            t = self._group(key)
            t["outcomes"][str(e.get("outcome") or "")] += 1
            for f in ("dur_s", "ttft_ms", "tool_calls", "read_kb") + PHASES:
                if isinstance(e.get(f), (int, float)):
                    t[f].append(float(e[f]))
            if any(isinstance(e.get(f), (int, float)) for f in TOKENS):
                self.turn_tokens_seen = True
                t["tok_source"] = "turns"
                for f in TOKENS:
                    if isinstance(e.get(f), (int, float)):
                        t["tok"][f] += int(e[f])
                if isinstance(e.get("tok_in"), (int, float)):
                    t["tok_in"].append(float(e["tok_in"]))
        elif evt == "http.summary":
            for route, s in (e.get("routes") or {}).items():
                if not isinstance(s, dict):
                    continue
                h = self.http.setdefault("%s %s" % (e.get("src"), route),
                                         {"n": 0, "codes": defaultdict(int), "p95_worst": 0.0, "max_ms": 0.0})
                h["n"] += int(s.get("n") or 0)
                for code, n in (s.get("codes") or {}).items():
                    h["codes"][code] += int(n)
                h["p95_worst"] = max(h["p95_worst"], float(s.get("p95") or 0))
                h["max_ms"] = max(h["max_ms"], float(s.get("max") or 0))
        elif evt == "proc.start":
            self.proc["starts"][str(e.get("src"))] += 1
        elif evt == "proc.heartbeat" and isinstance(e.get("rss_mb"), (int, float)):
            src = str(e.get("src"))
            self.proc["rss_mb_max"][src] = max(self.proc["rss_mb_max"].get(src, 0.0), float(e["rss_mb"]))
        elif evt == "repair.begin":
            self.proc["repairs"][str(e.get("caller"))] += 1
        elif evt == "repair.end" and not e.get("ok"):
            self.proc["repairs_failed"] += 1
        elif evt == "mcp.call":
            if e.get("tool") == "memory":
                args, res = e.get("args") or {}, e.get("result") or {}
                self.memory["calls"][str(args.get("action") or "")] += 1
                if isinstance(res.get("hits"), int):
                    self.memory["search_hits"].append(float(res["hits"]))
                self.memory["added"] += 1 if res.get("status") == "added" else 0
            m = self.mcp.setdefault(str(e.get("tool") or ""), {"fail": 0, "dur_ms": []})
            if not e.get("ok"):
                m["fail"] += 1
            if isinstance(e.get("dur_ms"), (int, float)):
                m["dur_ms"].append(float(e["dur_ms"]))
        elif evt == "events.publish":
            self.messages["published"][str(e.get("type") or "")] += 1
        elif evt == "events.deliver":
            self.messages["delivered"] += int(e.get("n") or 0)
        elif evt == "react.turn":
            self.messages["react_turn"] += 1
        elif evt in ("react.defer", "react.skip"):
            self.messages[evt.replace(".", "_")][str(e.get("reason") or "")] += 1 + int(e.get("repeat") or 0)
        elif evt == "room.turn":
            self.messages["room_turns"] += 1
        elif evt == "agent.spawn":
            self.sessions["spawn"] += 1
        elif evt == "session.session_rotate":
            self.sessions["rotate"][str(e.get("reason") or "")] += 1
        elif evt == "main.check" and e.get("ok") is not None:
            self.main["checks"] += 1
            self.main["red"] += 0 if e.get("ok") else 1

    def summary(self, day: str) -> Dict[str, Any]:
        def plain(d):
            return {k: plain(v) for k, v in d.items()} if isinstance(d, dict) else d
        turns = {}
        for key, t in sorted(self.turns.items()):
            provider, model, mode, character = key.split("|", 3)
            turns[key] = {"provider": provider, "model": model, "mode": mode, "character": character,
                          "outcomes": dict(t["outcomes"]), "dur_s": _dist(t["dur_s"]), "ttft_ms": _dist(t["ttft_ms"]),
                          "tool_calls": _dist(t["tool_calls"]), "read_kb": _dist(t["read_kb"]),
                          "tokens": dict(t["tok"]), "tok_in": _dist(t["tok_in"]), "tokens_from": t["tok_source"],
                          **{p: _dist(t[p]) for p in PHASES}}
        fps = sorted(self.errors["by_fp"].items(), key=lambda kv: -kv[1])[:TOP_FP]
        return {"version": VERSION, "day": day, "generated": int(time.time()), "events": self.events,
                "by_evt": dict(sorted(self.by_evt.items(), key=lambda kv: -kv[1])),
                "turns": turns,
                "http": {k: dict(v, codes=dict(v["codes"])) for k, v in sorted(self.http.items())},
                "errors": {"error": self.errors["error"], "warn": self.errors["warn"], "top_fp": dict(fps)},
                "proc": plain(self.proc),
                "mcp": {k: {"n": len(v["dur_ms"]), "fail": v["fail"], "dur_ms": _dist(v["dur_ms"])}
                        for k, v in sorted(self.mcp.items())},
                "context": {k: _dist(v) for k, v in sorted(self.context.items())},
                "messages": plain(self.messages), "sessions": plain(self.sessions), "main": dict(self.main),
                "memory": {"calls": dict(self.memory["calls"]), "added": self.memory["added"],
                           "search_hits": _dist(self.memory["search_hits"]),
                           "injected_chars": {k: _dist(v) for k, v in sorted(self.memory["injected_chars"].items())}}}


def session_usage(sessions_dir) -> Iterable[tuple]:
    """(day, turn group key, usage) for every answer with usage in the sessions' histories: tokens for the days before
    turn.end carried them (tl/D backfill). Reads meta.json numbers and ids only, never a message's text."""
    for p in sorted(Path(sessions_dir).glob("*/meta.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        key = "|".join([str(m.get("provider") or ""), str(m.get("model") or ""), str(m.get("mode") or "work"),
                        str(m.get("character") or "")])
        for h in m.get("history") or []:
            if h.get("role") == "assistant" and isinstance(h.get("usage"), dict) and isinstance(h.get("ts"), (int, float)):
                yield time.strftime("%Y-%m-%d", time.localtime(h["ts"])), key, h["usage"]


def build(log_path, events: Iterable[Dict[str, Any]], days: Optional[Iterable[str]] = None,
          today: Optional[str] = None, usage: Optional[Iterable[tuple]] = None) -> List[str]:
    """Write a rollup for each finished day in `events` (only `days`, when given). `usage`: session_usage() rows,
    applied only to days whose turn.end lines carry no tokens. Returns the days written."""
    today = today or time.strftime("%Y-%m-%d")
    want = set(days) if days is not None else None
    acc: Dict[str, Day] = {}
    who: Dict[str, Dict[str, str]] = {}
    for e in events:
        day = str(e.get("ts") or "")[:10]
        if len(day) != 10 or day >= today or (want is not None and day not in want):
            if e.get("evt") == "context.inject" and e.get("sid"):   # a session's character can span midnight
                who[e["sid"]] = {"character": str(e.get("character") or ""), "mode": str(e.get("mode") or "")}
            continue
        acc.setdefault(day, Day()).add(e, who)
    for day, key, u in usage or ():
        if day in acc and not acc[day].turn_tokens_seen:
            acc[day].add_usage(key, u)
    d = dir_for(log_path)
    d.mkdir(parents=True, exist_ok=True)
    for day, a in sorted(acc.items()):
        tmp = d / (".%s.json.tmp" % day)
        platform_compat.write_text(tmp, json.dumps(a.summary(day), ensure_ascii=False, sort_keys=True) + "\n",
                                   encoding="utf-8")
        os.replace(str(tmp), str(d / ("%s.json" % day)))
    return sorted(acc)


def _version(path: Path) -> int:
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("version") or 0)
    except (OSError, ValueError, AttributeError):
        return 0


def missing(log_path, first_day: str, today: Optional[str] = None) -> List[str]:
    """Finished days from `first_day` to yesterday with no rollup, or one an older VERSION wrote (rebuilt while the
    raw events still exist)."""
    today = today or time.strftime("%Y-%m-%d")
    t = time.mktime(time.strptime(first_day, "%Y-%m-%d")) + 43200   # noon: no DST edge
    out = []
    while True:
        day = time.strftime("%Y-%m-%d", time.localtime(t))
        if day >= today:
            return out
        if _version(dir_for(log_path) / ("%s.json" % day)) < VERSION:   # absent, or written by an older rollup
            out.append(day)
        t += 86400


def build_missing(log_path, now: Optional[float] = None) -> List[str]:
    """Fill every missing finished day the log (archive included) still holds. One process at a time."""
    from telemetry import logdigest
    now = time.time() if now is None else now
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    d = dir_for(log_path)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "a", encoding="utf-8", newline="\n") as lock:
        if not platform_compat.lock_file(lock, blocking=False):
            return []
        saved = logdigest.LOG
        logdigest.LOG = Path(log_path)
        try:
            files = logdigest.log_files()
            if not files:
                return []
            oldest = min(p.stat().st_mtime for p in files)
            first = None
            for e in logdigest.read_events(0.0):
                first = str(e.get("ts") or "")[:10]
                break
            first = first or time.strftime("%Y-%m-%d", time.localtime(oldest))
            want = missing(log_path, first, today)
            if not want:
                return []
            since = time.mktime(time.strptime(want[0], "%Y-%m-%d")) - 86400   # a day early: session characters
            import host_config
            return build(log_path, logdigest.read_events(since), want, today, session_usage(host_config.SESSIONS))
        finally:
            logdigest.LOG = saved
            platform_compat.unlock_file(lock)


def load(log_path, days: int = 7, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """The last `days` finished days that have a rollup, oldest first."""
    now = time.time() if now is None else now
    out = []
    for i in range(days, 0, -1):
        day = time.strftime("%Y-%m-%d", time.localtime(now - i * 86400))
        p = dir_for(log_path) / ("%s.json" % day)
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _line(r: Dict[str, Any]) -> str:
    turns = list(r.get("turns", {}).values())
    tok = sum(int((t.get("tokens") or {}).get("tok_total", 0)) for t in turns)
    n = sum(sum(t["outcomes"].values()) for t in turns)
    bad = sum(sum(v for k, v in t["outcomes"].items() if k not in ("result", "stopped", "interrupted")) for t in turns)
    dur = [t["dur_s"]["p95"] for t in turns if t["dur_s"]["p95"] is not None]
    ttft = [t["ttft_ms"]["p95"] for t in turns if t["ttft_ms"]["p95"] is not None]
    slow = max(((k, v) for k, v in r.get("http", {}).items() if not k.endswith("/events")),   # a stream stays open
               key=lambda kv: kv[1]["p95_worst"], default=(None, None))
    m = r.get("messages", {})
    return ("%s  turns %4d fail %3d  dur_p95 %6s  ttft_p95 %6s  tokens %6.1fM  errors %3d  chat_starts %2d  react %d/defer %d  "
            "slowest %s" % (r["day"], n, bad, max(dur) if dur else "-", max(ttft) if ttft else "-", tok / 1e6,
                            r["errors"]["error"], r["proc"]["starts"].get("chat", 0),
                            m.get("react_turn", 0), sum((m.get("react_defer") or {}).values()),
                            "%s %.0fms" % (slow[0], slow[1]["p95_worst"]) if slow[0] else "-"))


def main(argv: Optional[List[str]] = None) -> int:
    import host_config
    args = list(sys.argv[1:] if argv is None else argv)
    log = host_config.EVENTS_LOG
    if args[:1] == ["build"]:
        print("\n".join(build_missing(log)) or "nothing missing")
        return 0
    if args[:1] == ["show"]:
        days = int(args[args.index("--days") + 1]) if "--days" in args else 7
        rows = load(log, days)
        print(json.dumps(rows, ensure_ascii=False, indent=1) if "--json" in args else
              ("\n".join(_line(r) for r in rows) or "no rollups yet (rollup.py build)"))
        return 0
    print("usage: rollup.py build | show [--days N] [--json]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
