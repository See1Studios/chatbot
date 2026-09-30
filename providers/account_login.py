"""Status-tab CLI login flows for agy / claude / codex / grok.

One pending login per provider. Uses a PTY so CLIs that insist on a TTY still
emit their OAuth / device-code prompts. Never returns token/secret values —
only URLs, user codes, and (after success) whatever accounts.snapshot already
exposes (email etc.).

Modes (user-confirmed):
  * agy:    oauth_paste  — Google OAuth URL, then paste 4/0A… code
  * claude: oauth_paste  — authorize URL, then paste browser code (like agy)
  * grok:   device_code  — `grok login --device-auth`
  * codex:  device_code  — `codex login --device-auth`
"""
from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from host_config import AGY, CLAUDE_BIN, CODEX_BIN, GROK_BIN, AGENT_PATH_PREFIX

from providers import accounts


# Codex (and some other CLIs) colorize device URL/code with CSI sequences. Those
# glue to the token (…mRRTS-A8PTV…) so word-boundary regexes miss the code, and
# URL captures keep a trailing ESC[0m. Strip before parse.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]")


def _strip_ansi(text: str) -> str:
    if not text:
        return text
    if "\x1b" in text:
        text = _ANSI_RE.sub("", text)
    # Replace other C0 controls with newline (BEL/OSC leftovers separate
    # duplicated URLs; deleting them would glue two https://… runs).
    out = []
    for ch in text:
        o = ord(ch)
        if o >= 32 or ch in "\t\n\r":
            out.append(ch)
        else:
            out.append("\n")
    return "".join(out)


def _clean_captured(s: str) -> str:
    """Strip CSI and truncate at first leftover C0; trim trailing punct."""
    if not s:
        return s
    s = _strip_ansi(s)
    for i, ch in enumerate(s):
        if ord(ch) < 32:
            s = s[:i]
            break
    return s.rstrip(").,;]'\"")


def _unwrap_wrapped_urls(text: str) -> str:
    """Join soft-wrapped long OAuth URLs (agy TUI splits across lines)."""
    if not text or "http" not in text:
        return text
    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = re.sub(
            r"(https?://\S+)[\r\n]+\s+(\S+)",
            lambda m: m.group(1) + m.group(2)
            if (not m.group(2).lower().startswith("http")
                and not m.group(2).startswith(("→", "-", "─", "Select", "Copy", "After", "Open")))
            else m.group(0),
            cur,
        )
    return cur


PROVIDERS = accounts.PROVIDERS

MODE_BY_PROVIDER = {
    "agy": "oauth_paste",
    "claude": "oauth_paste",  # browser shows code; paste into CLI (NAS has no usable localhost callback)
    "grok": "device_code",
    "codex": "device_code",
}

# ~12 min covers typical device / OAuth waits without leaving zombies forever.
LOGIN_TIMEOUT_SEC = int(os.environ.get("CHATBOT_LOGIN_TIMEOUT_SEC", "720"))
# How long start() waits for the first URL / user_code before returning pending.
BOOTSTRAP_WAIT_SEC = float(os.environ.get("CHATBOT_LOGIN_BOOTSTRAP_SEC", "12"))

_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)]+")
_USER_CODE_RE = re.compile(
    r"(?:user[_ ]?code|enter\s+(?:the\s+)?code|code\s*[:：])\s*[\"']?([A-Z0-9][-A-Z0-9]{3,})[\"']?",
    re.I,
)
_USER_CODE_FALLBACK_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4,})\b")
_VERIFY_URI_RE = re.compile(
    r"(?:verification[_ ]?(?:uri|url)|visit|open)\s*[:=]?\s*(https?://[^\s\"'<>]+)",
    re.I,
)
_LOCAL_PORT_RE = re.compile(
    r"https?://(?:127\.0\.0\.1|localhost|\[::1\])[:/](\d{2,5})",
    re.I,
)
_OAUTH_EXCHANGE_FAIL_RE = re.compile(
    r"(token exchange failed|invalid_grant|Got an error:.*token exchange|"
    r"authorization code.*(invalid|expired))",
    re.I,
)
_SUCCESS_RE = re.compile(
    r"(logged in|login successful|authentication successful|authorized successfully|"
    r"successfully logged in|you are now logged in)",
    re.I,
)
_FAIL_RE = re.compile(
    r"(login failed|authentication failed|access denied|invalid code|"
    r"authorization.*(denied|error|failed)|error:\s)",
    re.I,
)

