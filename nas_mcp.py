#!/usr/bin/env python3
"""Sphere NAS MCP HTTP server — JSON-RPC tools/list + tools/call (MCP-ish).

Listen: 127.0.0.1:3012  paths: /mcp, /healthz
Never returns oauth tokens / secrets / .env contents.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

HOST = os.environ.get("NAS_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NAS_MCP_PORT", "3012"))
HOME = Path(os.environ.get("HOME", "/volume1/homes/me"))
SERVICES = HOME / "services"
DATA = SERVICES / "chatbot-data"
WEB = Path("/volume1/web")
HERMES = HOME / ".hermes"
TMP_ROOT = Path("/tmp/sphere-agy")

ALLOW_ROOTS = [
    DATA.resolve(),
    (WEB / "chat").resolve(),
    (WEB / "sphere-art").resolve(),
    (WEB / "sphere-lore").resolve(),
    (WEB / "sphere-sound").resolve(),
    (WEB / "sphere-tech").resolve(),
    (HERMES / "factory").resolve(),
    (HERMES / "shared").resolve() if (HERMES / "shared").exists() else (HERMES / "factory").resolve(),
    TMP_ROOT.resolve(),
    (DATA / "workspace").resolve(),
]

# Also allowlist these for read/list (broader read roots)
READ_ROOTS = ALLOW_ROOTS + [
    SERVICES.resolve(),
    WEB.resolve(),
    HERMES.resolve(),
    (HOME / ".local" / "bin").resolve(),
]

SECRET_NAME_RE = re.compile(
    r"(?i)(^\.env($|\.)|oauth|token|secret|credential|passwd|password|api[_-]?key|auth\.json|antigravity-oauth)"
)
SECRET_CONTENT_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9\-._~+/]+=*|api[_-]?key\s*[:=]|refresh[_-]?token|client_secret|BEGIN (RSA |OPENSSH )?PRIVATE KEY)"
)

CMD_PREFIXES = (
    "ls",
    "cat",
    "head",
    "tail",
    "df",
    "free",
    "ps",
    "du",
    "stat",
    "pwd",
    "whoami",
    "date",
    "uname",
    "curl -fsS http://127.0.0.1:",
    "curl -sS http://127.0.0.1:",
    "curl -fsS http://localhost:",
    "curl -sS http://localhost:",
    "/volume1/homes/me/services/chatbot-ctl.sh",
    "/volume1/homes/me/services/namuwatcher-ctl.sh",
    "chatbot-ctl.sh",
    "namuwatcher-ctl.sh",
    "/volume1/homes/me/.hermes/scripts/hermes-lifecycle.sh",
    "/volume1/homes/me/.local/bin/hermes",
    "hermes status",
    "hermes --version",
)

SERVICE_CTLS = {
    "sphere-agy": str(SERVICES / "chatbot-ctl.sh"),
    "chatbot": str(SERVICES / "chatbot-ctl.sh"),
    "namuwatcher": str(SERVICES / "namuwatcher-ctl.sh"),
    "nas-mcp": None,  # handled internally
}


def envelope(success: bool, message: str, data: Any = None) -> dict:
    return {"success": success, "message": message, "data": data}


def _is_under(path: Path, roots: List[Path]) -> bool:
    try:
        rp = path.resolve()
    except Exception:
        return False
    for root in roots:
        try:
            rp.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _deny_secret_path(path: Path) -> Optional[str]:
    name = path.name
    if SECRET_NAME_RE.search(name):
        return "refusing secret-like filename"
    # block oauth token file and common secret dirs
    low = str(path).lower()
    for bad in ("antigravity-oauth-token", "/.ssh/", "id_rsa", "id_ed25519", "auth.json"):
        if bad in low:
            return "refusing secret path"
    return None


def _scrub_text(text: str) -> str:
    if not text:
        return text
    lines = []
    for line in text.splitlines():
        if SECRET_CONTENT_RE.search(line) or any(
            x in line.lower() for x in ("authorization:", "bearer ", "refresh_token", "client_secret")
        ):
            lines.append("[redacted]")
        else:
            lines.append(line)
    return "\n".join(lines)


def tool_defs() -> List[dict]:
    return [
        {"name": "ping_nas", "description": "Health ping for NAS MCP", "inputSchema": {"type": "object", "properties": {}}},
        {
            "name": "list_services",
            "description": "List known Sphere/NAS service ctl scripts and ports",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "service_ctl",
            "description": "Run ctl script action: start|stop|restart|status",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "action": {"type": "string", "enum": ["start", "stop", "restart", "status"]},
                },
                "required": ["name", "action"],
            },
        },
        {
            "name": "list_dir",
            "description": "List directory under allowlisted roots",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "read_file",
            "description": "Read a text file under allowlisted roots (secrets blocked)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write text file under write allowlist roots only",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "run_command",
            "description": "Run allowlisted prefix commands (ls/cat/ctl/curl localhost/df/ps/...)",
            "inputSchema": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        },
        {
            "name": "sphere_hub_status",
            "description": "Check Sphere hub / web + chat health endpoints",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "factory_status",
            "description": "Summarize Hermes factory runs directory",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "hermes_status",
            "description": "Hermes lifecycle / process status summary",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "search_text",
            "description": "Search text files under allowlisted path (capped)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "pattern": {"type": "string"},
                },
                "required": ["path", "pattern"],
            },
        },
    ]


def _run(cmd: List[str], timeout: int = 20, cwd: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env={**os.environ, "PATH": f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", "")},
        )
        return p.returncode, _scrub_text(p.stdout[-20000:]), _scrub_text(p.stderr[-8000:])
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def call_tool(name: str, arguments: dict) -> dict:
    args = arguments or {}
    try:
        if name == "ping_nas":
            return envelope(True, "pong", {"host": HOST, "port": PORT, "ts": time.time()})

        if name == "list_services":
            items = []
            for n, ctl in SERVICE_CTLS.items():
                items.append({"name": n, "ctl": ctl})
            items.append({"name": "chat", "port": 3011, "url": "http://127.0.0.1:3011/healthz"})
            items.append({"name": "nas-mcp", "port": 3012, "url": "http://127.0.0.1:3012/healthz"})
            items.append({"name": "namuwatcher", "port": 3010})
            return envelope(True, "ok", {"services": items})

        if name == "service_ctl":
            svc = str(args.get("name") or "").strip()
            action = str(args.get("action") or "").strip()
            if action not in ("start", "stop", "restart", "status"):
                return envelope(False, "invalid action", None)
            if svc in ("nas-mcp",):
                return envelope(False, "use chatbot-ctl for mcp lifecycle", None)
            ctl = SERVICE_CTLS.get(svc)
            if not ctl or not Path(ctl).exists():
                return envelope(False, f"unknown service: {svc}", None)
            code, out, err = _run([ctl, action], timeout=60)
            return envelope(code == 0, "ran" if code == 0 else "failed", {"code": code, "stdout": out, "stderr": err})

        if name == "list_dir":
            path = Path(str(args.get("path") or "")).expanduser()
            if not _is_under(path, READ_ROOTS):
                return envelope(False, "path not allowlisted", {"path": str(path)})
            deny = _deny_secret_path(path)
            if deny:
                return envelope(False, deny, None)
            if not path.is_dir():
                return envelope(False, "not a directory", None)
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: p.name.lower())[:500]:
                if SECRET_NAME_RE.search(child.name):
                    continue
                try:
                    st = child.stat()
                    entries.append({
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": st.st_size if child.is_file() else None,
                    })
                except Exception:
                    continue
            return envelope(True, "ok", {"path": str(path.resolve()), "entries": entries})

        if name == "read_file":
            path = Path(str(args.get("path") or "")).expanduser()
            max_bytes = int(args.get("max_bytes") or 100_000)
            max_bytes = max(1, min(max_bytes, 500_000))
            if not _is_under(path, READ_ROOTS):
                return envelope(False, "path not allowlisted", None)
            deny = _deny_secret_path(path)
            if deny:
                return envelope(False, deny, None)
            if not path.is_file():
                return envelope(False, "not a file", None)
            raw = path.read_bytes()[:max_bytes]
            text = raw.decode("utf-8", errors="replace")
            return envelope(True, "ok", {"path": str(path.resolve()), "content": _scrub_text(text), "truncated": len(raw) >= path.stat().st_size and False or len(raw) < path.stat().st_size})

        if name == "write_file":
            path = Path(str(args.get("path") or "")).expanduser()
            content = str(args.get("content") if args.get("content") is not None else "")
            if len(content.encode("utf-8")) > 2_000_000:
                return envelope(False, "content too large", None)
            if not _is_under(path, ALLOW_ROOTS):
                return envelope(False, "write path not allowlisted", None)
            deny = _deny_secret_path(path)
            if deny:
                return envelope(False, deny, None)
            if SECRET_CONTENT_RE.search(content):
                return envelope(False, "refusing to write secret-like content", None)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return envelope(True, "written", {"path": str(path.resolve()), "bytes": len(content.encode("utf-8"))})

        if name == "run_command":
            cmd = str(args.get("cmd") or "").strip()
            if not cmd or "\n" in cmd or ";" in cmd or "|" in cmd or "&" in cmd or "`" in cmd or "$(" in cmd:
                return envelope(False, "command rejected (metacharacters or empty)", None)
            if not any(cmd == p or cmd.startswith(p + " ") or cmd.startswith(p) for p in CMD_PREFIXES):
                # also allow bare first-token match for simple cmds
                first = cmd.split()[0]
                if first not in ("ls", "cat", "head", "tail", "df", "free", "ps", "du", "stat", "pwd", "whoami", "date", "uname"):
                    return envelope(False, "command prefix not allowlisted", {"cmd": cmd})
            # block secret paths in args
            if SECRET_NAME_RE.search(cmd) or "antigravity-oauth" in cmd.lower() or ".env" in cmd:
                return envelope(False, "refusing secret-related command", None)
            code, out, err = _run(["bash", "-lc", cmd], timeout=30)
            return envelope(code == 0, "ok" if code == 0 else "nonzero", {"code": code, "stdout": out, "stderr": err})

        if name == "sphere_hub_status":
            checks = {}
            for label, url in (
                ("chat", "http://127.0.0.1:3011/healthz"),
                ("nas_mcp", "http://127.0.0.1:3012/healthz"),
                ("namuwatcher", "http://127.0.0.1:3010/"),
            ):
                code, out, err = _run(["curl", "-fsS", "-m", "3", url], timeout=5)
                checks[label] = {"ok": code == 0, "body": (out or err)[:500]}
            hub = WEB / "index.html"
            checks["hub_index"] = {"exists": hub.exists(), "path": str(hub)}
            return envelope(True, "ok", checks)

        if name == "factory_status":
            factory = HERMES / "factory"
            runs = factory / "runs"
            data = {"factory": str(factory), "exists": factory.exists()}
            if runs.exists():
                kids = sorted(runs.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
                data["recent_runs"] = [{"name": k.name, "mtime": k.stat().st_mtime, "type": "dir" if k.is_dir() else "file"} for k in kids]
            log = factory / "factory-log.jsonl"
            if log.exists():
                data["log_tail"] = _scrub_text(log.read_text(encoding="utf-8", errors="replace")[-4000:])
            return envelope(True, "ok", data)

        if name == "hermes_status":
            life = HERMES / "scripts" / "hermes-lifecycle.sh"
            info = {"hermes_home": str(HERMES), "lifecycle_script": str(life), "exists": life.exists()}
            hermes_bin = HOME / ".local" / "bin" / "hermes"
            if hermes_bin.exists():
                code, out, err = _run([str(hermes_bin), "status"], timeout=25)
                info["hermes_status"] = {"code": code, "stdout": out[-4000:], "stderr": err[-2000:]}
            elif life.exists():
                code, out, err = _run([str(life), "status"], timeout=25)
                info["lifecycle"] = {"code": code, "stdout": out[-4000:], "stderr": err[-2000:]}
            else:
                code, out, err = _run(["bash", "-lc", "ps aux | head -1; ps aux | grep -i hermes | grep -v grep | head -20"], timeout=10)
                info["ps"] = out
            return envelope(True, "ok", info)

        if name == "search_text":
            path = Path(str(args.get("path") or "")).expanduser()
            pattern = str(args.get("pattern") or "")
            if not pattern or len(pattern) > 200:
                return envelope(False, "bad pattern", None)
            if not _is_under(path, READ_ROOTS):
                return envelope(False, "path not allowlisted", None)
            deny = _deny_secret_path(path)
            if deny:
                return envelope(False, deny, None)
            try:
                cre = re.compile(pattern)
            except re.error as e:
                return envelope(False, f"invalid regex: {e}", None)
            hits = []
            files = []
            if path.is_file():
                files = [path]
            elif path.is_dir():
                for root, dirs, fnames in os.walk(path):
                    # prune secret-ish dirs
                    dirs[:] = [d for d in dirs if not SECRET_NAME_RE.search(d) and d not in (".git", "node_modules", "@eaDir")]
                    for fn in fnames:
                        if SECRET_NAME_RE.search(fn):
                            continue
                        if not fn.endswith((".md", ".txt", ".py", ".sh", ".json", ".yml", ".yaml", ".css", ".js", ".html", ".log")):
                            continue
                        files.append(Path(root) / fn)
                        if len(files) >= 200:
                            break
                    if len(files) >= 200:
                        break
            for fp in files:
                try:
                    if fp.stat().st_size > 1_000_000:
                        continue
                    text = fp.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if cre.search(line):
                        hits.append({"file": str(fp), "line": i, "text": _scrub_text(line[:300])})
                        if len(hits) >= 50:
                            return envelope(True, "capped", {"hits": hits, "capped": True})
            return envelope(True, "ok", {"hits": hits, "capped": False})

        return envelope(False, f"unknown tool: {name}", None)
    except Exception as e:
        return envelope(False, f"error: {e}", {"trace": traceback.format_exc()[-1500:]})


class Handler(BaseHTTPRequestHandler):
    server_version = "SphereNasMcp/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        msg = fmt % args
        if any(x in msg.lower() for x in ("token", "authorization", "bearer", "api_key")):
            return
        try:
            import sys
            sys.stderr.write("%s - %s\n" % (self.address_string(), msg))
        except Exception:
            pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")

    def _send(self, code: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/healthz", "/health", "/"):
            body = json.dumps({"ok": True, "service": "nas-mcp", "port": PORT}).encode("utf-8")
            return self._send(200, body)
        if path in ("/mcp", "/mcp/"):
            # lightweight discovery
            body = json.dumps({"ok": True, "mcp": True, "tools": [t["name"] for t in tool_defs()]}).encode("utf-8")
            return self._send(200, body)
        self._send(404, b'{"ok":false,"error":"not found"}')

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/mcp", "/mcp/", "/"):
            return self._send(404, b'{"ok":false,"error":"not found"}')
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if len(raw) > 2_000_000:
            return self._send(413, b'{"ok":false,"error":"too large"}')
        try:
            req = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return self._send(400, b'{"ok":false,"error":"bad json"}')

        # JSON-RPC style
        if isinstance(req, dict) and "method" in req:
            rid = req.get("id")
            method = req.get("method")
            params = req.get("params") or {}
            if method in ("initialize",):
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "sphere-nas-mcp", "version": "1.0.0"},
                }
                return self._rpc(rid, result)
            if method in ("notifications/initialized", "initialized"):
                # notification — empty ack
                return self._send(204, b"")
            if method in ("tools/list", "list_tools"):
                return self._rpc(rid, {"tools": tool_defs()})
            if method in ("tools/call", "call_tool"):
                tname = params.get("name") or params.get("tool")
                arguments = params.get("arguments") or params.get("args") or {}
                out = call_tool(str(tname), arguments if isinstance(arguments, dict) else {})
                # MCP tool result content
                text = json.dumps(out, ensure_ascii=False)
                return self._rpc(rid, {"content": [{"type": "text", "text": text}], "isError": not out.get("success", False)})
            if method == "ping":
                return self._rpc(rid, {})
            return self._rpc(rid, None, error={"code": -32601, "message": f"Method not found: {method}"})

        # simple REST fallback: {"tool":"...","arguments":{}}
        if isinstance(req, dict) and req.get("tool"):
            out = call_tool(str(req["tool"]), req.get("arguments") or {})
            return self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"))

        self._send(400, b'{"ok":false,"error":"expected JSON-RPC method"}')

    def _rpc(self, rid: Any, result: Any = None, error: Any = None) -> None:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result
        self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def main() -> None:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"sphere-nas-mcp on http://{HOST}:{PORT}/mcp", flush=True)

    def _stop(*_a):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
