"""Login account + agent-process visibility for the 상태 탭 (agy/claude/codex/grok).

Born from the 2026-09-19 incident: agy was re-logged-in as another account but
kept answering as the old one, because a two-day-old interactive `agy` from an
SSH session still held the old refresh token in memory and rewrote the shared
token file on its next refresh. Nothing in the UI showed which account was
active or that a stray process existed.

What each provider lets us know (measured 2026-09-19, docs/providers/*.md):
  * current account -- agy: id_token in its token file; claude: `claude auth
    status`; codex: id_token in auth.json; grok: plain `email` in auth.json.
  * per-process account -- ONLY agy (its log names the pid and the account).
    The others leave no per-process account record, so for them a process is
    only ever flagged `predates_change`: it started before the last observed
    account change. That is a fact about timing, not a claim that it holds the
    old credentials.

Read-only by design: token files are decoded only for the email/plan claims (no
token value ever leaves this module) and /proc/<pid>/environ is never read.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from host_config import DATA, HOME

PROVIDERS = ("agy", "claude", "codex", "grok")

AGY_DIR = HOME / ".gemini" / "antigravity-cli"
AGY_TOKEN = AGY_DIR / "antigravity-oauth-token"
AGY_LOG_DIR = AGY_DIR / "log"
CODEX_AUTH = HOME / ".codex" / "auth.json"
GROK_AUTH = Path(os.environ.get("GROK_HOME") or str(HOME / ".grok")) / "auth.json"
CLAUDE_BIN = os.environ.get("AGY_CLAUDE_BIN", str(HOME / ".local" / "bin" / "claude"))
STATE_FILE = DATA / "account_state.json"

_LOG_PID_RE = re.compile(rb"Starting language server process with pid (\d+)")
_LOG_AUTH_RE = re.compile(rb"authenticated successfully as (\S+)")
_LOG_NAME_RE = re.compile(r"^cli-(\d{8}_\d{6})\.log$")

_CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
_log_account_cache: Dict[str, tuple] = {}  # path -> ((mtime, size), pid, email)
_claude_cache = {"ts": 0.0, "data": None}
CLAUDE_STATUS_TTL_SEC = 60
_state_lock = threading.Lock()


def _jwt_claims(tok: str) -> dict:
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def _short(path: Path) -> str:
    return str(path).replace(str(HOME), "~", 1)


def _read_json(path: Path):
    """(data, mtime, error) -- error is a user-facing string or None."""
    try:
        st = path.stat()
        return json.loads(path.read_text(encoding="utf-8")), st.st_mtime, None
    except FileNotFoundError:
        return None, None, "로그인 안 됨 (인증 파일 없음)"
    except Exception as e:
        return None, None, f"인증 파일을 읽지 못했습니다: {type(e).__name__}"


# ---------------------------------------------------------------- accounts

def agy_account() -> dict:
    d, mtime, err = _read_json(AGY_TOKEN)
    if err:
        return {"ok": False, "error": err}
    claims = _jwt_claims(d.get("id_token") or "")
    return {
        "ok": bool(claims.get("email")),
        "email": claims.get("email"),
        "plan": d.get("auth_method"),
        "source": _short(AGY_TOKEN),
        "issued_at": claims.get("iat"),
        "expires_at": claims.get("exp"),
        "file_mtime": mtime,
    }


def codex_account() -> dict:
    d, mtime, err = _read_json(CODEX_AUTH)
    if err:
        return {"ok": False, "error": err}
    tokens = d.get("tokens") if isinstance(d.get("tokens"), dict) else {}
    claims = _jwt_claims(tokens.get("id_token") or "")
    auth = claims.get("https://api.openai.com/auth")
    return {
        "ok": bool(claims.get("email")),
        "email": claims.get("email"),
        "plan": auth.get("chatgpt_plan_type") if isinstance(auth, dict) else None,
        "source": _short(CODEX_AUTH),
        "expires_at": claims.get("exp"),
        "file_mtime": mtime,
    }


def grok_account() -> dict:
    d, mtime, err = _read_json(GROK_AUTH)
    if err:
        return {"ok": False, "error": err}
    best, best_rank = None, ""
    for v in (d.values() if isinstance(d, dict) else []):
        # same pick rule as adapters._grok_access_token: newest entry wins
        if isinstance(v, dict) and v.get("email"):
            rank = str(v.get("expires_at") or v.get("create_time") or "")
            if best is None or rank > best_rank:
                best, best_rank = v, rank
    if not best:
        return {"ok": False, "error": "로그인 안 됨 (email 항목 없음)"}
    return {
        "ok": True,
        "email": best.get("email"),
        "plan": best.get("auth_mode"),
        "source": _short(GROK_AUTH),
        "expires_at_iso": best.get("expires_at"),
        "file_mtime": mtime,
    }


def claude_account() -> dict:
    """`claude auth status` -- the credentials file carries no email. Costs a
    ~0.9s subprocess, so cached; failures are cached too (no hammering)."""
    now = time.time()
    with _state_lock:
        if _claude_cache["data"] is not None and now - _claude_cache["ts"] < CLAUDE_STATUS_TTL_SEC:
            return _claude_cache["data"]
    try:
        out = subprocess.run([CLAUDE_BIN, "auth", "status"], capture_output=True, text=True, timeout=20)
        d = json.loads(out.stdout)
        data = {
            "ok": bool(d.get("loggedIn") and d.get("email")),
            "email": d.get("email"),
            "plan": d.get("subscriptionType"),
            "source": f"claude auth status ({d.get('authMethod')})",
        }
        if not data["ok"]:
            data["error"] = "로그인 안 됨"
    except Exception as e:
        data = {"ok": False, "error": f"claude auth status 실패: {type(e).__name__}"}
    with _state_lock:
        _claude_cache.update(ts=now, data=data)
    return data


_ACCOUNT_FN = {"agy": agy_account, "claude": claude_account, "codex": codex_account, "grok": grok_account}


def current_email(provider: str) -> Optional[str]:
    """Email the provider is logged in as right now, or None when it is unknown
    (logged out, unreadable, or a provider with no account concept such as
    omniroute). Callers must treat None as "don't know", never as "changed".
    claude goes through the 60s-cached `auth status`, so its switch is seen
    within a minute."""
    fn = _ACCOUNT_FN.get(provider)
    if not fn:
        return None
    try:
        acct = fn()
    except Exception:
        return None
    return acct.get("email") if acct.get("ok") else None


# ------------------------------------------------- change observation (state)

def _load_state() -> dict:
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def observe(provider: str, account: dict, now: Optional[float] = None) -> Optional[list]:
    """Record the account seen for `provider`; return the last known change
    window [last_seen_with_old_account, first_seen_with_new_account] or None.
    Any process that started before window[0] certainly started under the old
    account. One that started inside the window is ambiguous and is NOT
    flagged -- the rule can miss, but it cannot cry wolf."""
    now = now or time.time()
    email = account.get("email") if account.get("ok") else None
    with _state_lock:
        state = _load_state()
        cur = state.get(provider) or {}
        if email and cur.get("email") and cur["email"] != email:
            cur["change_window"] = [cur.get("seen_at", now), now]
            cur["changed_from"] = cur["email"]
        if email:
            cur["email"] = email
            cur["seen_at"] = now
            state[provider] = cur
            _save_state(state)
        return cur.get("change_window")


def watch_loop(interval: int = 60) -> None:
    """Background sampler so an account change is noticed within ~a minute even
    if nobody has the status tab open (the change window stays narrow)."""
    while True:
        for p in PROVIDERS:
            try:
                observe(p, _ACCOUNT_FN[p]())
            except Exception:
                pass
        time.sleep(interval)


# --------------------------------------------------------------- /proc scan

def _boot_time() -> float:
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except Exception:
        pass
    return 0.0


def _stat_fields(pid: int) -> Optional[List[str]]:
    """Fields after `(comm) ` in /proc/<pid>/stat (comm may hold spaces/parens,
    so split on the LAST ')'). Index 0 is field 3 (state)."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        return raw[raw.rindex(")") + 2:].split()
    except Exception:
        return None


