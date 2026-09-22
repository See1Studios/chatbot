#!/usr/bin/env python3
"""Chat HTTP host (:3011). Entry: Handler + main.

Siblings (see data/workspace/PROJECT.md Where to edit):
  host_config.py  paths/env
  adapters.py     AGENT_ADAPTERS
  session.py      AgySession / REG  (ctl guard AST-scans this)
  tool_format.py  tool log lines
"""
from __future__ import annotations

import json
import mimetypes
mimetypes.add_type("image/webp", ".webp")
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, quote, unquote, urlparse

from adapters import AGENT_ADAPTERS, get_adapter
from host_config import (
    AGY,
    DATA,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    HOME,
    HOST,
    MCP_PORT,
    MODELS,
    PORT,
    ROOT,
    STATIC,
    WEB_ROOT,
    WORKSPACE,
    _now,
)
from session import (
    REG,
    AgySession,
    _atomic_write_text,
    _safe_artifact_rel,
    _safe_session_id,
    _standby_maintenance_loop,
    owned_agent_procs,
    recycle_agents,
)
import accounts
import evolution
import identity
import origin_guard

def _json_bytes(obj: Any, code: int = 200):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return code, raw


_SKILLS_CACHE = {"ts": 0.0, "data": []}
_USAGE_CACHE: Dict[str, dict] = {}  # provider id -> {"ts": float, "data": dict}
USAGE_CACHE_TTL_SEC = 300


def _get_usage(provider: str = "agy", force: bool = False) -> dict:
    """Generic provider-dispatching + caching wrapper (Multi-Provider plan
    Phase 0.5) -- the actual one-shot rate-limit call is
    `<adapter>.rate_limit_report()`, which is None for a provider that has no
    such thing. Cached per provider since each
    check is a real subprocess/network round-trip, not free.

    The cache is also tied to the ACCOUNT: quota is per account and accounts get
    rotated when one runs out, so a report cached for the previous login must not
    be served after a switch (it used to be, for up to USAGE_CACHE_TTL_SEC).
    Unknown account (None: logged out, unreadable, or no account concept) never
    invalidates -- that keeps the old per-provider behaviour."""
    if provider not in AGENT_ADAPTERS:
        raise ValueError(f"unknown provider: {provider!r}")
    now = time.time()
    email = accounts.current_email(provider)
    cached = _USAGE_CACHE.get(provider)
    switched = bool(email and cached and cached.get("email") and cached["email"] != email)
    if not force and cached and not switched and (now - cached["ts"] < USAGE_CACHE_TTL_SEC):
        return cached["data"]
    report = get_adapter(provider).rate_limit_report()
    if report is None:
        data = {
            "ok": False,
            "supported": False,
            "error": "이 프로바이더는 사용량 조회를 지원하지 않습니다",
            "checked_at": now,
        }
    elif "error" in report:
        data = {"ok": False, "supported": True, "error": report["error"], "checked_at": now}
    else:
        data = {"ok": True, "supported": True, "rows": report.get("rows", []), "checked_at": now}
    data["account"] = email
    _USAGE_CACHE[provider] = {"ts": now, "data": data, "email": email}
    return data


# Auto-recycle (2026-09-19): after the operator logs agy into another account
# (quota ran out -> rotate), chatbot-owned agy processes still hold the OLD
# login. Idle ones are stopped so the next message respawns them (same
# --conversation, so context is kept) under the new login -- the same
# transition the 15-minute idle reaper already performs. Busy sessions are never
# touched; external processes are never touched. CHATBOT_AUTO_RECYCLE=0 turns
# it off (the status-tab button still works).
AUTO_RECYCLE_ENABLED = os.environ.get("CHATBOT_AUTO_RECYCLE", "1") != "0"
AUTO_RECYCLE_EVERY_SEC = 30
_AUTO_RECYCLE = {"enabled": AUTO_RECYCLE_ENABLED, "last_at": None, "last_count": 0, "total": 0}


def _auto_recycle_once() -> int:
    snap = accounts.snapshot(owned_agent_procs(), providers=("agy",))
    stale = accounts.stale_owned(snap)
    if not stale:
        return 0
    result = recycle_agents(stale)
    n = len(result["recycled"])
    if n:
        _AUTO_RECYCLE.update(last_at=time.time(), last_count=n, total=_AUTO_RECYCLE["total"] + n)
        print(f"[{_now()}] auto-recycle: agy login changed, restarted {n} idle owned process(es) "
              f"{result['recycled']} (busy skipped: {result['skipped_busy']})", file=sys.stderr, flush=True)
    return n


def _auto_recycle_loop() -> None:
    while True:
        time.sleep(AUTO_RECYCLE_EVERY_SEC)
        try:
            _auto_recycle_once()
        except Exception:
            traceback.print_exc()


