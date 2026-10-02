#!/usr/bin/env python3
"""Chat HTTP host (:3011). Entry: Handler + main, and the route tables (GET_ROUTES … DELETE_ROUTES): every endpoint
is one row there, in match order. Handlers live by domain: route_sessions.py, route_accounts.py, route_files.py, the
host's own below; route_table.py matches (monolith-split split/B). Other siblings: see the code map in AGENTS.md.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import unquote, urlparse

from providers.adapters import AGENT_ADAPTERS, PROVIDER_META
from host_config import (
    DATA,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    HOME,
    HOST,
    MCP_PORT,
    MODELS,
    PORT,
    ROOT,
    WEB_ROOT,
    WORKSPACE,
    _now,
)
from session import REG, _atomic_write_text, _standby_maintenance_loop, owned_agent_procs
from providers import accounts
from providers import account_login
import art_manager
import room_chat
import card_upload
import chat_upload
import platform_compat
import items
import character_art
import obslog
import evolution
import identity
import origin_guard
import push_manager
import route_accounts
import route_files
import route_sessions
import route_table
import static_delivery
from route_accounts import _AUTO_RECYCLE, AUTO_RECYCLE_ENABLED, _auto_recycle_loop
from route_table import NEXT, Req, json_bytes as _json_bytes

try:  # worktree delegation (work cards, [맡겨]/[병합·⚡]); the page still loads without it
    from delegation import delegation_api
except Exception:  # noqa: BLE001
    obslog.exception("delegation.unavailable")
    delegation_api = lambda method, path, body: None  # noqa: E731


_SKILLS_CACHE = {"ts": 0.0, "data": []}

from preview_guard import (
    _HOME_R,
    _PREVIEW_ALLOWED_ROOTS,
    _PREVIEW_HOME_DOC_SUFFIXES,
    _SECRET_NAME_RE,
    _preview_allowed,
    _resolve_safe_preview_file,
)
import client_errors  # page errors -> the host log (#424)
import personal_turn  # PERSONAL_TURN_v1: its GET route
from workspace_status import (
    experts_api,
    instructions_api,
    observation_api,
    ticket_api,
    WS_SKILLS_DIR,
    _SKILLS_CACHE,
    _extract_yaml_desc,
    _get_available_skills,
    _get_workspace_skills,
    _popular_slash_skills,
    _hooks_config_path,
    _mcp_config_path,
    _read_hooks_config,
    _read_mcp_config,
    _self_status,
    _skill_desc,
    _write_mcp_config,
)


def _schedule_host_defibrillate() -> None:
    """Fire-and-forget host CPR. Caller must finish HTTP response first — repair restarts this process."""
    def _run() -> None:
        time.sleep(0.7)
        ticket = DATA / "host-force.ticket"
        try:
            platform_compat.write_text(ticket, f"v1 defibrillate {int(time.time())} api\n", encoding="utf-8")
            ticket.chmod(0o600)
        except Exception:
            pass
        env = dict(os.environ)
        env["CHATBOT_FORCE_HOST"] = "1"
        env["CHATBOT_CALLER"] = "api-defibrillate"
        obslog.event("host.defibrillate", lvl="warn", msg="repair requested over HTTP (FAB / POST /api/host/defibrillate)")
        try:
            # Must run in an independent session (setsid + start_new_session=True)
            # so when 'repair' kills server.py, the repair script itself isn't terminated.
            subprocess.Popen(
                ["setsid", "bash", str(ROOT / "chatbot-ctl.sh"), "repair"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


# Successful GETs of these are UI polling: counted in http.summary, never written one by one.
_OBS_STREAM_SUFFIX = "/events"


class Handler(obslog.HTTPLogMixin, BaseHTTPRequestHandler):
    """Access/exception logging comes from obslog.HTTPLogMixin (docs/LOGGING.md): every request
    is timed and counted; errors, slow and mutating requests are written one by one."""
    server_version = "Chatbot/1.0"

    def _obs_path(self, raw: str) -> str:
        return self._normalize_req_path(raw)

    def _obs_stream(self, method: str, path: str) -> bool:
        return path.endswith(_OBS_STREAM_SUFFIX)

    def _cors(self) -> None:
        # Only pages on this machine (e.g. the hub on another port) may read our
        # responses; other sites get no CORS headers, so browsers block them.
        origin = self.headers.get("Origin")
        if origin_guard.cors_allowed(origin, self.headers.get("Host")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, body: bytes, content_type: str, cache_control: str = "no-store",
              etag: str = "", encoding: str = "") -> None:
        # STATIC_DELIVERY_v1 (static_delivery.py): a revalidating client gets 304 with no body, and a
        # gzip-capable one gets the body compressed. ETag is opt-in per call; JSON API bodies are
        # gzipped for a client that asks (API_GZIP_v1: the page's session sync, 20-30 KB each).
        if etag and static_delivery.if_none_match(self.headers.get("If-None-Match"), etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache_control)
            self.send_header("Vary", "Accept-Encoding")
            self.end_headers()
            return
        if not encoding and content_type.startswith("application/json"):
            encoding = static_delivery.negotiate(self.headers.get("Accept-Encoding"), content_type, len(body))
        if encoding:
            body = static_delivery.compress(body)
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        if etag:
            self.send_header("ETag", etag)
            self.send_header("Vary", "Accept-Encoding")
        if encoding:
            self.send_header("Content-Encoding", encoding)
            if not etag:
                self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def _normalize_req_path(self, raw_path: str) -> str:
        """Strip proxy mount prefixes (e.g. /chat or X-Forwarded-Prefix) dynamically so routes work anywhere."""
        p = raw_path
        fwd_prefix = (self.headers.get("X-Forwarded-Prefix") or "").strip().rstrip("/")
        if fwd_prefix and p.startswith(fwd_prefix):
            p = p[len(fwd_prefix):] or "/"
        if p.startswith("/chat/"):
            p = p[5:]  # preserve leading slash e.g. /chat/api/... -> /api/...
        elif p == "/chat":
            p = "/"
        return p

    def do_GET(self) -> None:
        try:
            self._do_GET()
        except ValueError as e:
            code, body = _json_bytes({"ok": False, "error": str(e)}, 400)
            self._send(code, body, "application/json; charset=utf-8")
        except FileNotFoundError as e:
            code, body = _json_bytes({"ok": False, "error": str(e)}, 404)
            self._send(code, body, "application/json; charset=utf-8")
        except OSError as e:
            code, body = _json_bytes({"ok": False, "error": str(e)}, 500)
            self._send(code, body, "application/json; charset=utf-8")
        except Exception as e:
            code, body = _json_bytes({"ok": False, "error": str(e)}, 500)
            self._send(code, body, "application/json; charset=utf-8")

    def _do_GET(self) -> None:
        parsed = urlparse(self.path)
        route_table.dispatch(GET_ROUTES, Req(self, self._normalize_req_path(parsed.path), parsed.query))

    def _read_json(self) -> dict:
        ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct and ct != "application/json":
            raise ValueError(f"unsupported Content-Type: {ct!r} (expected application/json)")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("invalid Content-Length")
        if n < 0 or n > 200_000:
            err = ValueError("payload too large")
            err.status_code = 413
            raise err
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        req = Req(self, self._normalize_req_path(parsed.path), parsed.query)
        # Same-origin gate: every mutating POST must come from a page served by this server. Requiring Content-Type:
        # application/json (_read_json) already forces a CORS preflight for browser clients; this check is defence in
        # depth for non-browser callers that forge Origin. It covers the operator's own calls too (closing
        # observations, deciding tickets, letting delegated work land, restarting the host).
        if not origin_guard.same_origin(
            self.headers.get("Origin"),
            self.headers.get("Host"),
            self.headers.get("Sec-Fetch-Site"),
        ):
            return req.json({"ok": False, "error": "same-origin browser request required"}, 403)
        if route_table.dispatch(POST_STREAM_ROUTES, req):   # they read the request body themselves
            return None
        try:
            req.body = self._read_json()
        except Exception as e:
            return req.json({"ok": False, "error": str(e)}, getattr(e, "status_code", 400))
        try:
            if route_table.dispatch(POST_ROUTES, req):
                return None
        except Exception as e:
            # A route that fails answers 500 with the error; OBSLOG_v1: HTTPLogMixin records the traceback
            # (http.error) for this and every other method's catch-all.
            return req.json({"ok": False, "error": str(e)}, 500)
        req.json({"ok": False, "error": "not found"}, 404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        req = Req(self, parsed.path, parsed.query)
        try:
            req.body = self._read_json()
        except Exception as e:
            return req.json({"ok": False, "error": str(e)}, 400)
        try:
            if route_table.dispatch(PUT_ROUTES, req):
                return None
        except Exception as e:
            return req.json({"ok": False, "error": str(e)}, 500)
        req.json({"ok": False, "error": "not found"}, 404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        req = Req(self, parsed.path, parsed.query)
        try:
            if route_table.dispatch(DELETE_ROUTES, req):
                return None
        except Exception as e:
            return req.json({"ok": False, "error": str(e)}, 500)
        req.json({"ok": False, "error": "not found"}, 404)


# ------------------------------------------------------------------------------------------------ host routes

def _healthz(req: Req):
    avail = _provider_availability()
    return req.json({
        "ok": any(avail.values()),
        "providers": avail,  # PROVIDER_NEUTRAL_v1: every provider, none singled out
        "default_provider": DEFAULT_PROVIDER,
        "default_model": DEFAULT_MODEL,
        "class": "NAS agent (VibeCat-class)",
        "skip_permissions": True,
        "mcp_port": MCP_PORT,
        "boot_ts": BOOT_INFO["boot_ts"],
        "static": _static_fingerprint(),   # ASSET_RELOAD_v1: a restart with new page code reloads open pages
    })


def _static_fingerprint() -> str:
    from host_config import STATIC
    try:
        return static_delivery.fingerprint(STATIC)
    except OSError:
        return ""


def _host_status(req: Req):
    return req.json({
        "ok": True,
        "chat": True,  # we answered, so chat is up
        "boot_ts": BOOT_INFO["boot_ts"],
        "label_ko": "엔진 리부트",
        "hint_ko": "연결이 죽었거나 응답이 안 올 때 호스트를 재기동합니다. 몇 초 끊겼다가 다시 붙습니다.",
    })


def _providers(req: Req):
    # Multi-Provider plan, frontend selector: per-provider model
    # list + install-detected availability, theme keycolor, portrait
    # A provider is a vendor, not the persona: the persona/title come from the
    # instruction files (identity.py) and never appear in this catalog.
    providers = []
    for pid, adapter in AGENT_ADAPTERS.items():
        meta = dict(PROVIDER_META.get(pid) or {})
        extra = getattr(adapter, "meta", None) or {}
        if isinstance(extra, dict):
            meta.update({k: extra[k] for k in ("name", "role", "theme", "icon") if extra.get(k)})
        providers.append({
            "id": pid,
            "available": adapter.available(),
            "login": pid in account_login.MODE_BY_PROVIDER,  # has a CLI login the page can drive
            "models": adapter.known_models(),
            "default_model": (adapter.known_models()[0] if adapter.known_models() else ""),
            "name": meta.get("name", pid),
            "role": meta.get("role", "AI Provider"),
            "theme": meta.get("theme", "lime"),
            "icon": meta.get("icon", f"/chat/providers/{pid}.webp"),
        })
    return req.json({"providers": providers, "default": DEFAULT_PROVIDER})


def _commands(req: Req):
    skills = _get_available_skills()
    commands = [
        {"name": "/btw", "label": "샛길 질문", "desc": "작업 중 즉시 경량 샛길 답변", "template": "/btw "},
        {"name": "/private on", "label": "사적 대화 켜기", "desc": "♥ 사적 대화 세션으로 전환 (업무와 분리)", "template": "/private on"},
        {"name": "/private off", "label": "사적 대화 끄기", "desc": "업무 대화 세션으로 복귀", "template": "/private off"},
        {"name": "/continue", "label": "이어하기", "desc": "현재 대화 맥락 인계 새 세션", "template": "/continue"},
        {"name": "/new", "label": "새 세션", "desc": "완전한 새 대화 세션 시작", "template": "/new"},
        {"name": "/defib", "label": "엔진 리부트", "desc": "엔진 리부트 (repair/reboot)", "template": "/defib"},
        {"name": "/status", "label": "상태 확인", "desc": "챗봇 및 NAS 시스템 상태 확인", "template": "/status"},
        {"name": "/clear", "label": "화면 비우기", "desc": "대화창 화면 로그 초기화", "template": "/clear"},
        {"name": "/compact", "label": "세션 압축", "desc": "대화 히스토리 수동 압축/요약", "template": "/compact"},
        {"name": "/help", "label": "사용법", "desc": "탭·단축키·슬래시 명령어 요약", "template": "/help"},
    ]
    popular = _popular_slash_skills()
    return req.json({"ok": True, "commands": commands, "popular": popular, "skills": skills},
                    cache_control="public, max-age=300")


def _mcp_list(req: Req):
    cfg = _read_mcp_config()
    return req.json({"ok": True, "mcpServers": cfg.get("mcpServers", {})})


def _mcp_add(req: Req):
    name = str(req.body.get("name") or "").strip()
    url = str(req.body.get("serverUrl") or "").strip()
    if not name or not url:
        return req.json({"ok": False, "error": "name and serverUrl required"}, 400)
    cfg = _read_mcp_config()
    cfg.setdefault("mcpServers", {})[name] = {"serverUrl": url, "disabled": False}
    _write_mcp_config(cfg)
    return req.json({"ok": True, "mcpServers": cfg["mcpServers"]})


def _mcp_delete(req: Req):
    name = unquote(req.arg)
    if name == "nas":
        return req.json({"ok": False, "error": "nas MCP는 코어 — 삭제 불가"}, 400)
    cfg = _read_mcp_config()
    if name in cfg.get("mcpServers", {}):
        del cfg["mcpServers"][name]
        _write_mcp_config(cfg)
        return req.json({"ok": True, "mcpServers": cfg["mcpServers"]})
    return req.json({"ok": False, "error": "not found"}, 404)


def _skill_toggle(req: Req):
    name = unquote(req.arg)
    enabled_dir = WS_SKILLS_DIR / name
    disabled_dir = WS_SKILLS_DIR / ("_" + name)
    if enabled_dir.is_dir():
        enabled_dir.rename(disabled_dir)
        new_state = False
    elif disabled_dir.is_dir():
        disabled_dir.rename(enabled_dir)
        new_state = True
    else:
        return req.json({"ok": False, "error": "skill not found"}, 404)
    return req.json({"ok": True, "name": name, "enabled": new_state})


def _defibrillate(req: Req):
    # Restarts the host: only this server's own UI may ask (the POST same-origin gate). This does not stop a
    # non-browser client that forges Origin (the API has no login). Respond first, then schedule repair
    # (kills/restarts this server).
    req.json({
        "ok": True,
        "scheduled": True,
        "message_ko": "엔진 리부트 예약됨. 호스트가 재기동됩니다. 잠시 후 자동으로 다시 연결합니다.",
    })
    _schedule_host_defibrillate()


def _operator_only(req: Req):
    # Editing what the agent reads is the operator's: this server's own page only.
    if not origin_guard.same_origin(req.headers.get("Origin"), req.headers.get("Host"), req.headers.get("Sec-Fetch-Site")):
        return req.json({"ok": False, "error": "same-origin browser request required"}, 403)
    routed = instructions_api("PUT", req.path, req.body) or experts_api("PUT", req.path, req.body)
    return req.json(routed[1], routed[0])


def _push(method: str):
    return lambda req: None if push_manager.dispatch_push_api(req.h, method, req.path) else NEXT


def _art(req: Req):
    art = character_art.handle(req.path, req.qs())   # ART_PLACEHOLDER_v1: avatar, stage, sprites
    if not art:
        return NEXT
    return req.send(art[0], art[1], art[2], cache_control=art[3])


def _card_import(req: Req):
    status, payload = card_upload.handle(req.headers, req.rfile, WORKSPACE)
    return req.json(payload, status)


# ------------------------------------------------------------------------------------------------ route tables
# One table per method, tried in order; the first route that takes a request answers it (route_table.py).
# Order matters where patterns overlap: "/api/sessions/*" (one session) comes after its longer cousins.

_api, _gift = route_table.api, route_table.gift

GET_ROUTES = [
    (("/healthz", "/health"), _healthz),
    (None, _push("GET")),
    ("/api/host/status", _host_status),
    ("/api/identity", lambda req: req.json(identity.get_identity())),
    ("/api/models", lambda req: req.json({"models": MODELS, "default": DEFAULT_MODEL})),
    ("/api/providers", _providers),
    (("/api/skills", "/api/commands"), _commands),
    ("/api/self-status", lambda req: req.json(_self_status())),
    (None, _api(observation_api, "GET")),
    (None, _api(ticket_api, "GET")),
    (None, _api(delegation_api, "GET")),
    (None, _api(instructions_api, "GET")),
    (None, _api(experts_api, "GET")),
    (None, _api(personal_turn.api, "GET")),
    (None, _api(room_chat.api, "GET")),
    ("/api/mcp", _mcp_list),
    ("/api/usage", route_accounts.usage),
    ("/api/accounts/login/status", route_accounts.login_status),
    ("/api/accounts", route_accounts.listing),
    ("/api/sessions", route_sessions.listing),
    ("/api/characters", route_sessions.characters_list),
    (None, _gift(lambda req: items.handle_get(req.path))),
    (None, _gift(lambda req: chat_upload.handle_get(req.path, req.qs()))),
    (None, _gift(lambda req: art_manager.handle_get(req.path))),
    (None, _art),
    ("/api/sessions/busy", route_sessions.busy),
    ("/api/sessions/active", route_sessions.active),
    ("/api/sessions/caller", route_sessions.caller),
    ("/api/office/notify", route_sessions.office_notify),
    ("/api/office/opened", route_sessions.office_opened),
    ("/api/office", route_sessions.office),
    ("/api/sessions/*/events", route_sessions.events),
    ("/api/sessions/*/artifacts", route_sessions.artifacts),
    ("/api/service-log", lambda req: req.json(_service_log(req.q("since", "24h"), req.q("sid", "")))),
    ("/api/sessions/*/log", route_sessions.log),
    ("/api/sessions/*/summary", route_sessions.summary),
    ("/api/artifacts", route_files.artifacts_all),
    ("/api/file/preview", route_files.preview),
    ("/api/file/raw", route_files.raw),
    ("/api/sessions/*", route_sessions.detail),
    ("/artifacts/*", route_files.artifact),
    (("/chat/persona/*", "/persona/*"), route_files.persona),
    (None, route_files.static),
]

POST_STREAM_ROUTES = [   # before the JSON body is read
    ("/api/characters/import", _card_import),
    (None, _push("POST")),
    (None, _gift(lambda req: chat_upload.handle(req.path, req.headers, req.rfile))),
    (None, _gift(lambda req: art_manager.handle_upload(req.path, req.headers, req.rfile))),
]

POST_ROUTES = [
    ("/api/skills/*/toggle", _skill_toggle),
    ("/api/mcp", _mcp_add),
    (("/api/observations*", "/api/tickets*", "/api/delegations*", "/api/rooms*", client_errors.PATH + "*"),
     route_table.first(_api(observation_api, "POST"), _api(ticket_api, "POST"), _api(delegation_api, "POST"),
                       _api(room_chat.api, "POST"), _api(client_errors.api, "POST"))),
    ("/api/host/defibrillate", _defibrillate),
    ("/api/accounts/recycle", route_accounts.recycle),
    ("/api/accounts/login/start", route_accounts.login_start),
    ("/api/accounts/login/complete", route_accounts.login_complete),
    ("/api/accounts/login/cancel", route_accounts.login_cancel),
    ("/api/accounts/logout", route_accounts.logout),
    ("/api/sessions", route_sessions.create),
    ("/api/characters/*/session", route_sessions.character_session),
    ("/api/sessions/*/message", route_sessions.message),
    (None, _gift(lambda req: items.handle_post(req.path, req.body))),   # items (plus/F)
    (None, _gift(lambda req: art_manager.handle_post(req.path, req.body))),   # art (am/B)
    ("/api/sessions/*/provider", route_sessions.provider),
    ("/api/sessions/*/continue", route_sessions.continue_),
    ("/api/sessions/*/stop", route_sessions.stop),
    ("/api/sessions/*/discard", route_sessions.discard),
]

PUT_ROUTES = [   # PUT and DELETE match the path as sent (no mount-prefix stripping), as before split/B
    (("/api/instructions/*", "/api/experts/*"), _operator_only),
]

DELETE_ROUTES = [
    ("/api/mcp/*", _mcp_delete),
    ("/api/sessions/*", route_sessions.delete),
]


# Service log for the UI (로그 탭 → 서비스): logdigest over logs/events.jsonl (docs/LOGGING.md).
SERVICE_LOG_EVENTS = 200
SERVICE_LOG_TTL_SEC = 10
_SERVICE_LOG_CACHE: Dict[tuple, tuple] = {}
# info events that still belong in the service view: restarts, repairs, probes
_SERVICE_LOG_INFO_EVTS = ("proc.start", "proc.exit", "repair.", "doctor.", "ctl.", "host.", "agent.recycle")


def _trim_event(e: dict) -> dict:
    e = {k: v for k, v in e.items() if k not in ("_t", "routes")}
    err = e.get("err")
    if isinstance(err, dict) and isinstance(err.get("trace"), str):
        e["err"] = dict(err, trace=err["trace"][-2000:])
    return e


def _service_log(since: str, sid: str = "") -> dict:
    import logdigest
    if not re.fullmatch(r"\d{1,4}[smhd]", since or ""):
        raise ValueError("since: N[s|m|h|d]")
    if sid and not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", sid):
        raise ValueError("bad sid")
    key = (since, sid)
    hit = _SERVICE_LOG_CACHE.get(key)
    if hit and time.time() - hit[0] < SERVICE_LOG_TTL_SEC:
        return hit[1]
    since_s = logdigest.parse_since(since)
    since_t = time.time() - since_s
    if sid:
        events = logdigest.session_timeline(sid, since_t)
    else:
        events = [e for e in logdigest.read_events(since_t)
                  if isinstance(e, dict) and (e.get("lvl") in ("warn", "error") or str(e.get("evt", "")).startswith(_SERVICE_LOG_INFO_EVTS))]
    events = [_trim_event(e) for e in events if isinstance(e, dict)][-SERVICE_LOG_EVENTS:][::-1]
    d = logdigest.digest(since_s)
    d["errors"] = [dict(g, sample_trace=(g.get("sample_trace") or "")[-1500:] or None)
                   for g in d.get("errors") or [] if isinstance(g, dict)]  # a malformed group must not 500 the tab
    out = {"ok": True, "log_exists": logdigest.LOG.exists(), "since": since, "sid": sid or None,
           "digest": {k: d.get(k) for k in ("status", "window", "findings", "processes", "errors", "turns", "ops", "mcp", "counts")},
           "events": events}
    _SERVICE_LOG_CACHE.clear()
    _SERVICE_LOG_CACHE[key] = (time.time(), out)
    return out


# HOST_SIGNALS_v1.1: log findings -> observation candidates, from inside the service (the operator:
# doctor, the watchdog, must not run service code). logdigest throttles itself to once an hour.
HOST_SIGNAL_CHECK_SEC = 300


def _host_signal_tick() -> int:
    import logdigest
    if obslog.configured():
        logdigest.LOG = obslog._state["path"]
        logdigest.HOST_SIGNAL_STAMP = logdigest.LOG.with_name(".host-signals.stamp")
    logdigest.OBS_ROOT = WORKSPACE / "skill-observations"
    got = logdigest.host_candidates()
    if got:
        obslog.event("evolution.host_candidates", count=len(got), signals=sorted({g["signal"] for g in got}))
    return len(got)


def _host_signal_loop() -> None:
    while True:
        time.sleep(HOST_SIGNAL_CHECK_SEC)
        try:
            _host_signal_tick()
        except Exception:
            obslog.exception("evolution.host_candidates_failed", dedup="loop")


def _provider_availability() -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    for pid, adapter in AGENT_ADAPTERS.items():
        try:
            out[pid] = bool(adapter.available())
        except Exception:
            out[pid] = False
    return out


BOOT_INFO: Dict[str, Any] = {"boot_ts": 0.0, "head": "", "landed": []}  # set once by _record_boot() in main()
LANDED_MAX = 10


def _git(*args: str) -> str:
    """Run git in the service repo; any failure is "" (never blocks boot)."""
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _landed(old: str, new: str) -> list:
    """One-line subjects of the commits between the previous boot's HEAD and this one (newest first, capped)."""
    if not old or not new or old == new:
        return []
    out = _git("log", "--format=%s", "-n", str(LANDED_MAX), "%s..%s" % (old, new))
    return [ln for ln in out.splitlines() if ln.strip()][:LANDED_MAX]