def _comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except Exception:
        return ""


def _tty(pid: int) -> str:
    try:
        t = os.readlink(f"/proc/{pid}/fd/0")
        # only a real terminal counts; stdin=/dev/null or a pipe is "no tty"
        return t[5:] if t.startswith(("/dev/pts/", "/dev/tty")) else "-"
    except Exception:
        return "?"


def _scan_procs() -> Dict[str, List[dict]]:
    """provider -> processes whose argv[0] basename is that provider's CLI."""
    out: Dict[str, List[dict]] = {p: [] for p in PROVIDERS}
    boot = _boot_time()
    for n in os.listdir("/proc"):
        if not n.isdigit():
            continue
        try:
            argv = Path(f"/proc/{n}/cmdline").read_bytes().split(b"\0")
        except Exception:
            continue
        exe = os.path.basename(argv[0].decode("utf-8", "replace")) if argv else ""
        if exe not in out:
            continue
        pid = int(n)
        f = _stat_fields(pid)
        if not f:
            continue
        out[exe].append({
            "pid": pid,
            "ppid": int(f[1]),
            "started_at": boot + int(f[19]) / _CLK_TCK if boot else 0.0,
            "cmd": " ".join(a.decode("utf-8", "replace") for a in argv if a)[:200],
        })
    return out


# ----------------------------------------------------- agy log -> account