_MESSAGE_KO = {
    "agy": (
        "브라우저에서 Google 로그인 링크를 연 뒤, 콜백 페이지에 나온 "
        "인증 코드(보통 4/0A…로 시작)를 아래에 붙여넣고 제출하세요."
    ),
    "claude": (
        "브라우저에서 인증 URL을 연 뒤, 콜백 페이지에 나온 인증 코드를 "
        "아래에 붙여넣고 제출하세요. (NAS에서는 localhost 콜백이 안 닿아서 "
        "코드 붙여넣기 방식이 필요합니다.)"
    ),
    "grok": (
        "아래 확인 코드를 복사해 verification URL을 브라우저에서 열고 "
        "코드를 입력하세요. 완료될 때까지 이 패널이 대기합니다."
    ),
    "codex": (
        "아래 확인 코드를 복사해 verification URL을 브라우저에서 열고 "
        "코드를 입력하세요. 완료될 때까지 이 패널이 대기합니다."
    ),
}


def _login_argv(provider: str) -> list:
    if provider == "agy":
        # agy 1.2.8+: no `auth login` subcommand. Bare interactive TUI shows
        # "Select login method" then Google OAuth, then paste code. Override still works.
        raw = os.environ.get("CHATBOT_AGY_LOGIN_CMD", "").strip()
        if raw:
            return raw.split()
        return [AGY]
    if provider == "claude":
        raw = os.environ.get("CHATBOT_CLAUDE_LOGIN_CMD", "").strip()
        if raw:
            return raw.split()
        return [CLAUDE_BIN, "auth", "login"]
    if provider == "grok":
        return [GROK_BIN, "login", "--device-auth"]
    if provider == "codex":
        return [CODEX_BIN, "login", "--device-auth"]
    raise ValueError(f"unknown provider: {provider}")


def _env() -> dict:
    env = os.environ.copy()
    path = env.get("PATH", "")
    if AGENT_PATH_PREFIX and AGENT_PATH_PREFIX not in path:
        env["PATH"] = AGENT_PATH_PREFIX + (":" + path if path else "")
    # Prefer non-browser where CLIs honor it; we capture the URL ourselves.
    env.setdefault("BROWSER", "echo")
    env.setdefault("NO_BROWSER", "1")
    # agy TUI needs a sized xterm-like PTY or it exits before the sign-in menu.
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLUMNS", os.environ.get("CHATBOT_LOGIN_PTY_COLS", "120"))
    env.setdefault("LINES", os.environ.get("CHATBOT_LOGIN_PTY_ROWS", "40"))
    return env


@dataclass
class _Session:
    login_id: str
    provider: str
    mode: str
    state: str = "pending"  # pending|succeeded|failed|cancelled
    authorize_url: Optional[str] = None
    user_code: Optional[str] = None
    verification_uri: Optional[str] = None
    callback_port: Optional[int] = None
    message_ko: str = ""
    error: Optional[str] = None
    expires_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    proc: Optional[subprocess.Popen] = None
    master_fd: Optional[int] = None
    output: str = ""
    last_submitted_code: Optional[str] = None
    _last_ok_check_len: int = -1
    _agy_oauth_selected: bool = False
    baseline: Optional[dict] = None     # the login before this attempt: {"ok", "email", "fp"} (LOGIN_BASELINE_v1)
    _reader_stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def public(self) -> dict:
        now = time.time()
        expires_in = max(0, int(self.expires_at - now)) if self.expires_at else None
        out = {
            "ok": True,
            "provider": self.provider,
            "mode": self.mode,
            "login_id": self.login_id,
            "state": self.state,
            "authorize_url": self.authorize_url,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "callback_port": self.callback_port,
            "message_ko": self.message_ko,
            "expires_in": expires_in,
        }
        if self.error:
            out["error"] = self.error
        return out


_lock = threading.Lock()
_sessions: Dict[str, _Session] = {}


def _pick_url(text: str, provider: str) -> Optional[str]:
    urls = _URL_RE.findall(text)
    if not urls:
        return None
    prefer = []
    if provider == "agy":
        prefer = ["accounts.google.com", "antigravity.google"]
    elif provider == "claude":
        prefer = ["claude.ai/oauth", "claude.ai/"]
    elif provider in ("grok", "codex"):
        prefer = ["verification", "device", "login", "auth"]
    for needle in prefer:
        for u in urls:
            if needle in u:
                return u.rstrip(").,;]")
    # Prefer non-localhost for authorize; keep localhost for callback note
    for u in urls:
        if "127.0.0.1" not in u and "localhost" not in u.lower():
            return u.rstrip(").,;]")
    return urls[0].rstrip(").,;]")


