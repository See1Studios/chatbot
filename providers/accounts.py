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

Read-only by design for snapshots: token files are decoded only for the
email/plan claims (no token value ever leaves this module) and
/proc/<pid>/environ is never read.

Logout (Status tab): see `logout()`. Login (Status tab): see `account_login`
(POST /api/accounts/login/start|complete|cancel, GET .../status).
  * agy: Google OAuth URL then paste 4/0A… code (oauth_paste)
  * claude: browser OAuth URL → localhost:port/callback (oauth_callback)
  * grok / codex: device-auth (device_code)
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
from typing import Callable, Dict, List, Optional

import platform_compat
from host_config import DATA, HOME, CLAUDE_BIN, CODEX_BIN, GROK_BIN

PROVIDERS = ("agy", "claude", "codex", "grok")

AGY_DIR = HOME / ".gemini" / "antigravity-cli"
AGY_TOKEN = AGY_DIR / "antigravity-oauth-token"
AGY_LOG_DIR = AGY_DIR / "log"
AGY_PROFILES_DIR = AGY_DIR / "tokens"   # saved logins, one <email>.json each (created on first use)
CODEX_AUTH = HOME / ".codex" / "auth.json"
GROK_AUTH = Path(os.environ.get("GROK_HOME") or str(HOME / ".grok")) / "auth.json"
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


