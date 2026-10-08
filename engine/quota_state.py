"""QUOTA_STATE_v1 (docs/plans/quota-failure-resilience.md qfr/A): which brain (provider, model) is out of quota and until
when. Read from the provider's own usage report -- `route_accounts._get_usage` rows, read for one model by the adapter's
`quota_view` (agy: per model group, a five-hour and a weekly window, each with its remaining % and reset time) -- never
from the wording of an error. A turn that failed reads the report once, fresh, in the background; a send to a brain
that is recorded out of quota is not made until its reset time (the route answers with a notice instead), so a spent
quota is not hit again and again. Kept in memory: after a restart the first failure records it again.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

_STATE: Dict[Tuple[str, str], dict] = {}
# A test run never reads a real account's usage on its own: the suite's failed turns are fakes (run-tests.sh sets it)
AUTO = os.environ.get("CHATBOT_TEST_RUNNER") != "1"
_LOCK = threading.Lock()


def _epoch(text) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(text).strip().replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _report(provider: str, model: str, force: bool) -> Optional[dict]:
    """The adapter's quota view of this brain, or None when there is no report."""
    import route_accounts
    from providers.adapters import get_adapter
    data = route_accounts._get_usage(provider=provider, force=force)
    if not data.get("ok"):
        return None
    return get_adapter(provider).quota_view(model, data.get("rows") or [])


def read(provider: str, model: str, force: bool = False, now: Optional[float] = None) -> Optional[dict]:
    """{provider, model, scope, window, until} when a window of this brain's quota is at 0 % with a reset still to
    come (the latest such reset: the brain is usable once every empty window is back), else None. Records it."""
    if not provider or not model:   # no model named: the view would be every group, not this brain
        return None
    now = time.time() if now is None else now
    try:
        view = _report(provider, model, force) or {}
    except Exception:  # noqa: BLE001 -- a usage read must never break a turn or a send
        return None
    empty = [(w, _epoch(w.get("reset_at"))) for w in view.get("windows") or [] if w.get("pct") == 0]
    empty = [(w, t) for w, t in empty if t and t > now]
    hit = None
    if empty:
        w, until = max(empty, key=lambda x: x[1])
        hit = {"provider": provider, "model": model, "scope": str(view.get("scope") or ""),
               "window": str(w.get("label") or ""), "until": until}
    with _LOCK:
        if hit:
            _STATE[(provider, model)] = hit
        else:
            _STATE.pop((provider, model), None)
    return hit


def after_error(provider: str, model: str) -> None:
    """A turn of this brain failed: read its report once, fresh, off the turn's thread."""
    if not AUTO:
        return
    threading.Thread(target=read, args=(provider, model, True), daemon=True, name="quota-after-error").start()


def blocked(provider: str, model: str, now: Optional[float] = None) -> Optional[dict]:
    """Before a send: the recorded out-of-quota state while its reset time has not come (no report is read here)."""
    now = time.time() if now is None else now
    with _LOCK:
        s = _STATE.get((provider, model))
        if s and s["until"] <= now:
            _STATE.pop((provider, model), None)
            s = None
    return dict(s) if s else None


def alternatives(provider: str, model: str, limit: int = 2, now: Optional[float] = None) -> list:
    """qfr/C: other brains of this provider to offer when this one is out of quota -- in the provider's own list
    order (`known_models`), leaving out any recorded out of quota or with an empty window in the usage report. The
    report is the cached one (route_accounts' TTL): this runs only when a send was held."""
    import route_accounts
    from providers.adapters import get_adapter
    now = time.time() if now is None else now
    try:
        adapter = get_adapter(provider)
        models = [m for m in adapter.known_models() if m and m != model]
        data = route_accounts._get_usage(provider=provider)
    except Exception:  # noqa: BLE001 -- an offer is a convenience: none rather than a broken send
        return []
    rows = (data.get("rows") or []) if data.get("ok") else []
    out = []
    for m in models:
        if blocked(provider, m, now):
            continue
        windows = adapter.quota_view(m, rows).get("windows") or [] if rows else []
        if any(w.get("pct") == 0 and (_epoch(w.get("reset_at")) or 0) > now for w in windows):
            continue
        out.append(m)
        if len(out) >= limit:
            break
    return out


LOW_PCT = 10   # qfr/D, plan D3: warn while 10 % or less is left, before it runs out
_WARNED: set = set()   # (provider, scope, window, reset_at): each low window is said once until it resets


def low(provider: str, model: str, now: Optional[float] = None) -> Optional[dict]:
    """qfr/D: this brain's lowest window with 0 < pct <= LOW_PCT and a reset still to come, from the cached report
    ({provider, model, scope, window, pct, until, reset_at}), else None."""
    if not provider or not model:
        return None
    now = time.time() if now is None else now
    try:
        view = _report(provider, model, False) or {}
    except Exception:  # noqa: BLE001
        return None
    found = [(w, _epoch(w.get("reset_at"))) for w in view.get("windows") or []
             if isinstance(w.get("pct"), (int, float)) and 0 < w["pct"] <= LOW_PCT]
    found = [(w, t) for w, t in found if t and t > now]
    if not found:
        return None
    w, until = min(found, key=lambda x: x[0]["pct"])
    return {"provider": provider, "model": model, "scope": str(view.get("scope") or ""), "window": str(w.get("label") or ""),
            "pct": w["pct"], "until": until, "reset_at": str(w.get("reset_at") or "")}


def warn_low(session) -> None:
    """After a turn that ended with an answer: say once in the talk when this brain is running low (off the turn's
    thread; the report is the cached one, read again at most every route_accounts TTL)."""
    if not AUTO:
        return
    threading.Thread(target=_warn_low, args=(session,), daemon=True, name="quota-low").start()


def _warn_low(session) -> None:
    import i18n
    hit = low(str(getattr(session, "provider", "") or ""), str(getattr(session, "model", "") or ""))
    if not hit:
        return
    key = (hit["provider"], hit["scope"], hit["window"], hit["reset_at"])
    with _LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    session._emit({"event": "notice", "notice": "warn", "quota": hit,
                   **i18n.msg("srv.quota_low", model=hit["model"], window=hit["window"], pct=int(hit["pct"]),
                              until=until_text(hit["until"]))})


def until_text(until: float, now: Optional[float] = None) -> str:
    """The reset time as the host's clock shows it: HH:MM today, else MM/DD HH:MM."""
    now = time.time() if now is None else now
    t, n = time.localtime(until), time.localtime(now)
    return time.strftime("%H:%M" if t[:3] == n[:3] else "%m/%d %H:%M", t)