def _pick_verification_uri(text: str) -> Optional[str]:
    m = _VERIFY_URI_RE.search(text)
    if m:
        return m.group(1).rstrip(").,;]")
    for u in _URL_RE.findall(text):
        low = u.lower()
        if "oauth" in low or "device" in low or "activate" in low or "login" in low:
            if "127.0.0.1" not in low and "localhost" not in low:
                return u.rstrip(").,;]")
    return None


def _pick_user_code(text: str) -> Optional[str]:
    m = _USER_CODE_RE.search(text)
    if m:
        return m.group(1)
    m = _USER_CODE_FALLBACK_RE.search(text)
    if m:
        return m.group(1)
    return None


def _parse_output(sess: _Session) -> None:
    text = _unwrap_wrapped_urls(_strip_ansi(sess.output))
    url = _pick_url(text, sess.provider)
    if url:
        cleaned = _clean_captured(url)
        if not sess.authorize_url or len(cleaned) > len(sess.authorize_url):
            sess.authorize_url = cleaned
    if sess.mode == "device_code":
        if not sess.verification_uri:
            vu = _pick_verification_uri(text)
            if vu:
                sess.verification_uri = _clean_captured(vu)
        if not sess.user_code:
            sess.user_code = _pick_user_code(text)
        # Some CLIs only print one URL used as both authorize + verify
        if sess.verification_uri and not sess.authorize_url:
            sess.authorize_url = sess.verification_uri
        if sess.authorize_url and not sess.verification_uri:
            sess.verification_uri = sess.authorize_url
    if sess.mode == "oauth_callback" and sess.callback_port is None:
        m = _LOCAL_PORT_RE.search(text)
        if m:
            try:
                sess.callback_port = int(m.group(1))
            except ValueError:
                pass
            if sess.callback_port:
                tip = (
                    f" 콜백 포트 {sess.callback_port}: "
                    f"`ssh -L {sess.callback_port}:127.0.0.1:{sess.callback_port} diskstation` "
                    "후 로컬 브라우저로 인증을 마치면 됩니다."
                )
                if tip.strip() not in sess.message_ko:
                    sess.message_ko = (sess.message_ko or "") + tip

    # agy TUI: bad/expired paste shows token exchange failed while process stays alive.
    if sess.state == "pending" and _OAUTH_EXCHANGE_FAIL_RE.search(text):
        sess.state = "failed"
        m = _OAUTH_EXCHANGE_FAIL_RE.search(text)
        detail = (m.group(0) if m else "token exchange failed")[:160]
        submitted = sess.last_submitted_code
        if submitted and submitted in detail:
            detail = detail.replace(submitted, "[코드 생략]")
        sess.error = (
            f"인증 코드 교환에 실패했어요 ({detail}). "
            "새 로그인으로 다시 시도해 주세요."
        )



def _reader_loop(sess: _Session) -> None:
    fd = sess.master_fd
    if fd is None:
        return
    try:
        while not sess._reader_stop.is_set():
            try:
                r, _, _ = select.select([fd], [], [], 0.4)
            except (ValueError, OSError):
                break
            if not r:
                proc = sess.proc
                if proc is not None and proc.poll() is not None:
                    # drain once more
                    try:
                        while True:
                            chunk = os.read(fd, 4096)
                            if not chunk:
                                break
                            with sess._lock:
                                sess.output += chunk.decode("utf-8", errors="replace")
                                _parse_output(sess)
                    except OSError:
                        pass
                    break
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            with sess._lock:
                sess.output += chunk.decode("utf-8", errors="replace")
                _parse_output(sess)
                # agy 1.2.8 interactive sign-in: pick "1. Google OAuth" then wait for URL.
                if (
                    sess.provider == "agy"
                    and sess.state == "pending"
                    and not sess._agy_oauth_selected
                    and ("Google OAuth" in sess.output or "Select login method" in sess.output)
                ):
                    try:
                        os.write(fd, b"\r")
                        sess._agy_oauth_selected = True
                    except OSError:
                        pass
                if sess.state == "pending" and _SUCCESS_RE.search(sess.output[-2000:]):
                    # Soft signal; still confirm via accounts snapshot in watcher
                    pass
                if sess.state == "pending" and _FAIL_RE.search(sess.output[-2000:]):
                    # Don't fail immediately on partial "error:" in URLs; require process exit too
                    pass
    finally:
        pass