def _log_index(min_ts: float) -> List[tuple]:
    out = []
    try:
        names = os.listdir(AGY_LOG_DIR)
    except Exception:
        return out
    for n in names:
        m = _LOG_NAME_RE.match(n)
        if not m:
            continue
        try:
            ts = time.mktime(time.strptime(m.group(1), "%Y%m%d_%H%M%S"))
        except Exception:
            continue
        if ts >= min_ts:
            out.append((ts, AGY_LOG_DIR / n))
    return out


def _read_log(path: Path) -> tuple:
    """(pid, last authenticated email) of one agy log, cached by mtime+size."""
    try:
        st = path.stat()
    except Exception:
        return None, None
    key = (st.st_mtime, st.st_size)
    hit = _log_account_cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1], hit[2]
    pid = email = None
    try:
        data = path.read_bytes()
        m = _LOG_PID_RE.search(data[:4096])
        if m:
            pid = int(m.group(1))
        found = _LOG_AUTH_RE.findall(data)
        if found:
            email = found[-1].decode("utf-8", "replace")
    except Exception:
        pass
    _log_account_cache[str(path)] = (key, pid, email)
    return pid, email


def _agy_process_accounts(procs: List[dict], now: float) -> None:
    logs = _log_index(min((p["started_at"] for p in procs), default=now) - 5)
    for p in procs:
        p["account"] = None
        for ts, path in logs:
            if ts < p["started_at"] - 5 or ts > p["started_at"] + 30:
                continue
            lpid, lmail = _read_log(path)
            if lpid == p["pid"]:  # exact: the log's first line names the pid
                p["account"] = lmail
                break


# ---------------------------------------------------------------- snapshot

def snapshot(owned: Optional[Dict[int, dict]] = None, providers: tuple = PROVIDERS) -> dict:
    """Per provider: current account + running CLI processes. `owned` maps pid
    -> {"owner": "session"|"standby", ...} for processes this chatbot spawned
    (see session.owned_agent_procs). Top-level `stale_count` counts only agy
    processes PROVEN to hold another account (log evidence)."""
    owned = owned or {}
    now = time.time()
    me = os.getpid()
    scanned = _scan_procs()
    _agy_process_accounts(scanned["agy"], now)

    out = {}
    for prov in providers:
        current = _ACCOUNT_FN[prov]()
        window = observe(prov, current, now)
        cur_email = current.get("email") if current.get("ok") else None
        with _state_lock:
            changed_from = (_load_state().get(prov) or {}).get("changed_from")
        procs = sorted(scanned[prov], key=lambda p: p["started_at"])
        for p in procs:
            info = owned.get(p["pid"])
            if info:
                owner = info.get("owner", "session")
            elif p["ppid"] == me:
                owner = "chatbot-other"  # e.g. `agy --print /usage`, doctor probe
            else:
                owner = "external"
            account = p.get("account")
            p.update({
                "owner": owner,
                "sid": (info or {}).get("sid"),
                "busy": bool((info or {}).get("busy")),
                "account": account,
                "stale": bool(account and cur_email and account != cur_email),
                "predates_change": bool(window and p["started_at"] and p["started_at"] < window[0]),
                "tty": _tty(p["pid"]),
                "parent": _comm(p["ppid"]),
                "age_sec": int(now - p["started_at"]) if p["started_at"] else None,
            })
            if owner == "external" and (p["stale"] or p["predates_change"]):
                p["kill_cmd"] = f"kill {p['pid']}"
        out[prov] = {
            "current": current,
            "processes": procs,
            "account_evidence": "log" if prov == "agy" else "none",
            "stale_count": sum(1 for p in procs if p["stale"]),
            "predates_count": sum(1 for p in procs if p["predates_change"] and not p["stale"]),
            # Last observed account switch: the switch happened somewhere in
            # [changed_window_start, changed_at]; `changed_at` is when we first
            # saw the new account.
            "changed_from": changed_from if window else None,
            "changed_at": window[1] if window else None,
        }
    return {
        "ok": True,
        "providers": out,
        "stale_count": out.get("agy", {}).get("stale_count", 0),
        "checked_at": now,
    }


def parse_providers(value: Optional[str]) -> tuple:
    """`?provider=` of /api/accounts -> which providers to snapshot. None -> all;
    a known provider -> just that one (skips the other CLIs' status calls);
    anything else (e.g. omniroute: API key, no login) -> none."""
    if not value:
        return PROVIDERS
    return (value,) if value in PROVIDERS else ()


def stale_owned(snap: dict) -> set:
    """pids of chatbot-owned agy processes PROVEN (log evidence) to hold an
    account other than the current one. The one definition of "recycle
    candidate", shared by the manual button and the auto-recycle loop. Never
    includes external processes, and never a claude/codex/grok process (no
    per-process account evidence there)."""
    agy = (snap.get("providers") or {}).get("agy") or {}
    return {p["pid"] for p in agy.get("processes", [])
            if p.get("stale") and p.get("owner") in ("session", "standby")}