def _record_boot(state: Path = None) -> Dict[str, Any]:
    """Note this boot's time and HEAD, diff against the previous boot's HEAD, and remember this one for next time."""
    state = state or DATA / "last_boot.json"
    head = _git("rev-parse", "HEAD")
    try:
        old = str((json.loads(state.read_text(encoding="utf-8")) or {}).get("head") or "")
    except Exception:
        old = ""
    BOOT_INFO.update(boot_ts=time.time(), head=head, landed=_landed(old, head))
    try:
        _atomic_write_text(state, json.dumps({"ts": BOOT_INFO["boot_ts"], "head": head}))
    except Exception as e:  # noqa: BLE001
        obslog.event("boot.state_write_failed", lvl="warn", error=str(e))
    import session as _session_mod
    _session_mod.boot_notice = _turn_notices
    try:
        import events
        events.publish("host.restart", events.ALL, ts=BOOT_INFO["boot_ts"], head=head, landed=BOOT_INFO["landed"])
    except Exception as e:  # noqa: BLE001
        obslog.event("events.publish_failed", lvl="warn", error=str(e))
    return BOOT_INFO


def _turn_notices(sess) -> str:
    """Lines before the user's message (session.boot_notice hook) from the event mailbox (evt/B): what came for this
    session's character since it last read; a first read gets the restart and the open work, not the history. A work
    session also gets its unread dialogs (inbox/C)."""
    import events
    sid, character = str(getattr(sess, "sid", "") or ""), getattr(sess, "character", "") or ""
    channel = "private" if getattr(sess, "is_private", False) else "work"
    try:
        first = events.cursor(sid) is None
        got = [] if first else events.pending(sid, character, channel)
        restarted = first or any(e["type"] == "host.restart" for e in got)   # the text is this boot's (BOOT_INFO)
        notes = [_restart_line(BOOT_INFO) if restarted and BOOT_INFO.get("boot_ts") else ""]
        if channel == "work":
            import delegation
            notes.append(delegation.work_note(character, {})[0] if first else delegation.work_event_note(got, character))
        events.mark(sid, max([e["id"] for e in got] + [events.last_id() if first else 0]))
    except Exception as e:  # noqa: BLE001 -- a note is a courtesy; the turn goes on without it
        obslog.event("events.deliver_failed", lvl="warn", error=str(e))
        return ""
    if channel == "work" and (getattr(sess, "mode", "work") or "work") == "work":   # not room seats, not private
        try:   # what coworkers said to this brain, delivered (unified-message-inbox inbox/C, H)
            import dialog_log
            notes.append(dialog_log.turn_note(character, sid, sess.__dict__.setdefault("_dialog_noted", {}),
                                              bool(sess.__dict__.pop("_handed_over", False))))
        except Exception as e:  # noqa: BLE001
            obslog.event("dialog.note_failed", lvl="warn", error=str(e)[:200])
    return "\n\n".join(n for n in notes if n)


