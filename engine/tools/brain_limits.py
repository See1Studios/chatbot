"""Brains that cannot work right now, for the delegation runner.

`unavailable` tells a brain that could not work (quota, limit, missing CLI, timeout) from one that tried and failed.
BRAIN_LIMITS_v1 (docs/plans/director-handoff.md dir/J, D-9): such a brain is remembered until it can work again, so
the next run skips it at once instead of spending another try, or another 20-minute timeout, on it (#628: three
1200 s timeouts in a row; #631: a weekly limit, "Resets in 146h32m12s"). The state is one JSON file next to the
runner's other state; a file that cannot be read or written only turns the memory off, never the run.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

UNAVAILABLE_RE = re.compile(r"quota|rate.?limit|usage limit|session limit|limit reached|resets? (at|in)|\b429\b|"
                            r"exhausted|capacity|overloaded|too many requests|timed out|not installed|"
                            r"invalid model|not recognized as a known model|unknown model|"
                            r"internal server error|service unavailable|bad gateway|gateway timeout|"
                            r"connection refused|connection reset|temporary failure|\b50[0234]\b", re.I)
RESET_IN_RE = re.compile(r"resets? in\s+(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", re.I)
TIMEOUT_REST = 1800          # a brain that sat past its timeout: not again for half an hour
UNKNOWN_REST = 900           # a limit with no reset time in the message
MAX_REST = 8 * 24 * 3600     # a weekly limit at most; anything longer is a parse mistake


def brain_label(b: Dict) -> str:
    return "%s/%s" % (b["provider"], b["model"] or "default")


def unavailable(text: str, returncode) -> bool:
    """A brain that could not work (quota, limit, missing CLI, timeout), as opposed to one that tried and failed."""
    return returncode in (None, -1) or bool(UNAVAILABLE_RE.search(text or ""))


def rest_for(text: str) -> int:
    """Seconds until the brain can work again, read from its error."""
    m = RESET_IN_RE.search(text or "")
    if m and any(m.groups()):
        h, mi, s = (int(x or 0) for x in m.groups())
        return max(60, min(MAX_REST, h * 3600 + mi * 60 + s))
    if "timed out" in (text or "").lower():
        return TIMEOUT_REST
    return UNKNOWN_REST


def _load(path: Path) -> Dict[str, float]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def mark(path: Path, brain: Dict, text: str, now: float = 0.0) -> None:
    """Remember that `brain` cannot work until its reset."""
    now = now or time.time()
    state = {k: v for k, v in _load(path).items() if v > now}
    state[brain_label(brain)] = now + rest_for(text)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(state, sort_keys=True))
    except OSError:
        pass


def usable(path: Path, chain: List[Dict], now: float = 0.0) -> Tuple[List[Dict], List[str]]:
    """(the brains of `chain` that may work now, "label until HH:MM" for those still resting)."""
    now = now or time.time()
    state = _load(path)
    ok, resting = [], []
    for b in chain:
        until = state.get(brain_label(b), 0.0)
        if until > now:
            resting.append("%s until %s" % (brain_label(b), time.strftime("%m-%d %H:%M", time.localtime(until))))
        else:
            ok.append(b)
    return ok, resting


def resolve_provider_model(provider: str, model: str) -> str:
    """Resolve model name/family via provider adapter if available."""
    if not model:
        return model
    try:
        from providers.adapters import get_adapter
        ad = get_adapter(provider)
        if ad and hasattr(ad, "resolve_model"):
            return ad.resolve_model(model)
    except Exception:  # noqa: BLE001
        pass
    return model
