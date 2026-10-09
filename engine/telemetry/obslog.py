#!/usr/bin/env python3
"""Structured observability log (OBSLOG_v1): one JSONL stream for every process.

logs/events.jsonl is the single source for "what happened on this host": the chat
server, the MCP server, chatbot-ctl.sh (doctor/repair) and session turns all append
one JSON object per line. People read it through logdigest.py (summary / timeline /
follow); agents read the same lines or `logdigest.py --json`. OPERATIONS.md is the
schema and event dictionary -- add a new `evt` name there when you add one here.

Line shape (fixed keys first, then event fields):
  {"ts": "2026-09-23T10:44:31.123+09:00", "lvl": "info|warn|error", "src": "chat|mcp|ctl|...",
   "evt": "dotted.name", "pid": 123, "rid": "...", "sid": "...", ...}

Rules this module keeps so callers do not have to:
  - never raises into the caller; a failed write is counted, not thrown
  - redacts secret-looking keys and values (tokens, bearer, api keys, cookies)
  - caps every string so one line stays small
  - rotates by size under an flock, and opens-appends-closes per line, so several
    processes can share the file and nobody keeps writing into a rotated inode
  - successful high-frequency HTTP traffic is folded into a periodic http.summary;
    errors, slow requests and mutations are written one by one
  - repeated identical warnings collapse (`dedup=`) into one line plus a repeat count
  - an error storm (one fingerprint over and over) keeps its trace once per TRACE_EVERY_SEC and
    at most FP_MAX_PER_WINDOW lines per FP_WINDOW_SEC; the rest is counted and settled in
    log.suppressed, so a flood cannot rotate the earlier history out of the file

Where lines go: CHATBOT_OBSLOG_PATH, which chatbot-ctl.sh exports for everything it starts. Without it
(tests, a server started by hand, imports from tools) events stay in the in-memory RECENT ring and
warn/error still reach stderr -- so test servers never write into the production log.

Command line (for shell callers such as chatbot-ctl.sh):
  obslog.py emit --src ctl --evt repair.begin [--lvl warn] [--msg TEXT] [key=value ...]
"""
from __future__ import annotations

import atexit
import collections
import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

if __package__ in (None, ""):   # run as a script (chatbot-ctl.sh): the engine folder is the import root
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import platform_compat
import repo_layout

ROOT = Path(__file__).resolve().parent
# LOG_PATH_v1: the default lives in host_config, the one resolver ctl and logdigest also read, so the
# three cannot drift. It is a fallback name only -- where lines are actually written is decided by
# configure() (CHATBOT_OBSLOG_PATH), never from here.
from host_config import EVENTS_LOG as DEFAULT_PATH  # noqa: E402
MAX_BYTES = int(os.environ.get("CHATBOT_OBSLOG_MAX_BYTES", str(10 * 1024 * 1024)))
BACKUPS = 5
LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}
STR_CAP = 1000
MSG_CAP = 2000
TRACE_CAP = 6000
SUMMARY_EVERY_SEC = int(os.environ.get("CHATBOT_OBSLOG_SUMMARY_SEC", "300"))
SLOW_MS = 3000
# 404s that clients ask for on every connect by design; they stay in http.summary counts.
EXPECTED_404_PREFIXES = ("/.well-known/",)
DEDUP_WINDOW_SEC = 300
TRACE_EVERY_SEC = 300      # same err.fp: full trace at most once per this
FP_WINDOW_SEC = 60         # same err.fp: at most FP_MAX_PER_WINDOW lines per this window
FP_MAX_PER_WINDOW = 20

_state: Dict[str, Any] = {
    "src": None,
    "path": None,
    "mirror": "warn",   # min level copied to stderr as one human line (lands in chatbot.log)
    "started": time.time(),
    "write_errors": 0,
    "lines": 0,
}
_lock = threading.Lock()
_local = threading.local()
RECENT: "collections.deque[dict]" = collections.deque(maxlen=500)