def _restart_line(p: Dict[str, Any]) -> str:
    landed = " · ".join(p.get("landed") or []) or "새 커밋 없음"
    return "[시스템 안내] 호스트가 %s에 재기동됨 (HEAD %s). 반영: %s" % (
        time.strftime("%H:%M", time.localtime(p.get("boot_ts") or 0)), (p.get("head") or "?")[:7], landed)


def _obs_heartbeat() -> Dict[str, Any]:
    """Merged into every proc.heartbeat (obslog, every 5 min)."""
    with REG.lock:
        sessions = list(REG.sessions.values())
    busy = [s.sid for s in sessions if getattr(s, "busy", False)]
    return {
        "sessions": len(sessions),
        "busy": busy[:10],
        "subscribers": sum(len(getattr(s, "subscribers", []) or []) for s in sessions),
        "agent_procs": len(owned_agent_procs()),
        "auto_recycle_total": _AUTO_RECYCLE["total"],
    }


def main() -> None:
    avail = _provider_availability()
    if not any(avail.values()):  # still start: status pages and accounts must stay reachable
        obslog.event("providers.none_available", lvl="error", providers=avail)
    elif not avail.get(DEFAULT_PROVIDER):
        obslog.event("providers.default_unavailable", lvl="warn", default=DEFAULT_PROVIDER, providers=avail)
    seeded = identity.seed_workspace_files()
    try:
        import session as _session_mod
        moved = _session_mod.migrate_session_characters()
        if moved:
            print("sessions: %d old session(s) now name the default character" % moved, flush=True)
    except Exception as e:  # noqa: BLE001
        print("sessions: character migration failed: %s" % e, flush=True)
    obslog.start_process("chat", host=HOST, port=PORT, default_model=DEFAULT_MODEL, default_provider=DEFAULT_PROVIDER)
    _record_boot()   # after the log is configured: its host.restart event is mirrored there (evt/B)
    obslog.add_heartbeat(_obs_heartbeat)
    if seeded:
        obslog.event("workspace.seeded", files=seeded)
    httpd = platform_compat.http_server((HOST, PORT), Handler)   # exclusive port on Windows (#409)
    httpd.daemon_threads = True
    threading.Thread(target=_standby_maintenance_loop, daemon=True).start()
    threading.Thread(target=accounts.watch_loop, daemon=True).start()
    if AUTO_RECYCLE_ENABLED:
        threading.Thread(target=_auto_recycle_loop, daemon=True).start()
    threading.Thread(target=_host_signal_loop, name="host-signals", daemon=True).start()
    import delegation
    threading.Thread(target=delegation.queue_loop, name="delegation-queue", daemon=True).start()   # LEASE_SCOPE_v1
    threading.Thread(target=__import__("event_react").loop, args=(REG,), name="event-react", daemon=True).start()   # evt/D
    print(f"chatbot on http://{HOST}:{PORT} (VibeCat-class NAS)", flush=True)

    def _stop(signum=None, *_a):
        obslog.stop_process("signal %s" % signum)
        try:
            httpd.server_close()
        except Exception:
            pass
        os._exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

