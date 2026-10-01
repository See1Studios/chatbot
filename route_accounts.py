"""Provider accounts over HTTP (monolith-split split/B, moved from server.py): usage reports with their cache, CLI
login, logout, and restarting the idle owned processes still on an old login (by hand and every AUTO_RECYCLE_EVERY_SEC).
Routes are listed in server.py's tables."""
from __future__ import annotations

import os
import time
from typing import Dict, Optional

import obslog
from host_config import DEFAULT_PROVIDER
from providers import account_login, accounts
from providers.adapters import AGENT_ADAPTERS, get_adapter
from route_table import JSON, Req, json_bytes
from session import owned_agent_procs, recycle_agents

_USAGE_CACHE: Dict[str, dict] = {}  # provider id -> {"ts": float, "data": dict}
USAGE_CACHE_TTL_SEC = 300


def _invalidate_usage_cache(provider: Optional[str] = None) -> None:
    """Drop cached usage so the next Status-tab fetch re-queries the CLI."""
    if provider is None:
        _USAGE_CACHE.clear()
    else:
        _USAGE_CACHE.pop(provider, None)


def _get_usage(provider: str = DEFAULT_PROVIDER, force: bool = False) -> dict:
    """Generic provider-dispatching + caching wrapper (Multi-Provider plan
    Phase 0.5) -- the actual one-shot rate-limit call is
    `<adapter>.rate_limit_report()`, which is None for a provider that has no
    such thing. Cached per provider since each
    check is a real subprocess/network round-trip, not free.

    The cache is also tied to the ACCOUNT: quota is per account and accounts get
    rotated when one runs out, so a report cached for the previous login must not
    be served after a switch (it used to be, for up to USAGE_CACHE_TTL_SEC).
    Unknown account (None: logged out, unreadable, or no account concept) never
    invalidates -- that keeps the old per-provider behaviour.

    USAGE_v1 (2026-09-22): failures are NOT long-cached (auth often settles a
    moment after CLI login); one short retry covers the race. Success still
    caches for USAGE_CACHE_TTL_SEC."""
    if provider not in AGENT_ADAPTERS:
        raise ValueError(f"unknown provider: {provider!r}")
    now = time.time()
    email = accounts.current_email(provider)
    cached = _USAGE_CACHE.get(provider)
    switched = bool(email and cached and cached.get("email") and cached["email"] != email)
    if not force and cached and not switched and (now - cached["ts"] < USAGE_CACHE_TTL_SEC):
        # Never serve a cached failure for long — Status "첫 조회 실패" after login.
        if cached["data"].get("ok") or cached["data"].get("supported") is False:
            return cached["data"]
        if now - cached["ts"] < 8:
            return cached["data"]
    def _once():
        report = get_adapter(provider).rate_limit_report()
        ts = time.time()
        if report is None:
            data = {
                "ok": False,
                "supported": False,
                "error": "이 프로바이더는 사용량 조회를 지원하지 않습니다",
                "checked_at": ts,
            }
        elif "error" in report:
            data = {"ok": False, "supported": True, "error": report["error"], "checked_at": ts}
        else:
            data = {"ok": True, "supported": True, "rows": report.get("rows", []), "checked_at": ts}
        data["account"] = email
        return data
    data = _once()
    if (not data.get("ok")) and data.get("supported") is not False:
        # Auth settle / cold CLI after login — one retry after a brief wait.
        time.sleep(1.2)
        data = _once()
        if data.get("ok"):
            data["retried"] = True
    if data.get("ok") or data.get("supported") is False:
        _USAGE_CACHE[provider] = {"ts": time.time(), "data": data, "email": email}
    else:
        # Keep a short negative cache so a hammered Status tab doesn't fork CLIs.
        _USAGE_CACHE[provider] = {"ts": time.time(), "data": data, "email": email}
    return data


