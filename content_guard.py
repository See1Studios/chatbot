"""CONTENT_GUARD_v1: safety-policy guards around a turn, driven by data/content_guards.json.

check_preflight: a user message the provider would refuse anyway is stopped before any external call (0 tokens).
intercept_refusal: a provider refusal becomes a `notice: "warn"` system notice instead of an assistant bubble.
The table has a "default" section; "providers" may override pre_filter/post_refusal per provider id
(configuration only -- no provider is named in code, PROVIDER_NEUTRAL_v1).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TABLE_PATH = Path(__file__).resolve().parent / "data" / "content_guards.json"

_lock = threading.Lock()
_cache: Dict[str, Any] = {"mtime": None, "table": {}}


def load_table(path: Optional[Path] = None) -> Dict[str, Any]:
    """The guard table, re-read only when the file changes. Missing or broken file = no guards."""
    p = Path(path) if path else TABLE_PATH
    try:
        mtime = (str(p), p.stat().st_mtime)
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                table = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                table = {}
            _cache["mtime"], _cache["table"] = mtime, table if isinstance(table, dict) else {}
        return _cache["table"]


def _section(provider: str, name: str, table: Dict[str, Any]) -> Dict[str, Any]:
    over = ((table.get("providers") or {}).get(provider or "") or {}).get(name)
    sec = over if isinstance(over, dict) else (table.get("default") or {}).get(name)
    return sec if isinstance(sec, dict) else {}


def _notice_text(sec: Dict[str, Any], table: Dict[str, Any]) -> str:
    texts = (table.get("texts") or {}).get(table.get("locale") or "ko") or {}
    return str(texts.get(sec.get("notice_key") or "") or sec.get("default_text") or "")


def _matches(sec: Dict[str, Any], text: str) -> bool:
    low = text.lower()
    if any(k and str(k).lower() in low for k in sec.get("keywords") or []):
        return True
    for pat in sec.get("patterns") or []:
        try:
            if re.search(pat, text, re.I | re.M):
                return True
        except re.error:
            continue
    return False


def check_preflight(provider: str, text: str, table: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """(blocked, notice_text) for a user message about to go to `provider`."""
    table = load_table() if table is None else table
    sec = _section(provider, "pre_filter", table)
    if not sec or not (text or "").strip() or not _matches(sec, text):
        return False, ""
    return True, _notice_text(sec, table)


def intercept_refusal(provider: str, text: str, finish_reason: Optional[str] = None,
                      table: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """(refused, notice_text) for a finished answer. A refusal finish_reason always counts; text patterns
    only on short answers (max_chars) so a long real answer quoting a refusal line is left alone."""
    table = load_table() if table is None else table
    sec = _section(provider, "post_refusal", table)
    if not sec:
        return False, ""
    reasons: List[str] = [str(r).lower() for r in sec.get("finish_reasons") or []]
    body = (text or "").strip()
    hit = bool(finish_reason) and str(finish_reason).lower() in reasons
    if not hit and body and len(body) <= int(sec.get("max_chars") or 400):
        hit = _matches(sec, body)
    return (True, _notice_text(sec, table)) if hit else (False, "")


def notice_item(text: str, ts: Optional[float] = None) -> Tuple[dict, dict]:
    """(history item, SSE event) for a warn system notice -- one shape for server and finalize_turn."""
    ts = time.time() if ts is None else ts
    return ({"role": "assistant", "text": text, "notice": "warn", "ts": ts},
            {"event": "error", "raw_event": "error", "text": text, "notice": "warn", "ts": ts})
