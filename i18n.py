"""I18N_v1 server side (docs/plans/localization.md l10n/F): words the server sends a person, by key.

The page shows them in its own language; the server does not know it. So a user-facing event or field carries the
catalog key and its values, and the English text as well (for older pages, logs and anything that reads text):

    sess._emit(dict(event="stopped", **i18n.msg(KEY, user=user_title())))
    -> {"event": "stopped", "key": KEY, "vars": {"user": ...}, "text": <the English words>}

    i18n.field("message", KEY)
    -> {"message_key": KEY, "message_vars": {}, "message": <the English words>}

The catalogs are the page's (static/i18n/<lang>.json): one place for every word (test_l10n_catalogs checks the keys
named here). Words for an agent are English in code, never catalog keys; log lines are English.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

CATALOGS = Path(__file__).resolve().parent / "static" / "i18n"
_cache: Dict[str, Dict[str, str]] = {}


def catalog(lang: str = "en") -> Dict[str, str]:
    if lang not in _cache:
        try:
            _cache[lang] = json.loads((CATALOGS / ("%s.json" % lang)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache[lang] = {}
    return _cache[lang]


def _value(v: Any, lang: str) -> str:
    """A value as words: a nested {"key", "vars"} (another catalog line) is put in words too."""
    if isinstance(v, dict) and "key" in v:
        return text(v["key"], lang, **(v.get("vars") or {}))
    return str(v)


def _vars(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: ({"key": v["key"], "vars": _vars(v.get("vars") or {})} if isinstance(v, dict) and "key" in v else str(v))
            for k, v in values.items()}


def text(key: str, lang: str = "en", **values: Any) -> str:
    """The key's words in `lang` (English by default) with {name} filled; the key itself when missing. A value may
    be a nested line, {"key", "vars"} (e.g. a loop verdict inside its warning)."""
    s = catalog(lang).get(key) or catalog("en").get(key) or key
    return re.sub(r"\{(\w+)\}", lambda m: _value(values[m.group(1)], lang) if m.group(1) in values else m.group(0), s)


def line(key: str, **values: Any) -> Dict[str, Any]:
    """A nested line for another line's value: {"key", "vars"}."""
    return {"key": key, "vars": _vars(values)}


def msg(key: str, **values: Any) -> Dict[str, Any]:
    """An event's words: key, values and the English text."""
    return {"key": key, "vars": _vars(values), "text": text(key, **values)}


def field(name: str, key: str, **values: Any) -> Dict[str, Any]:
    """A message field of a JSON answer: <name>_key, <name>_vars and <name> (English)."""
    return {name + "_key": key, name + "_vars": _vars(values), name: text(key, **values)}