def _account_fn(provider: str):
    return {
        "agy": accounts.agy_account,
        "claude": accounts.claude_account,
        "codex": accounts.codex_account,
        "grok": accounts.grok_account,
    }.get(provider)


def _login_state(provider: str) -> dict:
    try:
        info = _account_fn(provider)() if _account_fn(provider) else {}
    except Exception:
        info = {}
    return {"ok": bool(info.get("ok")), "email": info.get("email"), "fp": accounts.login_fingerprint(provider)}


def _changed(base: Optional[dict], now: dict) -> Optional[bool]:
    """Did a new login land since `base`? True / False, or None when the provider leaves no way to tell a
    same-account re-login from nothing (then only the login CLI exiting says it is done)."""
    if not now.get("ok"):
        return False
    if not base or not base.get("ok") or base.get("email") != now.get("email"):
        return True
    if base.get("fp") and now.get("fp"):
        return base["fp"] != now["fp"]
    return None


def _account_ok(provider: str, sess: Optional["_Session"] = None, exited: bool = False) -> bool:
    """The attempt succeeded: a NEW login is in place. The login that was already there when the attempt started
    does not count (a switch without logging out first would otherwise "succeed" at once and kill the login).
    When the CLI has exited, a same-account re-login the provider cannot tell apart counts too."""
    try:
        fn = _account_fn(provider)
        if not fn:
            return False
        if provider == "claude":
            # Bypassing the TTL cache is only worth it when there's a concrete
            # reason the state might just have changed -- new PTY output since the
            # last time we forced a read -- instead of on every ~1s poll tick,
            # which defeated the cache with up to ~700 extra subprocess spawns
            # over one pending login's lifetime.
            if sess is None:
                accounts._invalidate_claude_cache()
            else:
                cur_len = len(sess.output or "")
                if cur_len != sess._last_ok_check_len:
                    accounts._invalidate_claude_cache()
                    sess._last_ok_check_len = cur_len
        info = fn()
        if not info.get("ok"):
            return False
        if sess is None:
            return True
        changed = _changed(sess.baseline, {"ok": True, "email": info.get("email"),
                                           "fp": accounts.login_fingerprint(provider)})
        return changed is True or (exited and changed is None)
    except Exception:
        return False


def _watcher_loop(sess: _Session) -> None:
    """Poll until success / process exit / timeout."""
    while True:
        with sess._lock:
            if sess.state not in ("pending",):
                return
            if time.time() >= sess.expires_at:
                sess.state = "failed"
                sess.error = "로그인 대기 시간이 초과됐어요."
                _kill_proc(sess)
                return
            proc = sess.proc
        # Success via auth files / claude status
        if _account_ok(sess.provider, sess):
            with sess._lock:
                if sess.state == "pending":
                    sess.state = "succeeded"
                    sess.message_ko = "로그인됐어요. 계정 정보를 새로고침합니다."
                    sess.error = None
            _on_success(sess.provider)
            # Let the CLI exit on its own briefly, then reap
            time.sleep(0.5)
            _kill_proc(sess)
            return
        if proc is not None:
            rc = proc.poll()
            if rc is not None:
                # Process ended — check account once more
                time.sleep(0.4)
                if _account_ok(sess.provider, sess, exited=True):
                    with sess._lock:
                        sess.state = "succeeded"
                        sess.message_ko = "로그인됐어요. 계정 정보를 새로고침합니다."
                    _on_success(sess.provider)
                else:
                    with sess._lock:
                        if sess.state == "pending":
                            sess.state = "failed"
                            tail = (sess.output or "").strip().splitlines()
                            detail = tail[-1][:200] if tail else f"exit {rc}"
                            # PTYs echo written input back into this same output buffer, so a
                            # code the user just pasted via complete() can land here as the
                            # tail line -- never let that real, possibly still-valid one-time
                            # code leave this process in an error message.
                            submitted = sess.last_submitted_code
                            if submitted and submitted in detail:
                                detail = detail.replace(submitted, "[코드 생략]")
                            sess.error = f"로그인 프로세스가 끝났지만 계정이 확인되지 않았어요 ({detail})."
                _close_fd(sess)
                return
        time.sleep(1.0)


def _on_success(provider: str) -> None:
    try:
        if provider == "claude":
            accounts._invalidate_claude_cache()
    except Exception:
        pass