def login_fingerprint(provider: str) -> Optional[str]:
    """A short hash of the stored refresh token: it changes on a new login, not on a routine access-token refresh
    (which rewrites the file hourly). Lets a login flow tell "logged in again, same email" from "nothing happened".
    None when the provider stores no readable one. The token itself never leaves this module."""
    import hashlib
    if provider != "agy":
        return None
    d, _mtime, err = _read_json(AGY_TOKEN)
    tok = (d or {}).get("refresh_token") if not err else None
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()[:16] if tok else None


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
        platform_compat.write_text(tmp, json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def _publish_switch(provider: str) -> None:
    """An account switch, for the event mailbox (evt/C): which provider, never which account."""
    try:
        import events
        events.publish("account.switch", events.ALL, subject=provider)
    except Exception:  # noqa: BLE001
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
            _publish_switch(provider)
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
        for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except Exception:
        pass
    return 0.0


def _stat_fields(pid: int) -> Optional[List[str]]:
    """Fields after `(comm) ` in /proc/<pid>/stat (comm may hold spaces/parens,
    so split on the LAST ')'). Index 0 is field 3 (state)."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return raw[raw.rindex(")") + 2:].split()
    except Exception:
        return None


def _comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


RUNNER_MARK = "worktree_runner.py"   # a delegated worker's parent (tools/worktree_runner.py)


def _is_runner(pid: int) -> bool:
    return any(a.endswith(RUNNER_MARK) for a in platform_compat.proc_cmdline(pid))


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
    if not platform_compat.has_proc():   # Windows, macOS: no /proc -- no running-CLI snapshot yet (pp/E), no crash
        return out
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


def agy_log_for(pid: int, started: float) -> Optional[Path]:
    """The agy log of process `pid` (its first lines name the pid), among logs begun since `started`."""
    for _ts, path in sorted(_log_index(started - 5)):
        if _read_log(path)[0] == pid:
            return path
    return None


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

# PROVIDER_NEUTRAL_v1: provider traits the common server asks about, declared here (the provider
# module), never tested by name there.
# Providers whose running processes keep the login they started with: after a login change the
# idle owned ones must be restarted (auto-recycle, login, "restart processes").
RECYCLE_ON_LOGIN: tuple = ("agy",)
# Extra words shown after a successful logout of that provider.
LOGOUT_NOTES: Dict[str, str] = {
    "agy": ("agy 토큰 파일을 백업·제거했고 소유 프로세스를 재시작했어요. "
            "외부(SSH 등) agy는 수동으로 종료해야 옛 토큰이 파일을 되쓰지 않아요."),
}


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
            elif _is_runner(p["ppid"]):
                owner = "worker"         # a delegated worker or reviewer (worktree_runner); ACCOUNT_SWITCH_v1
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


def stale_workers(snap: dict) -> set:
    """pids of delegated workers (owner "worker") PROVEN to hold an account other than the current one. The runner
    that started one sees the login change when it exits and runs the same step again (worktree_runner
    run_as_login), so stopping it costs no attempt (ACCOUNT_SWITCH_v1, operator 2026-09-30)."""
    agy = (snap.get("providers") or {}).get("agy") or {}
    return {p["pid"] for p in agy.get("processes", []) if p.get("stale") and p.get("owner") == "worker"}


def stop_workers(pids: set) -> list:
    """Stop each pid that is still a delegated worker (re-checked: a pid can be reused). Returns those stopped."""
    stopped = []
    for pid in sorted(pids):
        f = _stat_fields(pid)
        if f and _is_runner(int(f[1])) and platform_compat.terminate(pid):
            stopped.append(pid)
    return stopped


SWITCH_RERUNS = 2


def rerun_on_switch(provider: str, run, log=None, reruns: int = SWITCH_RERUNS):
    """`run()` -> (returncode, ...), run again when it failed and the provider's login changed meanwhile: the server
    stops a delegated worker still holding the old login (stop_workers), which is not the work's fault, so the step
    runs again under the new one instead of costing the ticket an attempt (ACCOUNT_SWITCH_v1). Only for providers
    whose processes keep the login they started with (RECYCLE_ON_LOGIN)."""
    if provider not in RECYCLE_ON_LOGIN:
        return run()
    for _ in range(1 + reruns):
        before = current_email(provider)
        res = run()
        if res[0] == 0 or not before or current_email(provider) in (None, before):
            break
        if log:
            log("%s login changed while it ran; running the same step again under the new login" % provider)
    return res


# -------------------------------------------------------------------- logout

def owned_pids(snap: dict, provider: str) -> set:
    """Chatbot-owned (session|standby) pids for one provider from a snapshot."""
    pv = (snap.get("providers") or {}).get(provider) or {}
    return {p["pid"] for p in pv.get("processes", [])
            if p.get("owner") in ("session", "standby")}


def _is_cli_helper(args: list) -> bool:
    """A login/app-server subcommand or a `--print /usage|/cost` probe, judged by whole arguments: a chat turn is
    `agy -p <prompt>`, and a prompt that merely mentions "login" once got a live session child stopped (#542)."""
    if args[:1] in (["login"], ["app-server"]) or args[:2] == ["auth", "login"]:
        return True
    return any(a in ("--print", "-p") and b in ("/usage", "/cost") for a, b in zip(args, args[1:]))


def reap_stray_cli_procs(provider: str, me: Optional[int] = None) -> list:
    """CODEX_PROC_v1: kill leftover CLI helpers that are not chatbot session
    children — typically `codex login` / `codex app-server` (usage) or a native
    binary orphaned (ppid=1) after the node wrapper was terminate()'d without
    killpg. Safe: only targets basename==provider AND (ppid==1 OR cmdline has
    login/app-server/--print /usage|/cost). Never touches grok casually beyond
    the same rules; never kills busy session children (those have live ppid)."""
    import signal as _signal
    if provider not in PROVIDERS:
        return []
    me = os.getpid() if me is None else me
    try:
        from providers import account_login
        protect_pid = account_login.active_pid(provider)
    except Exception:
        protect_pid = None
    killed = []
    for n in os.listdir("/proc"):
        if not n.isdigit():
            continue
        try:
            pid = int(n)
            if pid == me:
                continue
            if protect_pid is not None and pid == protect_pid:
                continue
            argv = Path(f"/proc/{n}/cmdline").read_bytes().split(b"\0")
            if not argv or not argv[0]:
                continue
            exe = os.path.basename(argv[0].decode("utf-8", "replace"))
            if exe != provider:
                continue
            f = _stat_fields(pid)
            if not f:
                continue
            ppid = int(f[1])
            cmd = " ".join(a.decode("utf-8", "replace") for a in argv if a)
            is_helper = _is_cli_helper([a.decode("utf-8", "replace") for a in argv[1:] if a])
            # Orphaned native child after wrapper death
            is_orphan = ppid == 1
            if not (is_helper or is_orphan):
                continue
            # Never kill our own live session child by accident: session children
            # have ppid == chatbot server, not 1, and are not login/app-server.
            if ppid == me and not is_helper:
                continue
            try:
                try:
                    os.killpg(pid, _signal.SIGTERM)
                except Exception:
                    os.kill(pid, _signal.SIGTERM)
                killed.append({"pid": pid, "cmd": cmd[:160], "reason": "orphan" if is_orphan and not is_helper else "helper"})
            except OSError:
                pass
        except Exception:
            continue
    return killed



def _invalidate_claude_cache() -> None:
    with _state_lock:
        _claude_cache.update(ts=0.0, data=None)


def _run_cli_logout(argv: list, timeout: int = 45) -> tuple:
    """Run a non-interactive logout CLI. Returns (ok, detail)."""
    try:
        out = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False, f"{argv[0]} not found"
    except subprocess.TimeoutExpired:
        return False, f"{' '.join(argv)} timed out"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    detail = (out.stderr or out.stdout or "").strip().splitlines()
    detail = detail[-1][:200] if detail else f"exit {out.returncode}"
    if out.returncode != 0:
        return False, detail
    return True, detail or "ok"


def _logout_agy() -> tuple:
    """No `agy logout` subcommand — rename the shared OAuth token (A30: long-lived
    processes can rewrite it from an in-memory refresh token, so callers must
    recycle owned agy procs after this). Login follow-up: Google OAuth URL +
    code paste (not implemented here)."""
    if not AGY_TOKEN.exists():
        return True, "already_logged_out", "token file absent"
    ts = int(time.time())
    bak = AGY_TOKEN.with_name(f"{AGY_TOKEN.name}.bak-{ts}")
    try:
        os.rename(AGY_TOKEN, bak)
    except Exception as e:
        return False, "rename_failed", f"{type(e).__name__}: {e}"
    return True, "renamed_token", _short(bak)


def _logout_claude() -> tuple:
    """`claude auth logout` (non-interactive). Login follow-up: browser OAuth."""
    ok, detail = _run_cli_logout([CLAUDE_BIN, "auth", "logout"])
    _invalidate_claude_cache()
    return ok, "claude_auth_logout", detail


def _logout_codex() -> tuple:
    """`codex logout`. Login follow-up: device-auth / API key."""
    ok, detail = _run_cli_logout([CODEX_BIN, "logout"])
    return ok, "codex_logout", detail


def _logout_grok() -> tuple:
    """`grok logout`. Login follow-up: device-auth / API key."""
    ok, detail = _run_cli_logout([GROK_BIN, "logout"])
    return ok, "grok_logout", detail


_LOGOUT_FN = {
    "agy": _logout_agy,
    "claude": _logout_claude,
    "codex": _logout_codex,
    "grok": _logout_grok,
}


def logout(provider: str) -> dict:
    """Log out one CLI provider. Never returns token values.

    Returns dict with keys:
      ok, provider, email_before, method, detail, error (on failure).
    Caller should recycle owned agent processes for this provider (especially
    agy — see A30) and then refresh via snapshot().
    """
    if provider not in PROVIDERS:
        return {
            "ok": False,
            "provider": provider,
            "email_before": None,
            "method": None,
            "error": f"unknown provider (want one of {', '.join(PROVIDERS)})",
        }
    email_before = current_email(provider)
    try:
        ok, method, detail = _LOGOUT_FN[provider]()
    except Exception as e:
        return {
            "ok": False,
            "provider": provider,
            "email_before": email_before,
            "method": None,
            "error": f"{type(e).__name__}: {e}",
        }
    out = {
        "ok": bool(ok),
        "provider": provider,
        "email_before": email_before,
        "method": method,
        "detail": detail,
    }
    if not ok:
        out["error"] = detail or "logout failed"
    # Drop observed email so the next login is a clean change window.
    if ok:
        with _state_lock:
            state = _load_state()
            cur = state.get(provider) or {}
            if cur.get("email"):
                cur["changed_from"] = cur["email"]
                cur["change_window"] = [cur.get("seen_at", time.time()), time.time()]
                cur.pop("email", None)
                state[provider] = cur
                _save_state(state)
        if provider == "claude":
            _invalidate_claude_cache()
    return out



# ------------------------------------------------------------------ profiles
# Saved agy logins (one token file per Google account) so the operator can swap accounts without a new OAuth
# login. Profile files hold live tokens: 0600 in a 0700 directory, and no token value ever leaves this module.

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")
_PROFILE_PROVIDERS = ("agy",)


def _profiles_dir() -> Path:
    AGY_PROFILES_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return AGY_PROFILES_DIR


def _token_email(path: Path) -> Optional[str]:
    """The account a token file belongs to (id_token email claim), or None when unreadable or not file-safe."""
    d, _mtime, err = _read_json(path)
    email = _jwt_claims((d or {}).get("id_token") or "").get("email") if not err and isinstance(d, dict) else None
    return email if isinstance(email, str) and _EMAIL_RE.match(email) and not email.startswith(".") else None


def _write_private(dest: Path, data: bytes) -> None:
    """Atomic 0600 write: a temp file beside `dest`, then os.replace -- a reader never sees half a token."""
    tmp = dest.with_name(f".{dest.name}.tmp-{os.getpid()}")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _adopt_backups() -> None:
    """Fold logout backups (AGY_TOKEN.bak-<ts>) into profiles: a backup newer than the saved profile of its account
    becomes that profile; every readable backup is then kept under tokens/bak/ (archived, never deleted)."""
    for bak in sorted(AGY_TOKEN.parent.glob(AGY_TOKEN.name + ".bak-*")):
        email = _token_email(bak)
        if not email:
            continue
        dest = _profiles_dir() / f"{email}.json"
        if not dest.exists() or dest.stat().st_mtime < bak.stat().st_mtime:
            _write_private(dest, bak.read_bytes())
        archive = _profiles_dir() / "bak"
        archive.mkdir(mode=0o700, exist_ok=True)
        os.replace(bak, archive / bak.name)


def _usage_file() -> Path:
    return _profiles_dir() / "usage.snapshots"   # not *.json: list_profiles only reads <email>.json


def usage_snapshots() -> Dict[str, dict]:
    """Last usage report seen per account: {email: {"rows": [...], "checked_at": ts}}. Quota is per account and only
    the active login can be queried, so a saved profile shows what it looked like when it was last the active one."""
    d, _mtime, err = _read_json(_usage_file())
    return d if not err and isinstance(d, dict) else {}


def save_usage_snapshot(email: Optional[str], rows: list, checked_at: float) -> None:
    if not email or not rows:
        return
    snaps = usage_snapshots()
    snaps[email] = {"rows": rows, "checked_at": checked_at}
    _write_private(_usage_file(), json.dumps(snaps).encode())


def _check_provider(provider: str) -> None:
    if provider not in _PROFILE_PROVIDERS:
        raise ValueError(f"no saved profiles for provider {provider!r} (want one of {', '.join(_PROFILE_PROVIDERS)})")


def list_profiles(provider: str = "agy") -> list:
    """Saved logins, 1-based `index` in email order (the number the CLI takes), the active one marked."""
    _check_provider(provider)
    _adopt_backups()
    active = current_email(provider)
    out = []
    for path in sorted(_profiles_dir().glob("*.json")):
        email = _token_email(path)
        if email and path.name == f"{email}.json":
            out.append({"index": len(out) + 1, "email": email, "active": email == active,
                        "saved_at": path.stat().st_mtime, "source": _short(path)})
    return out


def save_profile(provider: str = "agy") -> dict:
    """Copy the active token file to tokens/<email>.json (overwrites that account's older copy)."""
    _check_provider(provider)
    email = _token_email(AGY_TOKEN)
    if not email:
        return {"ok": False, "provider": provider, "error": "no active login with a readable email to save"}
    dest = _profiles_dir() / f"{email}.json"
    _write_private(dest, AGY_TOKEN.read_bytes())
    return {"ok": True, "provider": provider, "email": email, "source": _short(dest)}


def _find_profile(target: str, profiles: list) -> Optional[dict]:
    t = str(target).strip()
    for p in profiles:
        if (t.isdigit() and int(t) == p["index"]) or t.lower() == p["email"].lower():
            return p
    return None


def switch_profile(target: str, provider: str = "agy", owned: Optional[Dict[int, dict]] = None,
                   recycle: Optional[Callable[[set], dict]] = None) -> dict:
    """Make the saved login `target` (email or list index) the active one. The active login is saved first, so its
    newest token is never lost. Then the switch is observed (snapshot) and, given `recycle` (the server passes
    session.recycle_agents), stray CLI helpers are reaped and the owned processes now on the old login (stale_owned)
    are handed to it. A separate process (tools/switch_account.py) cannot tell the server's children from strays,
    so it does neither: the server's auto-recycle loop restarts them within its period and `stale_pids` names them."""
    _check_provider(provider)
    before = current_email(provider)
    if before:
        save_profile(provider)
    found = _find_profile(target, list_profiles(provider))
    if not found:
        return {"ok": False, "provider": provider, "email_before": before, "error": f"no saved profile {target!r}"}
    _write_private(AGY_TOKEN, (_profiles_dir() / f"{found['email']}.json").read_bytes())
    out = {"ok": True, "provider": provider, "email_before": before, "email": current_email(provider)}
    if recycle:   # in the server only: elsewhere its own children (and a live login flow) look like strays
        try:
            out["strays_killed"] = reap_stray_cli_procs(provider)
        except Exception as e:  # noqa: BLE001 -- no /proc: the swap still stands
            out["stray_error"] = f"{type(e).__name__}: {e}"
    snap = snapshot(owned, providers=(provider,))
    procs = (snap["providers"].get(provider) or {}).get("processes", [])
    out["stale_pids"] = sorted(p["pid"] for p in procs if p.get("stale"))
    out["recycle"] = recycle(stale_owned(snap)) if recycle else None
    return out