# -- redaction --------------------------------------------------------------------------
_SECRET_KEY_RE = re.compile(r"(token|secret|passw|authorization|api[_-]?key|cookie|bearer|refresh|credential|private[_-]?key)", re.I)
_SECRET_VAL_RES = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [redacted]"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}"), "[redacted-key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[redacted-key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "[redacted-key]"),
    (re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"), "[redacted-key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), "[redacted-jwt]"),
    (re.compile(r"(?i)\b(token|secret|password|passwd|api[_-]?key|access[_-]?key|code)(\s*[=:]\s*)(\"?)[^\s\"&,;]{6,}"), r"\1\2\3[redacted]"),
]


def redact(text: str) -> str:
    for rx, rep in _SECRET_VAL_RES:
        text = rx.sub(rep, text)
    return text


# tl/E (2026-10-09): mcp.call used to log every argument up to 300 characters -- memory lines, search words, dialog
# lines between characters, delegated instructions. A tool's words are content, like a turn's: only ids and kinds stay.
ARG_KEEP = frozenset(("action", "id", "status", "outcome", "provider", "model", "role", "mode", "channel", "kind",
                      "ticket", "room", "character", "name", "section", "path", "paths", "target", "all", "evidence"))


def text_err(evt: str, err: Any) -> Dict[str, Any]:
    """tl/F: an `err` given as text becomes the shape every reader takes -- {msg, type, fp}. The fingerprint is the
    event and the message with its numbers taken out, so one failure groups as one (the digest groups by fp; a text
    err used to be invisible to it, and broke it before #831)."""
    msg = redact(str(err))
    key = "%s|%s" % (evt, re.sub(r"\d+", "#", msg.splitlines()[0] if msg else "")[:120])
    return {"msg": msg[:STR_CAP], "type": "text", "where": evt, "fp": hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]}


