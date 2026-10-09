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
NOTIFY_WARN_AFTER_SEC = 24 * 3600   # D3: a warning reaches the operator once it has lasted a day; an error at once
NOTIFY_MAX = 3                # per tick, the worst first: the rest wait for the next tick (no wall of buttons)
NOTIFY_EVERY_SEC = 24 * 3600        # D3: the same incident at most once a day
RESOLVE_AFTER_SEC = 24 * 3600
TICK_SEC = 3600
FIRST_TICK_SEC = 300   # #865: the host restarts more often than hourly; an hour's wait first meant no check ran
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


def to_notify(state: Dict[str, Any], changes: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
    """D3, decided here: what the operator hears about -- a new error, an incident that got worse, a warning that has
    lasted a day -- each at most once a day, never one the operator ignored (unless it got worse), at most
    NOTIFY_MAX at a time: worse first, then errors, then the oldest. Marks the ones it returns."""
    worse = {c["incident"]["key"] for c in changes if c["change"] == "worse"}
    due = [(key, inc) for key, inc in state["incidents"].items()
           if inc["status"] == "open" and now - inc.get("notified_at", 0) >= NOTIFY_EVERY_SEC
           and (key in worse or inc["severity"] == "error" or now - inc["first_seen"] >= NOTIFY_WARN_AFTER_SEC)]
    due.sort(key=lambda ki: (ki[0] not in worse, ki[1]["severity"] != "error", ki[1]["first_seen"], ki[1]["id"]))
    out = []
    for _, inc in due[:NOTIFY_MAX]:
        inc["notified_at"] = now
        out.append(dict(inc))
    return out


def notify(incs: List[Dict[str, Any]]) -> None:
    """Each one as a host.incident event to the default character (the PD): event_react has it judge and speak first,
    within quiet hours and its hourly limit, and Web Push carries it to the operator's devices. Metadata only."""
    if not incs:
        return
    import characters
    import events
    from host_config import WORKSPACE
    default = characters.load_team(WORKSPACE).get("default")
    if not default:
        return
    for inc in incs:
        events.publish("host.incident", [default], channel="work", subject=str(inc["id"]), code=inc["code"],
                       severity=inc["severity"])


def note(incident_ids: List[int], path=None) -> str:
    """What the PD is told about these incidents: the engine's own words and references, for it to look up."""
    if path is None:
        import host_config
        path = host_config.INCIDENTS
    lines = []
    for iid in incident_ids:
        inc = get(path, iid)
        if not inc:
            continue
        ev = inc.get("evidence") or {}
        refs = ["incident:%d" % inc["id"]] + (["log:fp:%s" % ev["fp"]] if ev.get("fp") else [])
        lines.append("Incident #%d (%s, %s, seen since %s): %s. Hint: %s Evidence: %s." % (
            inc["id"], inc["code"], inc["severity"], time.strftime("%m-%d %H:%M", time.localtime(inc["first_seen"])),
            inc["title"], inc.get("hint") or "-", ", ".join(refs)))
    return " ".join(lines)


def decide(path, incident_id: int, action: str, operator: str = "operator (ui)") -> Dict[str, Any]:
    """The operator's word on an incident: `ticket` opens an approved engine ticket whose evidence is the incident;
    `ignore` keeps it quiet until it gets worse. Returns {"incident": ..., "ticket"?: ...}."""
    state = load(path)
    inc = next((i for i in state["incidents"].values() if i["id"] == int(incident_id)), None)
    if inc is None:
        raise KeyError("no incident %s" % incident_id)
    out: Dict[str, Any] = {}
    if action == "ignore":
        inc["status"] = "ignored"
    elif action == "ticket":
        if not inc.get("ticket"):
            import tickets
            data = Path(path).parent.parent        # <data>/dev/incidents.json
            t, _ = tickets.propose(data, "[incident #%d] %s" % (inc["id"], inc["title"])[:120],
                                   "incident %s" % inc["key"], ["incident:%d" % inc["id"]], actor="operator")
            t = tickets.approve(data, t["id"], operator=tickets.OPERATOR_UI)
            inc["ticket"] = t["id"]
            out["ticket"] = t
    else:
        raise ValueError("action is ticket or ignore")
    save(path, state)
    out["incident"] = dict(inc)
    return out


def api(method: str, path: str, body: Optional[dict]):
    """GET /api/incidents (open and ignored, newest first); POST /api/incidents/<id>/ticket|ignore. None: not ours."""
    if not (path == "/api/incidents" or path.startswith("/api/incidents/")):
        return None
    import host_config
    store = host_config.INCIDENTS
    if method == "GET" and path == "/api/incidents":
        incs = [i for i in load(store)["incidents"].values() if i["status"] in ("open", "ignored")]
        return 200, {"ok": True, "incidents": sorted(incs, key=lambda i: -i["id"])}
    parts = path.strip("/").split("/")
    if method == "POST" and len(parts) == 4 and parts[2].isdigit() and parts[3] in ("ticket", "ignore"):
        try:
            return 200, dict({"ok": True}, **decide(store, int(parts[2]), parts[3]))
        except KeyError as e:
            return 404, {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 -- a ticket refusal is the operator's to read
            return 400, {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}


def tick(path=None, now: Optional[float] = None, digest=None, improvements=None) -> List[Dict[str, Any]]:
    """One check: read the findings -- the log digest's and the rollups' improvement signals (il/D2) -- fold them in,
    log each change. Returns the changes (il/E notifies from them). A test passes `digest` and so reads no rollups."""
    from telemetry import obslog
    now = time.time() if now is None else now
    if path is None:
        import host_config
        path = host_config.INCIDENTS
    if digest is None:
        from telemetry import logdigest
        digest = logdigest.digest(WINDOW_SEC)
        if improvements is None:
            from health import improve
            improvements = improve.findings(now=now)
    state = load(path)
    changes = judge(state, (digest.get("findings") or []) + list(improvements or []), now)
    due = to_notify(state, changes, now)
    save(path, state)
    try:
        notify(due)
    except Exception:  # noqa: BLE001 -- the record stands even when the mailbox cannot be reached
        obslog.exception("incident.notify_failed", dedup="notify")
    for c in changes:
        inc = c["incident"]
        obslog.event("incident." + c["change"], lvl="warn" if c["change"] != "resolved" else "info", id=inc["id"],
                     code=inc["code"], key=inc["key"], severity=inc["severity"])
    return changes


def get(path, incident_id: int) -> Optional[Dict[str, Any]]:
    return next((i for i in load(path)["incidents"].values() if i["id"] == int(incident_id)), None)


def loop(sleep=time.sleep, rounds: Optional[int] = None) -> None:
    """The chat server's thread (dev build only): a check FIRST_TICK_SEC after start, then about every TICK_SEC.
    Never raises. What was told survives a restart (notified_at), so an early check repeats nothing."""
    from telemetry import obslog
    wait = FIRST_TICK_SEC
    while rounds is None or rounds > 0:
        sleep(wait)
        wait = TICK_SEC
        rounds = None if rounds is None else rounds - 1
        try:
            tick()
        except Exception:  # noqa: BLE001
            obslog.exception("incident.tick_failed", dedup="loop")
