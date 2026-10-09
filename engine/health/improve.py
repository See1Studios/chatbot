"""Improvement signals (docs/plans/improvement-layers.md il/D2): not "something broke" but "something could be better",
read from the daily rollups (telemetry/rollup.py) and decided here -- each a defined ratio over finished days with a
minimum sample, so a quiet day proves nothing. They are findings like the log digest's and become incidents the same
way (health/incidents.py): the PD judges them, the operator decides.

  turn_loops         turns that hit the tool-call loop notice: the last RECENT days' rate rose to at least twice the
                     BASE days before them, and to at least LOOP_MIN_PCT
  react_heavy_skips  over BASE days, reactions skipped because the session was heavy at least as many as were spoken
  memory_unused      on the days memory was injected, at least MEMORY_MIN_INJECTED injections and no memory tool call

Rates whose meaning is not clean yet stay out: session.stopped counts the repair probe's own stops; react.defer
counts polls, not events.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

RECENT = 3
BASE = 7
LOOP_MIN_TURNS = 50
LOOP_MIN_PCT = 5.0
HEAVY_MIN_SKIPS = 20
MEMORY_MIN_INJECTED = 20


def _evt(day: Dict[str, Any], name: str) -> int:
    return int((day.get("by_evt") or {}).get(name) or 0)


def _rate(days: List[Dict[str, Any]], num: str, den: str):
    n, d = sum(_evt(x, num) for x in days), sum(_evt(x, den) for x in days)
    return (100.0 * n / d if d else None), n, d


def _span(days: List[Dict[str, Any]]) -> str:
    return "%s..%s" % (days[0]["day"], days[-1]["day"]) if days else ""


def turn_loops(days: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    recent, base = days[-RECENT:], days[-RECENT - BASE:-RECENT]
    r, n, d = _rate(recent, "turn.loop_notice", "turn.end")
    b, _, bd = _rate(base, "turn.loop_notice", "turn.end")
    if r is None or d < LOOP_MIN_TURNS or bd < LOOP_MIN_TURNS or r < LOOP_MIN_PCT or r < 2 * (b or 0):
        return None
    return {"code": "turn_loops", "severity": "warn",
            "title": "%.0f%% of turns hit the loop notice (%d of %d, %s), %.0f%% before (%s)" % (
                r, n, d, _span(recent), b, _span(base)),
            "hint": "more turns run long on tool calls: read turn.loop_notice events (--evt turn.loop_notice) and what "
                    "those turns did",
            "evidence": {"days": _span(recent), "pct": round(r, 1), "base_pct": round(b, 1), "turns": d}}


def react_heavy_skips(days: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    week = days[-BASE:]
    skipped = sum(int(((x.get("messages") or {}).get("react_skip") or {}).get("session_heavy") or 0) for x in week)
    spoke = sum(int((x.get("messages") or {}).get("react_turn") or 0) for x in week)
    if skipped < HEAVY_MIN_SKIPS or skipped < spoke:
        return None
    return {"code": "react_heavy_skips", "severity": "warn",
            "title": "a character could not speak first %d times because its session was heavy, and spoke %d times (%s)"
                     % (skipped, spoke, _span(week)),
            "hint": "heavy sessions block speaking first: read react.skip events (--evt react.skip) and the session "
                    "weight levels and rotation",
            "evidence": {"days": _span(week), "skipped": skipped, "spoke": spoke}}


def memory_unused(days: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    def injected(x):
        return sum(int((v or {}).get("n") or 0) for v in ((x.get("memory") or {}).get("injected_chars") or {}).values())
    used = [x for x in days[-BASE:] if injected(x)]
    n = sum(injected(x) for x in used)
    calls = sum(sum((x.get("memory") or {}).get("calls", {}).values()) for x in used)
    if n < MEMORY_MIN_INJECTED or calls:
        return None
    return {"code": "memory_unused", "severity": "warn",
            "title": "memory was injected %d times and the memory tool was called 0 times (%s)" % (n, _span(used)),
            "hint": "the injected memory may be enough, unread, or the tool unknown to the agents: read context.inject "
                    "events and the memory instructions",
            "evidence": {"days": _span(used), "injected": n, "calls": 0}}


SIGNALS = (turn_loops, react_heavy_skips, memory_unused)


def findings(days: Optional[List[Dict[str, Any]]] = None, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """The improvement findings over the finished days' rollups (oldest first). None: read the host's."""
    if days is None:
        import host_config
        from telemetry import rollup
        days = rollup.load(host_config.EVENTS_LOG, RECENT + BASE, time.time() if now is None else now)
    out = []
    for signal in SIGNALS:
        f = signal(days)
        if f:
            out.append(f)
    return out