def arg_meta(args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A tool call's arguments as metadata: numbers and flags as given, ids and kinds (ARG_KEEP), the program a command
    runs, and every other text by its size only."""
    out: Dict[str, Any] = {}
    for k, v in (args or {}).items():
        if v is None or isinstance(v, (bool, int, float)):
            out[k] = v
        elif k == "cmd":
            out[k] = (str(v).split() or [""])[0][:80]
        elif k in ARG_KEEP:
            out[k] = _clean(v, 200)
        elif isinstance(v, (list, tuple)):
            out[k] = {"items": len(v)}
        elif isinstance(v, dict):
            out[k] = {"keys": len(v)}
        else:
            out[k] = {"chars": len(str(v))}
    return out


def result_meta(out: Any) -> Dict[str, Any]:
    """What a tool answered, as counts: the length of each list in its data, and a short status word."""
    data = out.get("data") if isinstance(out, dict) else None
    if not isinstance(data, dict):
        return {}
    meta: Dict[str, Any] = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    st = data.get("status")
    if isinstance(st, str) and re.fullmatch(r"[a-z_]{1,20}", st):
        meta["status"] = st
    return {"result": meta} if meta else {}


def _clean(value: Any, cap: int = STR_CAP, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        v = redact(value)
        return v if len(v) <= cap else v[:cap] + "…(+%d)" % (len(v) - cap)
    if depth >= 4:
        return _clean(repr(value), cap, depth)
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 60:
                out["…"] = "+%d keys" % (len(value) - 60)
                break
            k = str(k)
            out[k] = "[redacted]" if _SECRET_KEY_RE.search(k) and v not in (None, "", 0, False) else _clean(v, cap, depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out_l = [_clean(v, cap, depth + 1) for v in seq[:50]]
        if len(seq) > 50:
            out_l.append("…+%d" % (len(seq) - 50))
        return out_l
    return _clean(str(value), cap, depth)


# -- time / ids -------------------------------------------------------------------------
def iso_now(t: Optional[float] = None) -> str:
    t = time.time() if t is None else t
    lt = time.localtime(t)
    off = lt.tm_gmtoff or 0
    sign = "+" if off >= 0 else "-"
    off = abs(off)
    return "%s.%03d%s%02d:%02d" % (time.strftime("%Y-%m-%dT%H:%M:%S", lt), int((t % 1) * 1000), sign, off // 3600, (off % 3600) // 60)


def new_rid() -> str:
    return uuid.uuid4().hex[:12]


def bind(**fields: Any) -> None:
    """Attach fields (rid, sid, caller) to every event this thread logs until unbind()."""
    ctx = dict(getattr(_local, "ctx", {}) or {})
    ctx.update({k: v for k, v in fields.items() if v is not None})
    _local.ctx = ctx


def unbind() -> None:
    _local.ctx = {}


def context() -> Dict[str, Any]:
    return dict(getattr(_local, "ctx", {}) or {})


# -- configuration ----------------------------------------------------------------------
def configure(src: str, path: Optional[os.PathLike] = None, mirror: str = "warn") -> None:
    p = path or os.environ.get("CHATBOT_OBSLOG_PATH") or None
    _state["src"] = src
    _state["path"] = Path(p) if p else None
    _state["mirror"] = mirror
    _state["started"] = time.time()
    try:
        if _state["path"] is not None:
            _state["path"].parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def configured() -> bool:
    return _state["path"] is not None


def stats() -> Dict[str, Any]:
    return {"lines": _state["lines"], "write_errors": _state["write_errors"],
            "path": str(_state["path"]) if _state["path"] else None}


# -- writing ----------------------------------------------------------------------------
def _rotate_if_needed(path: Path) -> None:
    try:
        if path.stat().st_size < MAX_BYTES:
            return
    except FileNotFoundError:
        return
    last = path.with_name("%s.%d" % (path.name, BACKUPS))
    if last.exists():   # tl/B: the file falling off the end goes to the archive, not away
        from telemetry import archive
        archive.stash(last, path)
    for i in range(BACKUPS - 1, 0, -1):
        src = path.with_name("%s.%d" % (path.name, i))
        if src.exists():
            os.replace(str(src), str(path.with_name("%s.%d" % (path.name, i + 1))))
    os.replace(str(path), str(path.with_name(path.name + ".1")))


def _write_line(line: str) -> None:
    path = _state["path"]
    if path is None:
        return
    data = (line + "\n").encode("utf-8", "replace")
    lockf = None
    try:
        with _lock:
            lockf = open(str(path) + ".lock", "a", encoding="utf-8", newline="\n")
            platform_compat.lock_file(lockf)          # flock on POSIX, msvcrt on Windows (pp/D)
            _rotate_if_needed(path)
            fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
            _state["lines"] += 1
    except Exception:
        _state["write_errors"] += 1
    finally:
        if lockf is not None:
            try:
                platform_compat.unlock_file(lockf)
                lockf.close()
            except Exception:
                pass


def _mirror(rec: dict) -> None:
    if LEVELS.get(rec["lvl"], 20) < LEVELS.get(_state["mirror"], 30):
        return
    extras = " ".join("%s=%s" % (k, rec[k]) for k in ("sid", "rid", "route", "status", "outcome", "caller") if rec.get(k) not in (None, ""))
    msg = rec.get("msg") or (rec.get("err") or {}).get("msg") or ""
    try:
        sys.stderr.write("%s %s %s %s %s %s\n" % (rec["ts"], rec["lvl"].upper(), rec["src"], rec["evt"], extras, msg))
        sys.stderr.flush()
    except Exception:
        pass


_dedup: Dict[str, List[float]] = {}  # key -> [first_ts_of_window, suppressed_count]
_fp_state: Dict[str, Dict[str, Any]] = {}  # err.fp -> {trace_t, win_t, n, supp, evt, lvl, type, msg, where}


def _storm_guard(fields: Dict[str, Any], evt: str, lvl: str, now: float) -> bool:
    """False = drop this line (counted). May strip the trace from fields["err"] in place."""
    err = fields.get("err")
    if not isinstance(err, dict) or not err.get("fp"):
        return True
    with _lock:
        st = _fp_state.get(err["fp"])
        if st is None:
            st = _fp_state[err["fp"]] = {"trace_t": 0.0, "win_t": now, "n": 0, "supp": 0}
            if len(_fp_state) > 2000:
                for k in sorted(_fp_state, key=lambda k: _fp_state[k]["win_t"])[:1000]:
                    if not _fp_state[k]["supp"]:
                        _fp_state.pop(k, None)
        st.update(evt=evt, lvl=lvl, type=err.get("type"), msg=err.get("msg"), where=err.get("where"))
        if now - st["win_t"] >= FP_WINDOW_SEC:
            st["win_t"], st["n"] = now, 0
        st["n"] += 1
        if st["n"] > FP_MAX_PER_WINDOW:
            st["supp"] += 1
            return False
        if "trace" in err:
            if now - st["trace_t"] < TRACE_EVERY_SEC:
                fields["err"] = {k: v for k, v in err.items() if k != "trace"}
                fields["err"]["trace_omitted"] = True
            else:
                st["trace_t"] = now
    return True


def flush_suppressed() -> None:
    """Settle storm counts: one log.suppressed line per fingerprint that had lines dropped."""
    with _lock:
        pending = [(fp, dict(st)) for fp, st in _fp_state.items() if st["supp"]]
        for fp, _ in pending:
            _fp_state[fp]["supp"] = 0
    for fp, st in pending:
        event("log.suppressed", lvl=st.get("lvl") or "warn", count=st["supp"], of_evt=st.get("evt"),
              err={"fp": fp, "type": st.get("type"), "msg": st.get("msg"), "where": st.get("where")},
              msg="%d more lines of this error were counted, not written (storm guard)" % st["supp"])


def event(evt: str, lvl: str = "info", msg: str = "", dedup: Optional[str] = None,
          dedup_window: float = DEDUP_WINDOW_SEC, **fields: Any) -> Optional[dict]:
    """Record one event. `dedup`: identical keys inside the window are counted, not written;
    the next write after the window carries `repeat` (how many were folded into it)."""
    try:
        now = time.time()
        repeat = 0
        if dedup:
            key = "%s|%s" % (evt, dedup)
            with _lock:
                slot = _dedup.get(key)
                if slot and now - slot[0] < dedup_window:
                    slot[1] += 1
                    return None
                if slot:
                    repeat = int(slot[1])
                _dedup[key] = [now, 0]
                if len(_dedup) > 5000:
                    for k in sorted(_dedup, key=lambda k: _dedup[k][0])[:2500]:
                        _dedup.pop(k, None)
        if fields.get("err") is not None and not isinstance(fields["err"], dict):
            fields["err"] = text_err(evt, fields["err"])
        if evt != "log.suppressed" and not _storm_guard(fields, evt, lvl, now):
            return None
        rec: Dict[str, Any] = {"ts": iso_now(now), "lvl": lvl if lvl in LEVELS else "info",
                               "src": _state["src"] or fields.pop("src", None) or "lib", "evt": evt, "pid": os.getpid()}
        fields.pop("src", None)
        for k, v in context().items():
            rec.setdefault(k, v)
        for k, v in fields.items():
            if v is not None:
                rec[k] = v
        if msg:
            rec["msg"] = msg
        if repeat:
            rec["repeat"] = repeat
        rec = _clean(rec, STR_CAP)
        if msg:
            rec["msg"] = _clean(msg, MSG_CAP)
        RECENT.append(rec)
        if _state["path"] is not None:
            _write_line(json.dumps(rec, ensure_ascii=False, separators=(",", ":"), default=str))
        if _state["src"] is not None:
            _mirror(rec)
        return rec
    except Exception:
        _state["write_errors"] += 1
        return None


def _frames(tb) -> List[traceback.FrameSummary]:
    try:
        return traceback.extract_tb(tb)
    except Exception:
        return []


def err_info(exc: BaseException, tb=None, with_trace: bool = True) -> Dict[str, Any]:
    """{type, msg, fp, where, trace}. `fp` groups the same bug across lines and restarts: the
    exception type plus the innermost project frames by file:function (no line numbers, so an
    unrelated edit above does not split the group)."""
    tb = tb if tb is not None else exc.__traceback__
    frames = _frames(tb)
    root = str(repo_layout.REPO)   # project frames: anything under the repository
    own = [f for f in frames if f.filename.startswith(root)] or frames
    tail = own[-3:]
    sig = type(exc).__name__ + "|" + "|".join("%s:%s" % (os.path.basename(f.filename), f.name) for f in tail)
    out: Dict[str, Any] = {
        "type": type(exc).__name__,
        "msg": _clean(str(exc), 500),
        "fp": hashlib.sha1(sig.encode("utf-8")).hexdigest()[:10],
    }
    if own:
        last = own[-1]
        out["where"] = "%s:%s:%s" % (os.path.relpath(last.filename, root) if last.filename.startswith(root) else os.path.basename(last.filename), last.lineno, last.name)
    if with_trace:
        text = "".join(traceback.format_exception(type(exc), exc, tb))
        out["trace"] = _clean(text[-TRACE_CAP:], TRACE_CAP)
    return out


def exception(evt: str, exc: Optional[BaseException] = None, msg: str = "", lvl: str = "error", **fields: Any) -> Optional[dict]:
    """Record an exception (defaults to the one being handled)."""
    try:
        if exc is None:
            exc = sys.exc_info()[1]
        if exc is not None:
            fields["err"] = err_info(exc)
        return event(evt, lvl=lvl, msg=msg, **fields)
    except Exception:
        return None


# -- HTTP -------------------------------------------------------------------------------
_SID_RE = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HEX_RE = re.compile(r"(?<=/)[0-9a-f]{16,}(?=/|$)", re.I)
_NUM_RE = re.compile(r"(?<=/)\d+(?=/|$)")


def sid_in(path: str) -> Optional[str]:
    m = _SID_RE.search(path or "")
    return m.group(0) if m else None


def route_of(path: str) -> str:
    """Collapse ids so one route is one aggregation key: /api/sessions/<sid>/log -> /api/sessions/:sid/log.
    Non-API files collapse by directory and extension (/persona/providers/agy.webp -> /persona/*.webp)."""
    p = (path or "/").split("?", 1)[0]
    p = _SID_RE.sub(":sid", p)
    p = _UUID_RE.sub(":uuid", p)
    p = _HEX_RE.sub(":id", p)
    p = _NUM_RE.sub(":n", p)
    if not p.startswith("/api/") and "." in p.rsplit("/", 1)[-1]:
        ext = p.rsplit(".", 1)[-1][:8]
        parts = [s for s in p.split("/") if s]
        p = ("/%s/*.%s" % (parts[0], ext)) if len(parts) > 1 else ("/*.%s" % ext)
    return p[:160]


class _RouteStats:
    __slots__ = ("n", "codes", "durs", "max")

    def __init__(self) -> None:
        self.n = 0
        self.codes: Dict[str, int] = {}
        self.durs: List[float] = []
        self.max = 0.0

    def add(self, status: Any, dur_ms: float) -> None:
        self.n += 1
        key = "%sxx" % str(status)[0] if isinstance(status, int) else str(status)
        self.codes[key] = self.codes.get(key, 0) + 1
        if len(self.durs) < 2000:
            self.durs.append(dur_ms)
        self.max = max(self.max, dur_ms)

    def snapshot(self) -> Dict[str, Any]:
        d = sorted(self.durs)
        pct = (lambda q: round(d[min(len(d) - 1, int(q * len(d)))], 1)) if d else (lambda q: None)
        return {"n": self.n, "codes": self.codes, "p50": pct(0.5), "p95": pct(0.95), "max": round(self.max, 1)}


_http_lock = threading.Lock()
_http: Dict[str, _RouteStats] = {}
_http_window_start = time.time()


def http_request(method: str, path: str, status: Any, dur_ms: float, quiet: bool = False,
                 stream: bool = False, err: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
    """One finished HTTP request. Always counted in http.summary; written individually when it
    matters: status >= 400, an exception, slow (non-stream), or a mutation (unless quiet)."""
    try:
        route = "%s %s" % (method or "?", route_of(path))
        with _http_lock:
            _http.setdefault(route, _RouteStats()).add(status, dur_ms)
        code = status if isinstance(status, int) else 0
        if code == 404 and not err and path.startswith(EXPECTED_404_PREFIXES):
            return  # client discovery probes (MCP OAuth metadata): counted in http.summary only
        base = dict(route=route, status=status, dur_ms=round(dur_ms, 1))
        sid = sid_in(path)
        if sid:
            base["sid"] = sid
        base.update(fields)
        if code >= 500 or (err and not 400 <= code < 500):
            event("http.error", lvl="error", err=err, path=path, **base)
        elif code >= 400:
            event("http.client_error", lvl="warn", dedup="%s|%s" % (route, code), err=err, path=path, **base)
        elif status == "gone":
            event("http.client_gone", lvl="info", dedup=route, dedup_window=600, **base)
        elif not stream and dur_ms >= SLOW_MS:
            event("http.slow", lvl="warn", **base)
        elif not quiet and method in ("POST", "PUT", "DELETE", "PATCH"):
            event("http.request", **base)
    except Exception:
        pass


def flush_http_summary() -> None:
    global _http_window_start
    with _http_lock:
        snap = {k: v.snapshot() for k, v in sorted(_http.items())}
        _http.clear()
        start, _http_window_start = _http_window_start, time.time()
    if snap:
        event("http.summary", window_s=int(time.time() - start), total=sum(v["n"] for v in snap.values()), routes=snap)
    flush_suppressed()


_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class HTTPLogMixin:
    """Mix in before BaseHTTPRequestHandler. Times every request, tags it with a request id
    (thread-bound, echoed as X-Request-Id), keeps the exception that a route's catch-all turned
    into a 4xx/5xx (it is still being handled when send_response runs), folds client
    disconnects (BrokenPipe/reset) into http.client_gone instead of a stderr traceback, and
    replaces the stdlib access line with http_request(). Override _obs_path/_obs_quiet/_obs_stream
    per server."""

    _obs_t0 = 0.0
    _obs_status: Any = None
    _obs_exc: Any = None
    _obs_gone = False
    _obs_rid: Optional[str] = None
    _obs_note: Optional[str] = None

    def _obs_path(self, raw: str) -> str:
        return raw

    def _obs_quiet(self, method: str, path: str) -> bool:
        return False

    def _obs_stream(self, method: str, path: str) -> bool:
        return False

    def log_request(self, code: Any = "-", size: Any = "-") -> None:  # stdlib access line: replaced
        pass

    def log_message(self, fmt: str, *args: Any) -> None:  # only log_error reaches here now
        try:
            self._obs_note = (fmt % args)[:300]
        except Exception:
            pass

    def send_response(self, code: int, message: Optional[str] = None) -> None:
        self._obs_status = code
        if code >= 400 and self._obs_exc is None:
            ei = sys.exc_info()
            if ei[1] is not None:
                self._obs_exc = ei
        super().send_response(code, message)  # type: ignore[misc]
        if self._obs_rid:
            self.send_header("X-Request-Id", self._obs_rid)  # type: ignore[attr-defined]

    def handle_one_request(self) -> None:
        self._obs_t0 = time.monotonic()
        self._obs_status = None
        self._obs_exc = None
        self._obs_gone = False
        self._obs_note = None
        self._obs_rid = new_rid()
        self.command = None  # type: ignore[assignment]
        bind(rid=self._obs_rid)
        try:
            super().handle_one_request()  # type: ignore[misc]
        except _CLIENT_GONE:
            self._obs_gone = True
            self.close_connection = True
        except Exception:
            self._obs_exc = sys.exc_info()
            self.close_connection = True
        finally:
            try:
                self._obs_finish()
            finally:
                unbind()

    def _obs_finish(self) -> None:
        method = getattr(self, "command", None)
        if not method and self._obs_status is None and self._obs_exc is None:
            return  # idle keep-alive connection closed: no request happened
        try:
            raw = (getattr(self, "path", "") or "").split("?", 1)[0].split("#", 1)[0]
            path = self._obs_path(raw)
        except Exception:
            path = "?"
        dur = (time.monotonic() - self._obs_t0) * 1000.0
        status: Any = "gone" if self._obs_gone else (self._obs_status or 0)
        err = None
        if self._obs_exc is not None and isinstance(self._obs_exc[1], _CLIENT_GONE):
            # the route's catch-all tried to answer an error to a client that had already left
            status, self._obs_exc = "gone", None
        if self._obs_exc is not None:
            exc = self._obs_exc[1]
            with_trace = not (isinstance(status, int) and 400 <= status < 500)
            err = err_info(exc, self._obs_exc[2], with_trace=with_trace)
        headers = getattr(self, "headers", None)
        caller = headers.get("X-Chatbot-Caller") if headers is not None else None
        m = method or "?"
        http_request(m, path, status, dur, quiet=self._obs_quiet(m, path), stream=self._obs_stream(m, path),
                     err=err, caller=caller, note=self._obs_note)


# -- process lifecycle / heartbeat ------------------------------------------------------
def _proc_status() -> Dict[str, Any]:
    out: Dict[str, Any] = {"uptime_s": int(time.time() - _state["started"])}
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = round(int(line.split()[1]) / 1024.0, 1)
                elif line.startswith("Threads:"):
                    out["threads"] = int(line.split()[1])
    except Exception:
        out["threads"] = threading.active_count()
    try:
        out["fds"] = len(os.listdir("/proc/self/fd"))
    except Exception:
        pass
    try:
        t = os.times()
        out["cpu_s"] = round(t.user + t.system, 1)
    except Exception:
        pass
    out["log_write_errors"] = _state["write_errors"]
    return out


def _git_sha() -> Optional[str]:
    try:
        head = (repo_layout.REPO / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = repo_layout.REPO / ".git" / head.split(" ", 1)[1]
            if ref.exists():
                return ref.read_text(encoding="utf-8").strip()[:10]
            packed = repo_layout.REPO / ".git" / "packed-refs"
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(head.split(" ", 1)[1]):
                    return line.split()[0][:10]
            return None
        return head[:10]
    except Exception:
        return None


_heartbeat_fns: List[Callable[[], Dict[str, Any]]] = []
_bg_started = False


def add_heartbeat(fn: Callable[[], Dict[str, Any]]) -> None:
    """Register a callable whose dict is merged into every proc.heartbeat."""
    _heartbeat_fns.append(fn)


def heartbeat() -> None:
    data = _proc_status()
    for fn in list(_heartbeat_fns):
        try:
            data.update(fn() or {})
        except Exception as e:  # noqa: BLE001
            data.setdefault("heartbeat_errors", []).append("%s: %s" % (type(e).__name__, e))
    event("proc.heartbeat", every_s=SUMMARY_EVERY_SEC, **data)


ARCHIVE_EVERY_SEC = 3600


def archive_tick(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """tl/B: compress and prune the archive about once an hour; logs `log.archive` when something changed."""
    now = time.time() if now is None else now
    if _state["path"] is None or now - _state.get("archived_at", 0) < ARCHIVE_EVERY_SEC:
        return None
    _state["archived_at"] = now
    from telemetry import archive
    got = archive.maintain(_state["path"], now)
    if got.get("compressed") or got.get("pruned"):
        event("log.archive", **got)
    return got


ROLLUP_EVERY_SEC = 3600


def rollup_tick(now: Optional[float] = None) -> Optional[List[str]]:
    """tl/C: write the daily rollups that are missing (yesterday, or a backlog) about once an hour."""
    now = time.time() if now is None else now
    if _state["path"] is None or now - _state.get("rolled_at", 0) < ROLLUP_EVERY_SEC:
        return None
    _state["rolled_at"] = now
    from telemetry import rollup
    days = rollup.build_missing(_state["path"], now)
    if days:
        event("log.rollup", days=len(days), first=days[0], last=days[-1])
    return days


def _bg_loop() -> None:
    while True:
        time.sleep(SUMMARY_EVERY_SEC)
        try:
            flush_http_summary()
            heartbeat()
            archive_tick()
            rollup_tick()
        except Exception:
            pass


def _on_exit() -> None:
    if _state.get("exited"):
        return
    try:
        _state["exited"] = True
        flush_http_summary()
        event("proc.exit", **_proc_status())
    except Exception:
        pass


def start_process(src: str, **info: Any) -> None:
    """Configure, log proc.start (pid, git sha, argv, python), hook uncaught exceptions in the main
    thread and in worker threads, and start the summary/heartbeat thread."""
    global _bg_started
    configure(src)
    # The path is now held in _state. Children (CLI agents, and the tests an agent runs) must not
    # inherit it, or a test server they start writes fake restarts into the production log.
    os.environ.pop("CHATBOT_OBSLOG_PATH", None)
    caller = os.environ.pop("CHATBOT_CALLER", None)
    event("proc.start", lvl="info", git=_git_sha(), python=sys.version.split()[0],
          argv=sys.argv[:6], ppid=os.getppid(), caller=caller, **info)
    _mirror({"ts": iso_now(), "lvl": "warn", "src": src, "evt": "proc.start", "msg": "pid=%d" % os.getpid()})

    prev_hook = sys.excepthook

    def _hook(tp, val, tb):
        exception("proc.crash", val, msg="uncaught exception in main thread")
        prev_hook(tp, val, tb)

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        def _thook(args):  # type: ignore[no-untyped-def]
            if args.exc_type is SystemExit:
                return
            exception("thread.crash", args.exc_value, thread=getattr(args.thread, "name", None))
        threading.excepthook = _thook
    atexit.register(_on_exit)
    if not _bg_started:
        _bg_started = True
        threading.Thread(target=_bg_loop, name="obslog", daemon=True).start()


def stop_process(reason: str = "signal") -> None:
    """Call from a signal handler that ends with os._exit (atexit does not run then)."""
    if _state.get("exited"):
        return
    try:
        _state["exited"] = True
        flush_http_summary()
        event("proc.exit", reason=reason, **_proc_status())
    except Exception:
        pass


# -- CLI --------------------------------------------------------------------------------
def _coerce(v: str) -> Any:
    if re.fullmatch(r"-?\d{1,15}", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def main(argv: List[str]) -> int:
    if not argv or argv[0] != "emit":
        sys.stderr.write(__doc__.split("Command line", 1)[1])
        return 2
    args = argv[1:]
    opts = {"src": "ctl", "evt": None, "lvl": "info", "msg": "", "dedup": None}
    fields: Dict[str, Any] = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--") and a[2:] in opts and i + 1 < len(args):
            opts[a[2:]] = args[i + 1]
            i += 2
            continue
        if "=" in a:
            k, v = a.split("=", 1)
            fields[k] = _coerce(v)
        i += 1
    if not opts["evt"]:
        sys.stderr.write("obslog emit: --evt required\n")
        return 2
    configure(str(opts["src"]), mirror="error")
    caller = os.environ.get("CHATBOT_CALLER")
    if caller and "caller" not in fields:
        fields["caller"] = caller
    event(str(opts["evt"]), lvl=str(opts["lvl"]), msg=str(opts["msg"]), dedup=opts["dedup"], **fields)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
