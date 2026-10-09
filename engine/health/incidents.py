"""Incidents (docs/plans/improvement-layers.md il/D): the log digest's findings, grouped into incidents the engine
keeps track of -- a sign that something on this host is wrong, with what showed it.

  <data>/dev/incidents.json   (host_config.INCIDENTS: dev data, next to the engine tickets)

Every check (`tick`, about hourly from the chat server, dev build only) reads the findings of the last WINDOW and:
  open      a finding whose key has no open incident                -> incident.open     (notify)
  worse     an open incident whose finding rose from warn to error   -> incident.worse    (notify)
  resolved  an open incident no finding showed for RESOLVE_AFTER     -> incident.resolved
  ignored   the operator said so (il/E); it opens again only when it gets worse
A finding's key is its code plus the first of fp / route / provider / src it carries -- never a pid or a time, so a
restart does not make a new incident of an old one. All of it is decided here, from the findings' fields; no model
reads anything. `incident:<id>` is ticket evidence (tickets.verify_evidence, improvement-layers D2).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

WINDOW_SEC = 24 * 3600
RESOLVE_AFTER_SEC = 24 * 3600
TICK_SEC = 3600
KEY_FIELDS = ("fp", "route", "provider", "src")
RANK = {"info": 0, "warn": 1, "error": 2}


def key_of(finding: Dict[str, Any]) -> str:
    ev = finding.get("evidence") or {}
    return "|".join([str(finding.get("code") or "")] + [str(ev[k]) for k in KEY_FIELDS if ev.get(k)][:1])


def load(path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"next_id": 1, "incidents": {}}


def save(path, state: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(str(tmp), "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(str(tmp), str(p))


def judge(state: Dict[str, Any], findings: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
    """Fold `findings` into `state`; return what changed: [{"change": open|worse|resolved, "incident": {...}}]."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for f in findings:
        key = key_of(f)
        if key in seen:
            continue
        seen.add(key)
        sev = str(f.get("severity") or "warn")
        inc = state["incidents"].get(key)
        if inc is None or inc["status"] == "resolved":
            inc = {"id": state["next_id"], "key": key, "code": f.get("code"), "severity": sev,
                   "title": str(f.get("title") or "")[:200], "hint": str(f.get("hint") or "")[:300],
                   "evidence": f.get("evidence") or {}, "first_seen": now, "last_seen": now, "checks": 1,
                   "status": "open"}
            state["next_id"] += 1
            state["incidents"][key] = inc
            out.append({"change": "open", "incident": dict(inc)})
            continue
        inc.update(last_seen=now, checks=inc.get("checks", 0) + 1, title=str(f.get("title") or "")[:200],
                   evidence=f.get("evidence") or {})
        if RANK.get(sev, 1) > RANK.get(inc["severity"], 1):
            inc["severity"] = sev
            if inc["status"] == "ignored":
                inc["status"] = "open"   # it got worse: the operator hears it again
            out.append({"change": "worse", "incident": dict(inc)})
    for key, inc in state["incidents"].items():
        if inc["status"] in ("open", "ignored") and key not in seen and now - inc["last_seen"] >= RESOLVE_AFTER_SEC:
            inc.update(status="resolved", resolved_at=now)
            out.append({"change": "resolved", "incident": dict(inc)})
    return out


def tick(path=None, now: Optional[float] = None, digest=None) -> List[Dict[str, Any]]:
    """One check: read the findings, fold them in, log each change. Returns the changes (il/E notifies from them)."""
    from telemetry import obslog
    now = time.time() if now is None else now
    if path is None:
        import host_config
        path = host_config.INCIDENTS
    if digest is None:
        from telemetry import logdigest
        digest = logdigest.digest(WINDOW_SEC)
    state = load(path)
    changes = judge(state, digest.get("findings") or [], now)
    save(path, state)
    for c in changes:
        inc = c["incident"]
        obslog.event("incident." + c["change"], lvl="warn" if c["change"] != "resolved" else "info", id=inc["id"],
                     code=inc["code"], key=inc["key"], severity=inc["severity"])
    return changes


def get(path, incident_id: int) -> Optional[Dict[str, Any]]:
    return next((i for i in load(path)["incidents"].values() if i["id"] == int(incident_id)), None)


def loop() -> None:
    """The chat server's thread (dev build only): a check about every TICK_SEC. Never raises."""
    from telemetry import obslog
    while True:
        time.sleep(TICK_SEC)
        try:
            tick()
        except Exception:  # noqa: BLE001
            obslog.exception("incident.tick_failed", dedup="loop")