# Auto-recycle (2026-09-19): after the operator logs agy into another account
# (quota ran out -> rotate), chatbot-owned agy processes still hold the OLD
# login. Idle ones are stopped so the next message respawns them (same
# --conversation, so context is kept) under the new login -- the same
# transition the 15-minute idle reaper already performs. Busy sessions are never
# touched; external processes are never touched. A delegated worker still on the
# old login is stopped and its runner runs the step again (ACCOUNT_SWITCH_v1).
# CHATBOT_AUTO_RECYCLE=0 turns it off (the status-tab button still works).
AUTO_RECYCLE_ENABLED = os.environ.get("CHATBOT_AUTO_RECYCLE", "1") != "0"
AUTO_RECYCLE_EVERY_SEC = 30
_AUTO_RECYCLE = {"enabled": AUTO_RECYCLE_ENABLED, "last_at": None, "last_count": 0, "total": 0}


def _recycle_after_login(provider: str, result: dict) -> dict:
    """After a login change, restart the idle owned processes of a provider that keeps its login in
    the running process (accounts.RECYCLE_ON_LOGIN). Others: result unchanged."""
    if provider not in accounts.RECYCLE_ON_LOGIN:
        return result
    try:
        snap = accounts.snapshot(owned_agent_procs(), providers=(provider,))
        pids = accounts.owned_pids(snap, provider)
        if pids:
            result = {**result, "recycle": recycle_agents(pids)}
    except Exception as e:
        result = {**result, "recycle_error": f"{type(e).__name__}: {e}"}
    return result


def _auto_recycle_once() -> int:
    snap = accounts.snapshot(owned_agent_procs(), providers=accounts.RECYCLE_ON_LOGIN)
    stale, workers = accounts.stale_owned(snap), accounts.stale_workers(snap)
    if not (stale or workers):
        return 0
    result = {**recycle_agents(stale), "workers_stopped": accounts.stop_workers(workers)}   # ACCOUNT_SWITCH_v1
    n = len(result["recycled"]) + len(result["workers_stopped"])
    if n:
        _AUTO_RECYCLE.update(last_at=time.time(), last_count=n, total=_AUTO_RECYCLE["total"] + n)
        obslog.event("agent.recycle", lvl="warn", msg="agy login changed; restarted idle owned processes",
                     recycled=result["recycled"], skipped_busy=result["skipped_busy"],
                     workers_stopped=result["workers_stopped"])
    return n


def _auto_recycle_loop() -> None:
    while True:
        time.sleep(AUTO_RECYCLE_EVERY_SEC)
        try:
            _auto_recycle_once()
        except Exception:
            obslog.exception("agent.recycle_failed")


# ------------------------------------------------------------------------------------------------ routes

def usage(req: Req):
    force = req.q("force", "0") == "1"
    provider = req.q("provider", DEFAULT_PROVIDER)
    try:
        data = _get_usage(provider=provider, force=force)
        code, body = json_bytes(data)
    except ValueError as e:
        code, body = json_bytes({"ok": False, "error": str(e)}, 400)
    return req.send(code, body, JSON)


def login_status(req: Req):
    # ACCOUNTS_LOGIN_v1
    provider = (req.q("provider", None) or "").strip()
    login_id = (req.q("login_id", None) or "").strip() or None
    result = account_login.status(provider, login_id=login_id)
    if (
        result.get("ok")
        and result.get("state") == "succeeded"
        and not result.get("recycle")
    ):
        result = _recycle_after_login(provider, result)
    return req.json(result, 200 if result.get("ok") else 400)


def listing(req: Req):
    wanted = accounts.parse_providers(req.q("provider", None))
    return req.json({**accounts.snapshot(owned_agent_procs(), providers=wanted), "auto_recycle": dict(_AUTO_RECYCLE)})


def recycle(req: Req):
    # Stale set is recomputed server-side and limited to processes
    # this server owns -- the client cannot name pids, and external
    # processes (e.g. an SSH agy session) are never touched.
    snap = accounts.snapshot(owned_agent_procs(), providers=accounts.RECYCLE_ON_LOGIN)
    return req.json({"ok": True, **recycle_agents(accounts.stale_owned(snap)),
                     "workers_stopped": accounts.stop_workers(accounts.stale_workers(snap))})