from preview_guard import (
    _HOME_R,
    _PREVIEW_ALLOWED_ROOTS,
    _PREVIEW_HOME_DOC_SUFFIXES,
    _SECRET_NAME_RE,
    _preview_allowed,
    _resolve_safe_preview_file,
)
from workspace_status import (
    observation_api,
    ticket_api,
    RULE_FILES,
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
    _rule_path,
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
            ticket.write_text(f"v1 defibrillate {int(time.time())} api\n", encoding="utf-8")
            ticket.chmod(0o600)
        except Exception:
            pass
        env = dict(os.environ)
        env["CHATBOT_FORCE_HOST"] = "1"
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


class Handler(BaseHTTPRequestHandler):
    server_version = "Chatbot/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        # Only pages on this machine (e.g. the hub on another port) may read our
        # responses; other sites get no CORS headers, so browsers block them.
        origin = self.headers.get("Origin")
        if origin_guard.cors_allowed(origin, self.headers.get("Host")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, body: bytes, content_type: str, cache_control: str = "no-store") -> None:
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
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
        path = self._normalize_req_path(parsed.path)
        if path in ("/healthz", "/health"):
            ok = shutil.which(AGY) is not None or Path(AGY).exists()
            code, body = _json_bytes({
                "ok": ok,
                "agy": AGY,
                "models": MODELS,
                "class": "NAS agent (VibeCat-class)",
                "skip_permissions": True,
                "mcp_port": MCP_PORT,
            })
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/host/status":
            chat_ok = False
            try:
                # ourselves — if we answer, chat is up
                chat_ok = True
            except Exception:
                chat_ok = False
            code, body = _json_bytes({
                "ok": True,
                "chat": chat_ok,
                "label_ko": "전기충격 · 심폐소생",
                "hint_ko": "연결이 죽었거나 응답이 안 올 때 호스트를 재기동합니다. 몇 초 끊겼다가 다시 붙습니다.",
            })
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/identity":
            code, body = _json_bytes(identity.get_identity())
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/models":
            code, body = _json_bytes({"models": MODELS, "default": DEFAULT_MODEL})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/providers":
            # Multi-Provider plan, frontend selector: per-provider model
            # list + install-detected availability, theme keycolor, portrait
            # A provider is a vendor, not the persona: the persona/title come from the
            # instruction files (identity.py) and never appear in this catalog.
            PROVIDER_META = {
                "agy": {"name": "Antigravity", "role": "Google Antigravity", "theme": "spark", "icon": "/chat/persona/providers/agy.webp?v=9"},
                "claude": {"name": "Claude", "role": "Anthropic AI", "theme": "amber", "icon": "/chat/persona/providers/claude.webp?v=10"},
                "grok": {"name": "Grok", "role": "xAI Explorer", "theme": "mono", "icon": "/chat/persona/providers/grok.webp?v=6"},
                "codex": {"name": "Codex", "role": "OpenAI Engine", "theme": "emerald", "icon": "/chat/persona/providers/codex.webp?v=10"},
            }
            providers = []
            for pid, adapter in AGENT_ADAPTERS.items():
                meta = dict(PROVIDER_META.get(pid) or {})
                extra = getattr(adapter, "meta", None) or {}
                if isinstance(extra, dict):
                    meta.update({k: extra[k] for k in ("name", "role", "theme", "icon") if extra.get(k)})
                providers.append({
                    "id": pid,
                    "available": adapter.available(),
                    "models": adapter.known_models(),
                    "name": meta.get("name", pid),
                    "role": meta.get("role", "AI Provider"),
                    "theme": meta.get("theme", "lime"),
                    "icon": meta.get("icon", f"/chat/persona/providers/{pid}.webp"),
                })
            code, body = _json_bytes({"providers": providers, "default": DEFAULT_PROVIDER})
            return self._send(code, body, "application/json; charset=utf-8")
        if path in ("/api/skills", "/api/commands"):
            skills = _get_available_skills()
            commands = [
                {"name": "/btw", "label": "샛길 질문", "desc": "작업 중 즉시 경량 샛길 답변", "template": "/btw "},
                {"name": "/private", "label": "사적 모드", "desc": "🔒 비밀 보장·휘발성 일상 대화 모드", "template": "/private"},
                {"name": "/continue", "label": "이어하기", "desc": "현재 대화 맥락 인계 새 세션", "template": "/continue"},
                {"name": "/new", "label": "새 세션", "desc": "완전한 새 대화 세션 시작", "template": "/new"},
                {"name": "/defib", "label": "심폐소생", "desc": "⚡ 호스트 전기충격·소생 (repair)", "template": "/defib"},
                {"name": "/status", "label": "상태 확인", "desc": "챗봇 및 NAS 시스템 상태 확인", "template": "/status"},
                {"name": "/clear", "label": "화면 비우기", "desc": "대화창 화면 로그 초기화", "template": "/clear"},
                {"name": "/compact", "label": "세션 압축", "desc": "대화 히스토리 수동 압축/요약", "template": "/compact"},
                {"name": "/help", "label": "사용법", "desc": "탭·단축키·슬래시 명령어 요약", "template": "/help"},
            ]
            popular = _popular_slash_skills()
            code, body = _json_bytes({"ok": True, "commands": commands, "popular": popular, "skills": skills})
            return self._send(code, body, "application/json; charset=utf-8", cache_control="public, max-age=300")
        if path == "/api/self-status":
            code, body = _json_bytes(_self_status())
            return self._send(code, body, "application/json; charset=utf-8")
        routed = observation_api("GET", path, None) or ticket_api("GET", path, None)
        if routed is not None:
            code, raw = _json_bytes(routed[1], routed[0])
            return self._send(code, raw, "application/json; charset=utf-8")
        if path.startswith("/api/rules/"):
            name = unquote(path[len("/api/rules/"):])
            fp = _rule_path(name)
            if not fp and name == "PRIVATE.md":
                fp = WORKSPACE / "PRIVATE.md"
            if not fp or not fp.exists():
                code, body = _json_bytes({"ok": False, "error": "not found"}, 404)
                return self._send(code, body, "application/json; charset=utf-8")
            code, body = _json_bytes({"ok": True, "name": name, "content": fp.read_text(encoding="utf-8", errors="replace")})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/mcp":
            cfg = _read_mcp_config()
            code, body = _json_bytes({"ok": True, "mcpServers": cfg.get("mcpServers", {})})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/usage":
            force = parse_qs(parsed.query).get("force", ["0"])[0] == "1"
            provider = parse_qs(parsed.query).get("provider", [DEFAULT_PROVIDER])[0]
            try:
                data = _get_usage(provider=provider, force=force)
                code, body = _json_bytes(data)
            except ValueError as e:
                code, body = _json_bytes({"ok": False, "error": str(e)}, 400)
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/accounts":
            wanted = accounts.parse_providers(parse_qs(parsed.query).get("provider", [None])[0])
            code, body = _json_bytes({**accounts.snapshot(owned_agent_procs(), providers=wanted), "auto_recycle": dict(_AUTO_RECYCLE)})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/sessions":
            code, body = _json_bytes({"sessions": REG.list()})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/sessions/active":
            sess = REG.get_active()
            pub = sess.to_public()
            pub["is_private"] = bool(getattr(sess, "is_private", False))
            code, body = _json_bytes(pub)
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/api/sessions/") and path.endswith("/events"):
            sid = path[len("/api/sessions/"):-len("/events")]
            return self._sse(sid)
        if path.startswith("/api/sessions/") and path.endswith("/artifacts"):
            sid = path[len("/api/sessions/"):-len("/artifacts")]
            sess = REG.peek(sid)
            if sess is None:
                return self._send(404, b"session not found", "text/plain")
            all_artifacts = sess.get_artifacts()  # already sorted newest-mtime-first
            qs = parse_qs(parsed.query)
            try:
                limit = max(1, min(200, int(qs.get("limit", ["60"])[0])))
            except ValueError:
                limit = 60
            before_raw = qs.get("before", [""])[0]
            page = all_artifacts
            if before_raw:
                try:
                    before = float(before_raw)
                    page = [a for a in all_artifacts if a["mtime"] < before]
                except ValueError:
                    pass
            page = page[:limit]
            next_before = page[-1]["mtime"] if len(page) == limit and len(page) < len(all_artifacts) else None
            code, body = _json_bytes({
                "artifacts": page,
                "total": len(all_artifacts),
                "next_before": next_before,
            })
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/api/sessions/") and path.endswith("/log"):
            sid = path[len("/api/sessions/"):-len("/log")]
            sess = REG.peek(sid)
            if sess is None:
                return self._send(404, b"session not found", "text/plain")
            all_events = sess.get_log()  # already sorted newest-ts-first
            qs = parse_qs(parsed.query)
            try:
                limit = max(1, min(200, int(qs.get("limit", ["60"])[0])))
            except ValueError:
                limit = 60
            before_raw = qs.get("before", [""])[0]
            page = all_events
            if before_raw:
                try:
                    before = float(before_raw)
                    page = [e for e in all_events if (e.get("ts") or 0) < before]
                except ValueError:
                    pass
            page = page[:limit]
            next_before = page[-1].get("ts") if len(page) == limit and len(page) < len(all_events) else None
            code, body = _json_bytes({
                "events": page,
                "total": len(all_events),
                "next_before": next_before,
            })
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/api/sessions/") and path.endswith("/summary"):
            # Read-only handover-style summary of an arbitrary (often archived) session,
            # for the "가져오기" scrollback/session-list action — never touches the
            # target session's own state, and never injected automatically anywhere.
            sid = path[len("/api/sessions/"):-len("/summary")]
            sess = REG.peek(sid)
            if sess is None:
                return self._send(404, b"session not found", "text/plain")
            summary = sess.get_handover_summary()
            code, body = _json_bytes({"id": sid, "summary": summary})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/artifacts":
            sess = AgySession("global")
            code, body = _json_bytes({"artifacts": sess.get_artifacts()})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/file/preview":
            raw_target = parse_qs(parsed.query).get("path", [""])[0]
            fp, reason = _resolve_safe_preview_file(raw_target)
            if not fp:
                code, body = _json_bytes({"ok": False, "error": reason or "파일을 찾을 수 없거나 접근이 거부되었습니다"}, 404)
                return self._send(code, body, "application/json; charset=utf-8")
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            stat = fp.stat()
            is_text = False
            content = None
            is_image = ctype.startswith("image/")
            raw_url = "/api/file/raw?path=" + quote(str(fp))
            if is_image:
                kind = "image"
            elif ctype.startswith("text/") or fp.suffix.lower() in (
                ".md", ".py", ".js", ".json", ".sh", ".css", ".html", ".txt", ".ts", ".jsx", ".tsx",
                ".yml", ".yaml", ".ini", ".conf", ".cfg", ".sql", ".xml", ".csv", ".log", ".env.example"
            ):
                kind = "text"
                is_text = True
                try:
                    # preview up to 500KB text
                    if stat.st_size <= 500_000:
                        content = fp.read_text(encoding="utf-8", errors="replace")
                    else:
                        content = fp.read_text(encoding="utf-8", errors="replace")[:200_000] + f"\n\n... (파일이 너무 큽니다: {stat.st_size:,} bytes, 앞부분 200KB만 표시)"
                except Exception as e:
                    content = f"내용을 읽을 수 없습니다: {e}"
            else:
                kind = "binary"

            rel_label = str(fp).replace(str(HOME), "~", 1)
            code, body = _json_bytes({
                "ok": True,
                "name": fp.name,
                "path": str(fp),
                "label": rel_label,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "mime": ctype,
                "kind": kind,
                "is_text": is_text,
                "content": content,
                "raw_url": raw_url,
            })
            return self._send(code, body, "application/json; charset=utf-8")
        # --- Role Studio API ---
        if path == "/api/roles":
            try:
                import yaml as _yaml
            except ImportError:
                code, body = _json_bytes({"ok": False, "error": "PyYAML is not installed. Run: pip install -r requirements.txt"}, 503)
                return self._send(code, body, "application/json; charset=utf-8")
            char_dir = HOME / "data" / "characters"
            roles = []
            if char_dir.is_dir():
                for yaml_path in sorted(char_dir.glob("*.yaml")):
                    try:
                        raw = _yaml.safe_load(yaml_path.read_text("utf-8")) or {}
                        slug = yaml_path.stem
                        state = raw.get("state", {})
                        # Merge saved SimCore session state if exists
                        session_dir = WORKSPACE / ".agents" / "skills" / "character-chat" / "sessions"
                        saved_state = {}
                        if session_dir.is_dir():
                            import glob as _glob
                            session_files = sorted(session_dir.glob(f"{slug}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                            if session_files:
                                try:
                                    sdata = json.loads(session_files[0].read_text("utf-8"))
                                    saved_state = sdata.get("state", {})
                                except Exception:
                                    pass
                        merged_state = {**state, **saved_state} if saved_state else state
                        roles.append({
                            "slug": slug,
                            "name": raw.get("name", slug),
                            "description": raw.get("description", ""),
                            "version": raw.get("version", "1.0.0"),
                            "state": merged_state,
                            "persona": raw.get("persona", {}),
                            "has_image": (char_dir / "images" / slug / "avatar.webp").exists()
                                         or (char_dir / "images" / slug / "avatar.png").exists(),
                        })
                    except Exception:
                        pass
            code, body = _json_bytes({"ok": True, "roles": roles})
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/api/roles/") and not path.endswith("/chat"):
            slug = path[len("/api/roles/"):].strip("/")
            if not slug or "/" in slug or ".." in slug:
                code, body = _json_bytes({"ok": False, "error": "invalid slug"}, 400)
                return self._send(code, body, "application/json; charset=utf-8")
            char_dir = HOME / "data" / "characters"
            yaml_path = char_dir / f"{slug}.yaml"
            if not yaml_path.is_file():
                code, body = _json_bytes({"ok": False, "error": "not found"}, 404)
                return self._send(code, body, "application/json; charset=utf-8")
            try:
                import yaml as _yaml
            except ImportError:
                code, body = _json_bytes({"ok": False, "error": "PyYAML is not installed. Run: pip install -r requirements.txt"}, 503)
                return self._send(code, body, "application/json; charset=utf-8")
            try:
                raw = _yaml.safe_load(yaml_path.read_text("utf-8")) or {}
                raw["slug"] = slug
                # Merge latest SimCore session state
                session_dir = WORKSPACE / ".agents" / "skills" / "character-chat" / "sessions"
                if session_dir.is_dir():
                    session_files = sorted(session_dir.glob(f"{slug}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if session_files:
                        try:
                            sdata = json.loads(session_files[0].read_text("utf-8"))
                            raw["_session"] = {
                                "id": session_files[0].stem,
                                "state": sdata.get("state", {}),
                                "turn_count": sdata.get("turn_count", 0),
                            }
                        except Exception:
                            pass
                img_dir = char_dir / "images" / slug
                image_url = None
                for ext in ("webp", "png", "jpg"):
                    p = img_dir / f"avatar.{ext}"
                    if p.exists():
                        image_url = f"/api/roles/{slug}/image"
                        break
                raw["image_url"] = image_url
                code, body = _json_bytes({"ok": True, "role": raw})
                return self._send(code, body, "application/json; charset=utf-8")
            except Exception as e:
                code, body = _json_bytes({"ok": False, "error": str(e)}, 500)
                return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/api/roles/") and path.endswith("/image"):
            slug = path[len("/api/roles/"):-len("/image")].strip("/")
            if not slug or "/" in slug or ".." in slug:
                return self._send(404, b"not found", "text/plain")
            img_dir = HOME / "data" / "characters" / "images" / slug
            for ext in ("webp", "png", "jpg"):
                p = img_dir / f"avatar.{ext}"
                if p.exists():
                    ctype = mimetypes.guess_type(str(p))[0] or "image/png"
                    return self._send(200, p.read_bytes(), ctype, cache_control="public, max-age=300")
            return self._send(404, b"no image", "text/plain")
        # --- End Role Studio API ---
        if path == "/api/file/raw":
            raw_target = parse_qs(parsed.query).get("path", [""])[0]
            fp, reason = _resolve_safe_preview_file(raw_target)
            if not fp:
                return self._send(404, (reason or "not found").encode("utf-8"), "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            try:
                data = fp.read_bytes()
                return self._send(200, data, ctype, cache_control="private, max-age=60")
            except Exception as e:
                return self._send(500, str(e).encode("utf-8"), "text/plain")
        if path.startswith("/api/sessions/"):
            sid = path.split("/")[3]
            sess = REG.peek(sid)
            if sess is None:
                code, body = _json_bytes({"ok": False, "error": "session not found"}, 404)
                return self._send(code, body, "application/json; charset=utf-8")
            full = parse_qs(parsed.query).get("full", ["0"])[0] == "1"
            out = sess.to_public()
            out["is_private"] = bool(getattr(sess, "is_private", False))
            if full:
                with sess.lock:
                    out["history"] = list(sess.history)
            code, body = _json_bytes(out)
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/artifacts/"):
            rel = path[len("/artifacts/"):]
            fp = _safe_artifact_rel(rel)
            if not fp:
                return self._send(404, b"not found", "text/plain")
            data = fp.read_bytes()
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            return self._send(200, data, ctype, cache_control="private, max-age=3600")
        # persona assets — stay inside DATA/persona (or the web-root fallback).
        # http.server does not collapse `..`; join+resolve without a root
        # check would read any file the process can open.
        if path.startswith("/chat/persona/") or path.startswith("/persona/"):
            rel_p = path[len("/chat/persona/"):] if path.startswith("/chat/persona/") else path[len("/persona/"):]
            rel_p = unquote(rel_p or "")
            parts = rel_p.split("/")
            if (
                not rel_p
                or ".." in parts
                or rel_p.startswith(("/", "\\"))
                or any(part.startswith(".") for part in parts)
            ):
                return self._send(404, b"not found", "text/plain")
            persona_root = (DATA / "persona").resolve()
            fp_p = (DATA / "persona" / rel_p).resolve()
            try:
                fp_p.relative_to(persona_root)
            except ValueError:
                fp_p = None
            if fp_p is None or not fp_p.exists() or not fp_p.is_file():
                web_persona = (WEB_ROOT / "chat" / "persona").resolve()
                fp_p = (WEB_ROOT / "chat" / "persona" / rel_p).resolve()
                try:
                    fp_p.relative_to(web_persona)
                except ValueError:
                    return self._send(404, b"not found", "text/plain")
            if fp_p.exists() and fp_p.is_file():
                data = fp_p.read_bytes()
                ctype = mimetypes.guess_type(str(fp_p))[0] or "application/octet-stream"
                return self._send(200, data, ctype, cache_control="public, max-age=60")
            return self._send(404, b"not found", "text/plain")

        # static
        rel = "index.html" if path in ("/", "/chat", "/chat/") else path.lstrip("/")
        if ".." in rel:
            return self._send(400, b"bad path", "text/plain")
        fp = STATIC / rel
        if not fp.exists() or not fp.is_file():
            return self._send(404, b"not found", "text/plain")
        data = fp.read_bytes()
        ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        if rel.endswith(".html") or rel == "index.html":
            ctype = "text/html; charset=utf-8"
            if rel == "index.html":
                # `<!--IDENTITY-->` -> the identity from this instance's instruction files.
                # Served statically (marker untouched) it is a harmless comment and app.js
                # falls back to /api/identity.
                data = data.replace(
                    b"<!--IDENTITY-->",
                    ("<script>window.__IDENTITY__=" + identity.script_json() + ";</script>").encode("utf-8"), 1)
            return self._send(200, data, ctype, cache_control="no-cache")
        elif rel.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
            return self._send(200, data, ctype, cache_control="no-cache")
        elif rel.endswith(".css"):
            ctype = "text/css; charset=utf-8"
            return self._send(200, data, ctype, cache_control="no-cache")
        elif rel.lower().endswith((".png", ".webp", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2")):
            return self._send(200, data, ctype, cache_control="public, max-age=86400")
        return self._send(200, data, ctype)

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
        path = self._normalize_req_path(parsed.path)
        # Same-origin gate: every mutating POST must come from a page served by
        # this server. Requiring Content-Type: application/json (enforced in
        # _read_json above) already forces a CORS preflight for browser clients;
        # this check is defence in depth for non-browser callers that forge Origin.
        # Exceptions: none — the existing per-route checks below are now redundant
        # but harmless; a request that reaches them has already passed here.
        if not origin_guard.same_origin(
            self.headers.get("Origin"),
            self.headers.get("Host"),
            self.headers.get("Sec-Fetch-Site"),
        ):
            code, raw = _json_bytes({"ok": False, "error": "same-origin browser request required"}, 403)
            return self._send(code, raw, "application/json; charset=utf-8")
        try:
            body = self._read_json()
        except Exception as e:
            status = getattr(e, "status_code", 400)
            code, raw = _json_bytes({"ok": False, "error": str(e)}, status)
            return self._send(code, raw, "application/json; charset=utf-8")
        try:
            # --- Role Studio POST ---
            if path == "/api/roles" or (path.startswith("/api/roles/") and not path.endswith("/chat")):
                try:
                    import yaml as _yaml
                except ImportError:
                    code, raw = _json_bytes({"ok": False, "error": "PyYAML is not installed. Run: pip install -r requirements.txt"}, 503)
                    return self._send(code, raw, "application/json; charset=utf-8")
                char_dir = HOME / "data" / "characters"
                char_dir.mkdir(parents=True, exist_ok=True)
                slug = body.get("slug", "").strip().lower().replace(" ", "_")
                if not slug or "/" in slug or ".." in slug:
                    code, raw = _json_bytes({"ok": False, "error": "invalid or missing slug"}, 400)
                    return self._send(code, raw, "application/json; charset=utf-8")
                # Build YAML dict from body
                card = {
                    "name": body.get("name", slug),
                    "version": body.get("version", "1.0.0"),
                    "description": body.get("description", ""),
                    "state": body.get("state", {
                        "affinity": 0, "stress": 0, "mood": "차분함",
                        "act": 1, "turn_count": 0, "current_location": "미정",
                    }),
                    "persona": body.get("persona", {}),
                    "guidelines": body.get("guidelines", []),
                }
                yaml_path = char_dir / f"{slug}.yaml"
                yaml_path.write_text(_yaml.dump(card, allow_unicode=True, sort_keys=False), "utf-8")
                code, raw = _json_bytes({"ok": True, "slug": slug})
                return self._send(code, raw, "application/json; charset=utf-8")
            # --- End Role Studio POST ---
            if path.startswith("/api/skills/") and path.endswith("/toggle"):
                name = unquote(path[len("/api/skills/"):-len("/toggle")])
                enabled_dir = WS_SKILLS_DIR / name
                disabled_dir = WS_SKILLS_DIR / ("_" + name)
                if enabled_dir.is_dir():
                    enabled_dir.rename(disabled_dir)
                    new_state = False
                elif disabled_dir.is_dir():
                    disabled_dir.rename(enabled_dir)
                    new_state = True
                else:
                    code, raw = _json_bytes({"ok": False, "error": "skill not found"}, 404)
                    return self._send(code, raw, "application/json; charset=utf-8")
                code, raw = _json_bytes({"ok": True, "name": name, "enabled": new_state})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path == "/api/mcp":
                name = str(body.get("name") or "").strip()
                url = str(body.get("serverUrl") or "").strip()
                if not name or not url:
                    code, raw = _json_bytes({"ok": False, "error": "name and serverUrl required"}, 400)
                    return self._send(code, raw, "application/json; charset=utf-8")
                cfg = _read_mcp_config()
                cfg.setdefault("mcpServers", {})[name] = {"serverUrl": url, "disabled": False}
                _write_mcp_config(cfg)
                code, raw = _json_bytes({"ok": True, "mcpServers": cfg["mcpServers"]})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/observations") or path.startswith("/api/tickets"):
                # Closing observations or deciding tickets is the operator's: this server's own UI only.
                if not origin_guard.same_origin(self.headers.get("Origin"), self.headers.get("Host"),
                                                self.headers.get("Sec-Fetch-Site")):
                    code, raw = _json_bytes({"ok": False, "error": "same-origin browser request required"}, 403)
                    return self._send(code, raw, "application/json; charset=utf-8")
                routed = observation_api("POST", path, body) or ticket_api("POST", path, body)
                if routed is not None:
                    code, raw = _json_bytes(routed[1], routed[0])
                    return self._send(code, raw, "application/json; charset=utf-8")
            if path == "/api/host/defibrillate":
                # Restarts the host: only this server's own UI may ask. This does not stop a
                # non-browser client that forges Origin (the API has no login).
                if not origin_guard.same_origin(self.headers.get("Origin"), self.headers.get("Host"),
                                                self.headers.get("Sec-Fetch-Site")):
                    code, raw = _json_bytes({"ok": False, "error": "same-origin browser request required"}, 403)
                    return self._send(code, raw, "application/json; charset=utf-8")
                # Respond first, then schedule repair (kills/restarts this server).
                code, raw = _json_bytes({
                    "ok": True,
                    "scheduled": True,
                    "message_ko": "전기충격(심폐소생) 예약됨. 호스트가 재기동됩니다. 잠시 후 자동으로 다시 연결합니다.",
                })
                self._send(code, raw, "application/json; charset=utf-8")
                _schedule_host_defibrillate()
                return
            if path == "/api/accounts/recycle":
                # Stale set is recomputed server-side and limited to processes
                # this server owns -- the client cannot name pids, and external
                # processes (e.g. an SSH agy session) are never touched.
                stale = accounts.stale_owned(accounts.snapshot(owned_agent_procs(), providers=("agy",)))
                code, raw = _json_bytes({"ok": True, **recycle_agents(stale)})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path == "/api/sessions":
                provider = str(body.get("provider") or DEFAULT_PROVIDER)
                # DEFAULT_MODEL names an agy/Gemini model -- meaningless as a
                # fallback for any other provider, whose own adapter already
                # treats an empty model as "let the CLI use its own default"
                # (verified live for claude: omitting --model just used its
                # account default, claude-sonnet-5).
                default_model = DEFAULT_MODEL if provider == DEFAULT_PROVIDER else ""
                sess = REG.create(
                    model=str(body.get("model") or default_model),
                    effort=str(body.get("effort") or ""),
                    provider=provider,
                )
                code, raw = _json_bytes({"ok": True, "session": sess.to_public()})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/sessions/") and path.endswith("/message"):
                sid = path[len("/api/sessions/"):-len("/message")]
                sess = REG.get(sid)
                sess.maybe_swap_provider(str(body.get("provider") or ""))
                sess.maybe_swap_model(str(body.get("model") or ""))
                text = str(body.get("text") or body.get("message") or "")
                client_mid = str(body.get("client_mid") or "")
                client_ctx = body.get("client_context")
                if not isinstance(client_ctx, dict):
                    client_ctx = None

                stripped = text.strip()
                if stripped in ("/private", "/private on"):
                    sess.is_private = True
                    priv_file = WORKSPACE / "PRIVATE.md"
                    priv_rules = priv_file.read_text(encoding="utf-8", errors="replace") if priv_file.exists() else ""
                    text = (
                        "[시스템: 사적 모드(Private Mode) 활성화]\n"
                        "이 대화는 완전 휘발성이며 영구 기억(MEMORY.md)/관찰/도구 호출이 차단됩니다.\n"
                        "아래 PRIVATE.md 규칙(진짜 카톡 같은 자연스러운 구어체, 1~2줄, 냥체 배제, 지문 배제)을 엄격히 준수하세요.\n"
                        f"---\n{priv_rules}\n---\n"
                        f"{identity.user_title()}이 사적 모드(/private)에 들어왔습니다. 자연스럽고 편안한 일상 구어체(1~2줄)로 맞이하세요."
                    )
                elif stripped in ("/work", "/private off"):
                    sess.is_private = False
                    text = (
                        "[시스템: 업무 모드(Work Mode) 복귀]\n"
                        "사적 모드가 해제되고 기본 업무 모드로 복귀했습니다.\n"
                        f"{identity.self_label()} 기본 페르소나(친근한 냥체, 업무 도구 활용)로 복귀하세요.\n"
                        f"{identity.user_title()}이 업무 모드로 복귀했습니다."
                    )
                elif getattr(sess, "is_private", False):
                    text = f"[사적 모드: No Logging, No Tools, 일상 구어체 반말 1~2줄]\n{text}"

                try:
                    rotated = sess.send(text, client_mid, client_context=client_ctx)
                except Exception as e:
                    # skill-observations 0011 (2026-09-17): this route
                    # intermittently 500'd on a brand-new session's first
                    # message with no traceback anywhere to root-cause from
                    # -- the generic do_POST catch-all only ever returned
                    # str(e). Log the real traceback (lands in
                    # logs/chatbot.log) and, like /stop already does via
                    # to_public()'s debug_stderr_tail, surface the spawned
                    # agy process's own recent stderr in the error body
                    # itself so the *next* occurrence is diagnosable without
                    # a second round-trip to GET the session.
                    print(f"[{_now()}] EXCEPTION in POST /message sid={sid}:", file=sys.stderr)
                    traceback.print_exc()
                    err: Dict[str, Any] = {"ok": False, "error": str(e)}
                    tail = getattr(sess, "_stderr_tail", None)
                    if tail:
                        err["debug_stderr_tail"] = tail[-15:]
                    code, raw = _json_bytes(err, 500)
                    return self._send(code, raw, "application/json; charset=utf-8")
                
                target_sess = rotated or sess
                pub = target_sess.to_public()
                pub["is_private"] = bool(getattr(sess, "is_private", False))
                if rotated is not None:
                    code, raw = _json_bytes({
                        "ok": True,
                        "rotated": True,
                        "old_session_id": sid,
                        "session": pub,
                        "handoff_summary": getattr(rotated, "handoff_summary", ""),
                    })
                else:
                    code, raw = _json_bytes({"ok": True, "session": pub})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/sessions/") and path.endswith("/provider"):
                sid = path[len("/api/sessions/"):-len("/provider")]
                sess = REG.get(sid)
                new_p = str(body.get("provider") or "").strip()
                if new_p:
                    sess.maybe_swap_provider(new_p)
                new_m = str(body.get("model") or "").strip()
                if new_m:
                    sess.maybe_swap_model(new_m)
                code, raw = _json_bytes({"ok": True, "session": sess.to_public()})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/sessions/") and path.endswith("/continue"):
                sid = path[len("/api/sessions/"):-len("/continue")]
                sess = REG.get(sid)
                result = sess.continue_to_successor(str(body.get("model") or ""), bool(body.get("sticky")))
                code, raw = _json_bytes({
                    "ok": True,
                    "session": result["new_sess"].to_public(),
                    "old_session_id": sid,
                    "summary": result["summary"],
                    "reused": result["reused"],
                })
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/sessions/") and path.endswith("/stop"):
                sid = path[len("/api/sessions/"):-len("/stop")]
                sess = REG.get(sid)
                sess.stop()
                code, raw = _json_bytes({"ok": True, "session": sess.to_public()})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/sessions/") and path.endswith("/discard"):
                # Doctor/probe throwaway: stop agy and drop from in-memory registry (meta kept).
                sid = path[len("/api/sessions/"):-len("/discard")]
                sess = REG.get(sid)
                sess.stop(notify=False)
                with REG.lock:
                    REG.sessions.pop(sid, None)
                code, raw = _json_bytes({"ok": True, "discarded": sid})
                return self._send(code, raw, "application/json; charset=utf-8")
        except Exception as e:
            # Same rationale as the /message route's own try/except above:
            # this catch-all used to be the only thing standing between an
            # unhandled exception and a bare {"ok": false, "error": str(e)}
            # body -- no traceback landed anywhere, so any other POST route
            # that fails this way is just as undiagnosable as 0011 was.
            # Print it here too (goes to logs/chatbot.log) rather than
            # adding a try/except to every branch above.
            print(f"[{_now()}] EXCEPTION in POST {path}:", file=sys.stderr)
            traceback.print_exc()
            code, raw = _json_bytes({"ok": False, "error": str(e)}, 500)
            return self._send(code, raw, "application/json; charset=utf-8")
        code, raw = _json_bytes({"ok": False, "error": "not found"}, 404)
        self._send(code, raw, "application/json; charset=utf-8")

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json()
        except Exception as e:
            code, raw = _json_bytes({"ok": False, "error": str(e)}, 400)
            return self._send(code, raw, "application/json; charset=utf-8")
        try:
            if path.startswith("/api/rules/"):
                name = unquote(path[len("/api/rules/"):])
                fp = _rule_path(name)
                if not fp and name == "PRIVATE.md":
                    fp = WORKSPACE / "PRIVATE.md"
                if not fp:
                    code, raw = _json_bytes({"ok": False, "error": "unknown rule file"}, 404)
                    return self._send(code, raw, "application/json; charset=utf-8")
                if evolution.is_protected(ROOT, fp):
                    code, raw = _json_bytes({"ok": False, "error": "read-only rule file (protected); edit it on disk"}, 403)
                    return self._send(code, raw, "application/json; charset=utf-8")
                content = body.get("content")
                if not isinstance(content, str) or not content.strip():
                    code, raw = _json_bytes({"ok": False, "error": "content required"}, 400)
                    return self._send(code, raw, "application/json; charset=utf-8")
                if fp.exists():
                    ts = time.strftime("%Y%m%d%H%M%S")
                    backup = fp.with_name(f"{fp.name}.bak-selfstatus-{ts}")
                    try:
                        backup.write_text(fp.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                    except Exception:
                        pass
                _atomic_write_text(fp, content)
                code, raw = _json_bytes({"ok": True, "name": name, "bytes": len(content.encode("utf-8"))})
                return self._send(code, raw, "application/json; charset=utf-8")
        except Exception as e:
            code, raw = _json_bytes({"ok": False, "error": str(e)}, 500)
            return self._send(code, raw, "application/json; charset=utf-8")
        code, raw = _json_bytes({"ok": False, "error": "not found"}, 404)
        self._send(code, raw, "application/json; charset=utf-8")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            # --- Role Studio DELETE ---
            if path.startswith("/api/roles/"):
                slug = path[len("/api/roles/"):].strip("/")
                if not slug or "/" in slug or ".." in slug:
                    code, raw = _json_bytes({"ok": False, "error": "invalid slug"}, 400)
                    return self._send(code, raw, "application/json; charset=utf-8")
                yaml_path = HOME / "data" / "characters" / f"{slug}.yaml"
                if not yaml_path.is_file():
                    code, raw = _json_bytes({"ok": False, "error": "not found"}, 404)
                    return self._send(code, raw, "application/json; charset=utf-8")
                yaml_path.unlink()
                img_dir = HOME / "data" / "characters" / "images" / slug
                if img_dir.is_dir():
                    import shutil as _shutil
                    _shutil.rmtree(img_dir)
                code, raw = _json_bytes({"ok": True, "slug": slug, "deleted": True})
                return self._send(code, raw, "application/json; charset=utf-8")
            # --- End Role Studio DELETE ---
            if path.startswith("/api/mcp/"):
                name = unquote(path[len("/api/mcp/"):])
                if name == "nas":
                    code, raw = _json_bytes({"ok": False, "error": "nas MCP는 코어 — 삭제 불가"}, 400)
                    return self._send(code, raw, "application/json; charset=utf-8")
                cfg = _read_mcp_config()
                if name in cfg.get("mcpServers", {}):
                    del cfg["mcpServers"][name]
                    _write_mcp_config(cfg)
                    code, raw = _json_bytes({"ok": True, "mcpServers": cfg["mcpServers"]})
                else:
                    code, raw = _json_bytes({"ok": False, "error": "not found"}, 404)
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/sessions/"):
                sid = path[len("/api/sessions/"):]
                existing = REG.sessions.get(_safe_session_id(sid))
                # A stale busy=True (e.g. its agy process got reaped by
                # kill_orphan_agy mid-turn without ever emitting a
                # result/error event) must not block deletion forever --
                # only a genuinely still-running process counts as busy.
                really_busy = bool(
                    existing is not None and existing.busy
                    and existing.proc is not None and existing.proc.poll() is None
                )
                if really_busy:
                    code, raw = _json_bytes({"ok": False, "error": "이 세션은 지금 작업 중이라 삭제할 수 없습니다"}, 409)
                    return self._send(code, raw, "application/json; charset=utf-8")
                ok = REG.delete(sid)
                code, raw = _json_bytes({"ok": ok} if ok else {"ok": False, "error": "not found"}, 200 if ok else 404)
                return self._send(code, raw, "application/json; charset=utf-8")
        except Exception as e:
            code, raw = _json_bytes({"ok": False, "error": str(e)}, 500)
            return self._send(code, raw, "application/json; charset=utf-8")
        code, raw = _json_bytes({"ok": False, "error": "not found"}, 404)
        self._send(code, raw, "application/json; charset=utf-8")

    def _sse(self, sid: str) -> None:
        try:
            sess = REG.get(sid)
        except Exception as e:
            code, raw = _json_bytes({"ok": False, "error": str(e)}, 400)
            return self._send(code, raw, "application/json; charset=utf-8")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b"event: hello\ndata: {\"ok\":true}\n\n")
            self.wfile.flush()
        except Exception:
            return
        sub_queue: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
        with sess.lock:
            sess.subscribers.append(sub_queue)
        try:
            # Recycle idle SSE sockets after 15 min so leaked mobile
            # connections die. Do NOT cut a busy turn — a tablet sitting
            # on a long job used to hit this wall, show "연결이 끊겼다냥",
            # and leave the other phone with no live stream at all.
            idle_until = _now() + 900
            while True:
                if not sess.busy and _now() > idle_until:
                    break
                try:
                    ev = sub_queue.get(timeout=15)
                except queue.Empty:
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except Exception:
                        break
                    if sess.busy:
                        idle_until = _now() + 900
                    continue
                if sess.busy:
                    idle_until = _now() + 900
                safe = {k: v for k, v in ev.items()}
                if "payload" in safe and isinstance(safe["payload"], dict):
                    safe["payload"] = {k: safe["payload"].get(k) for k in list(safe["payload"])[:8]}
                line = "data: " + json.dumps(safe, ensure_ascii=False) + "\n\n"
                try:
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    break
        finally:
            with sess.lock:
                if sub_queue in sess.subscribers:
                    sess.subscribers.remove(sub_queue)


def main() -> None:
    if not Path(AGY).exists():
        raise SystemExit(f"agy not found: {AGY}")
    seeded = identity.seed_workspace_files()
    if seeded:
        print(f"seeded workspace from templates: {seeded}", flush=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=_standby_maintenance_loop, daemon=True).start()
    threading.Thread(target=accounts.watch_loop, daemon=True).start()
    if AUTO_RECYCLE_ENABLED:
        threading.Thread(target=_auto_recycle_loop, daemon=True).start()
    print(f"chatbot on http://{HOST}:{PORT} (VibeCat-class NAS)", flush=True)

    def _stop(*_a):
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