def _reap_after_success(sess: _Session) -> None:
    time.sleep(0.5)   # let the CLI finish writing its token file
    _kill_proc(sess)


def _close_fd(sess: _Session) -> None:
    fd = sess.master_fd
    sess.master_fd = None
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


def _kill_proc(sess: _Session) -> None:
    sess._reader_stop.set()
    proc = sess.proc
    sess.proc = None
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    _close_fd(sess)


def _spawn(sess: _Session) -> None:
    argv = _login_argv(sess.provider)
    try:
        import pty                   # POSIX only: imported here so the server itself starts on Windows (pp/D)
    except ImportError:
        sess.state = "failed"
        sess.error = "terminal login needs a POSIX pty; not available on this OS yet (platform-portability pp/E)"
        return
    master, slave = pty.openpty()
    try:
        import fcntl
        import struct
        import termios
        rows = int(os.environ.get("CHATBOT_LOGIN_PTY_ROWS", "40"))
        cols = int(os.environ.get("CHATBOT_LOGIN_PTY_COLS", "120"))
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass
    try:
        proc = subprocess.Popen(
            argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=_env(),
            close_fds=True,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        os.close(master)
        os.close(slave)
        sess.state = "failed"
        sess.error = f"CLI를 찾을 수 없어요: {e}"
        return
    except Exception as e:
        os.close(master)
        os.close(slave)
        sess.state = "failed"
        sess.error = f"{type(e).__name__}: {e}"
        return
    os.close(slave)
    sess.proc = proc
    sess.master_fd = master
    threading.Thread(target=_reader_loop, args=(sess,), daemon=True, name=f"login-r-{sess.provider}").start()
    threading.Thread(target=_watcher_loop, args=(sess,), daemon=True, name=f"login-w-{sess.provider}").start()


def _wait_bootstrap(sess: _Session, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        with sess._lock:
            if sess.state != "pending":
                return
            if sess.mode == "oauth_paste" and sess.authorize_url:
                return
            if sess.mode == "oauth_callback" and sess.authorize_url:
                return
            if sess.mode == "device_code" and (sess.user_code or sess.verification_uri or sess.authorize_url):
                return
        time.sleep(0.25)


def active_pid(provider: str) -> Optional[int]:
    """pid of the login process this module is currently tracking for `provider`,
    if any. accounts.reap_stray_cli_procs uses this so it never kills a login it
    is actively managing just because the cmdline also matches its "helper" scan."""
    with _lock:
        sess = _sessions.get(provider)
        return sess.proc.pid if sess and sess.proc else None


def cancel(provider: str, login_id: Optional[str] = None) -> dict:
    if provider not in PROVIDERS:
        return {"ok": False, "provider": provider, "error": f"unknown provider (want one of {', '.join(PROVIDERS)})"}
    with _lock:
        sess = _sessions.get(provider)
        if not sess:
            return {"ok": True, "provider": provider, "state": "idle", "message_ko": "진행 중인 로그인이 없어요."}
        if login_id and sess.login_id != login_id:
            return {"ok": False, "provider": provider, "error": "login_id mismatch", "state": sess.state}
        sess.state = "cancelled"
        sess.error = "사용자가 취소했어요."
        _sessions.pop(provider, None)
    # Once popped, no other code path can reach this sess via _sessions -- the
    # process-kill sequence (SIGTERM/wait/SIGKILL, up to ~6s for a slow CLI) is safe
    # outside _lock, so it never blocks an unrelated provider's status()/start() poll.
    _kill_proc(sess)
    return {"ok": True, "provider": provider, "state": "cancelled", "message_ko": "로그인을 취소했어요."}


def start(provider: str) -> dict:
    if provider not in PROVIDERS:
        return {
            "ok": False,
            "provider": provider,
            "error": f"unknown provider (want one of {', '.join(PROVIDERS)})",
        }
    # Starting again cancels previous
    cancel(provider)
    mode = MODE_BY_PROVIDER[provider]
    sess = _Session(
        login_id=uuid.uuid4().hex[:12],
        provider=provider,
        mode=mode,
        message_ko=_MESSAGE_KO.get(provider, "안내에 따라 로그인을 완료하세요."),
        expires_at=time.time() + LOGIN_TIMEOUT_SEC,
        baseline=_login_state(provider),
    )
    with _lock:
        _sessions[provider] = sess
    _spawn(sess)
    if sess.state == "failed":
        with _lock:
            _sessions.pop(provider, None)
        return {**sess.public(), "ok": False}
    _wait_bootstrap(sess, BOOTSTRAP_WAIT_SEC)
    pub = sess.public()
    # Still pending without URL is ok — client will poll status
    return pub


def complete(provider: str, code: str, login_id: Optional[str] = None) -> dict:
    """Submit paste-code for oauth_paste (agy). Other modes usually self-complete."""
    if provider not in PROVIDERS:
        return {"ok": False, "provider": provider, "error": f"unknown provider (want one of {', '.join(PROVIDERS)})"}
    code = (code or "").strip()
    if not code:
        return {"ok": False, "provider": provider, "error": "code required"}
    with _lock:
        sess = _sessions.get(provider)
        if not sess or sess.state != "pending":
            return {"ok": False, "provider": provider, "error": "진행 중인 로그인이 없어요.", "state": "idle"}
        if login_id and sess.login_id != login_id:
            return {"ok": False, "provider": provider, "error": "login_id mismatch"}
        if sess.mode != "oauth_paste":
            return {
                **sess.public(),
                "ok": True,
                "message_ko": "이 방식은 브라우저에서 끝나면 자동으로 완료돼요. 코드 제출은 필요 없어요.",
            }
        fd = sess.master_fd
        proc = sess.proc
    if fd is None or proc is None or proc.poll() is not None:
        return {"ok": False, "provider": provider, "error": "로그인 프로세스가 없어요. 다시 시작해 주세요."}
    try:
        # agy 1.2.8 TUI code field submits on CR (\r), not LF (\n). LF only
        # inserts characters and never starts token exchange — UI looks dead.
        os.write(fd, (code + "\r").encode("utf-8"))
        sess.last_submitted_code = code
    except OSError as e:
        return {"ok": False, "provider": provider, "error": f"코드 전달 실패: {e}"}
    # Wait a bit for CLI to accept / exchange
    for _ in range(40):
        with sess._lock:
            _parse_output(sess)
            if sess.state == "failed":
                return {**sess.public(), "ok": False}
        if _account_ok(provider, sess):
            with _lock:
                if sess.state == "pending":
                    sess.state = "succeeded"
                    sess.message_ko = "로그인됐어요."
            _on_success(provider)
            # The watcher stops at once when the state leaves "pending", so the CLI is ours to end: an
            # interactive login (agy's TUI) never exits by itself and would keep the token in memory.
            threading.Thread(target=_reap_after_success, args=(sess,), daemon=True,
                             name=f"login-reap-{provider}").start()
            return {**sess.public(), "ok": True}
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    # Still pending — client should keep polling status
    with sess._lock:
        pub = sess.public()
    if pub.get("state") == "failed":
        return {**pub, "ok": False}
    return {**pub, "ok": True, "message_ko": "코드를 전달했어요. 완료 확인 중…"}


def status(provider: str, login_id: Optional[str] = None) -> dict:
    if provider not in PROVIDERS:
        return {"ok": False, "provider": provider, "state": "idle",
                "error": f"unknown provider (want one of {', '.join(PROVIDERS)})"}
    with _lock:
        sess = _sessions.get(provider)
        if not sess:
            return {"ok": True, "provider": provider, "state": "idle"}
        # A poller that already has a login_id (start()'s response gave it one) is
        # asking about ITS attempt specifically. If start() was called again for
        # this provider meanwhile, _sessions[provider] now holds a different
        # session -- surface that as a mismatch instead of silently handing back
        # the new attempt's authorize_url/user_code as if it were the caller's own.
        if login_id and sess.login_id != login_id:
            return {"ok": False, "provider": provider, "error": "login_id mismatch", "state": "superseded",
                    "message_ko": "다른 곳에서 새 로그인을 시작해서 이 시도는 대체됐어요."}
        # Expire cleanup
        if sess.state == "pending" and time.time() >= sess.expires_at:
            sess.state = "failed"
            sess.error = "로그인 대기 시간이 초과됐어요."
            _kill_proc(sess)
        pub = sess.public()
        if sess.state in ("succeeded", "failed", "cancelled"):
            # Keep one poll readable, then drop
            dead = sess
        else:
            dead = None
    if dead is not None and dead.state != "pending":
        # Leave succeeded/failed available until next start/cancel; client may poll once more
        pass
    return pub


def idle_all() -> None:
    """Test helper: cancel everything."""
    for p in list(PROVIDERS):
        cancel(p)