def login_start(req: Req):
    # ACCOUNTS_LOGIN_v1 — start CLI login (one pending per provider).
    provider = str(req.body.get("provider") or "").strip()
    result = account_login.start(provider)
    http = 200 if result.get("ok") else 400
    if result.get("error") and "unknown provider" in str(result.get("error")):
        http = 400
    return req.json(result, http)


def login_complete(req: Req):
    body = req.body
    provider = str(body.get("provider") or "").strip()
    login_id = str(body.get("login_id") or "").strip() or None
    code_val = str(body.get("code") or "")
    result = account_login.complete(provider, code_val, login_id=login_id)
    http = 200 if result.get("ok") else 400
    if result.get("ok") and result.get("state") == "succeeded":
        _invalidate_usage_cache(provider)
    # On success, a provider whose processes keep their login gets its idle owned ones restarted (A30)
    if result.get("ok") and result.get("state") == "succeeded":
        result = _recycle_after_login(provider, result)
    return req.json(result, http)


def login_cancel(req: Req):
    provider = str(req.body.get("provider") or "").strip()
    login_id = str(req.body.get("login_id") or "").strip() or None
    result = account_login.cancel(provider, login_id=login_id)
    http = 200 if result.get("ok") else 400
    try:
        stray = accounts.reap_stray_cli_procs(provider)
        if stray:
            result = {**result, "strays_killed": stray}
    except Exception as e:
        result = {**result, "stray_error": f"{type(e).__name__}: {e}"}
    return req.json(result, http)


def logout(req: Req):
    # One provider at a time. Body: {"provider": "agy"|"claude"|"codex"|"grok"}.
    # Never returns token values. After logout, recycle owned procs of
    # that provider so in-memory refresh tokens cannot rewrite auth
    # files (agy A30); busy ones are skipped by recycle_agents and
    # called out in the response.
    provider = str(req.body.get("provider") or "").strip()
    result = accounts.logout(provider)
    if not result.get("ok") and result.get("method") is None and "unknown provider" in str(result.get("error") or ""):
        return req.json(result, 400)
    _invalidate_usage_cache(provider)
    owned = owned_agent_procs()
    wanted = accounts.parse_providers(provider)
    snap = accounts.snapshot(owned, providers=wanted)
    pids = accounts.owned_pids(snap, provider) if provider in accounts.PROVIDERS else set()
    recycled = recycle_agents(pids) if pids else {"recycled": [], "skipped_busy": []}
    # CODEX_PROC_v1: also reap login/app-server/usage strays (node wrapper
    # may leave a native child with ppid=1 after terminate-without-killpg).
    try:
        stray = accounts.reap_stray_cli_procs(provider)
        if stray:
            recycled = {**recycled, "strays_killed": stray}
    except Exception as e:
        recycled = {**recycled, "stray_error": f"{type(e).__name__}: {e}"}
    note = None
    if recycled.get("skipped_busy"):
        note = (
            "로그아웃은 반영됐지만 작업 중인 소유 프로세스 "
            f"{len(recycled['skipped_busy'])}개는 재시작하지 못했어요. "
            "턴이 끝난 뒤 프로세스 재시작(또는 다시 로그아웃)을 눌러 주세요."
        )
    elif result.get("ok") and accounts.LOGOUT_NOTES.get(provider):
        note = accounts.LOGOUT_NOTES[provider]
    payload = {
        **result,
        "providers": snap.get("providers") or {},
        "checked_at": snap.get("checked_at"),
        "recycle": recycled,
    }
    if note:
        payload["note"] = note
        payload["message_ko"] = note
    # Prefer logout ok; if logout failed, surface that status.
    return req.json(payload, 200 if result.get("ok") else 400)
