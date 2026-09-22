#!/usr/bin/env python3
"""MCP tool server: JSON-RPC tools/list + tools/call over HTTP (MCP-ish).

Serves the generic file and command tools, the core's adapters (mcp_core.py) and, when present, the host plugin
(nas_mcp_host.py: this machine's own services and siblings). It has no tool of its own about any one machine.
The name clients know it by ("nas") is a configuration key of each provider and stays as it is.

Listen: 127.0.0.1:3012  paths: /mcp, /healthz
Never returns oauth tokens / secrets / .env contents.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

HOST = os.environ.get("NAS_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NAS_MCP_PORT", "3012"))
HOME = Path(os.environ.get("HOME", "/volume1/homes/me"))
SERVICES = HOME / "services"
DATA = SERVICES / "chatbot" / "data"  # consolidated under chatbot/ 2026-09-16
# Same env var as server.py's WEB_ROOT -- only this NAS's actual value
# (/volume1/web) is host-specific, not the mechanism.
WEB_ROOT = Path(os.environ.get("AGY_CHAT_WEB_ROOT", "/volume1/web"))
AGENTS = HOME / ".agents"
TMP_ROOT = Path("/tmp/chatbot-mcp")
CODE_ROOT = Path(__file__).resolve().parent  # where protected_paths.json lives

# Which paths are write-protected is decided by the core registry, not here.
# If it cannot be imported, write_file refuses everything (read tools keep working).
try:
    import evolution
except Exception:
    evolution = None
# The core's tools (memory, observation, ticket) are served by the mcp_core adapter module; without it the
# server just lacks them.
try:
    import mcp_core
except Exception:
    mcp_core = None

# Generic/core roots -- always allowlisted regardless of deployment.
# Sphere/Hermes/wiki-specific extra roots live in the optional nas_mcp_host
# plugin (see docs/plans/chatbot-host-portability.md Phase 1) and get merged
# in by _allow_roots()/_read_roots() below once HOST_PLUGIN is resolved.
ALLOW_ROOTS = [
    DATA.resolve(),
    AGENTS.resolve(),
    (WEB_ROOT / "chat").resolve(),
    TMP_ROOT.resolve(),
    (DATA / "workspace").resolve(),
    (SERVICES / "chatbot").resolve(),  # host py/static; not in agy ADD_DIRS (token tax)
]

# Also allowlist these for read/list (broader read roots)
READ_ROOTS = ALLOW_ROOTS + [
    SERVICES.resolve(),
    (HOME / ".local" / "bin").resolve(),
    (HOME / "bin").resolve(),
    (HOME / "AGENTS.md").resolve(),
]

SECRET_NAME_RE = re.compile(
    r"(?i)(^\.env($|\.)|oauth|token|secret|credential|passwd|password|api[_-]?key|auth\.json|antigravity-oauth)"
)
SECRET_CONTENT_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9\-._~+/]+=*|api[_-]?key\s*[:=]|refresh[_-]?token|client_secret|BEGIN (RSA |OPENSSH )?PRIVATE KEY)"
)

# Commands allowed by their first token (exact match, never a string prefix).
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
)
# chatbot-ctl.sh is a lifecycle script: only these read/diagnose subcommands, and
# no arguments except probe's timeout. `doctor --auto-repair` reaches repair, so
# doctor takes none. repair/start/stop/restart/defibrillate are for people.
CTL_NAMES = (str(SERVICES / "chatbot-ctl.sh"), "chatbot-ctl.sh")
CTL_SUBCOMMANDS = ("status", "doctor", "probe", "guard")
# curl is GET-only against this machine: fixed leading flags, one local URL, and
# a short list of harmless extras. Anything that can write a file or send a body
# (-o -O -T -d -X -F --json ...) is simply not on the list.
CURL_LEAD_FLAGS = ("-fsS", "-sS")
CURL_URL_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):\d{1,5}(/\S*)?$")
CURL_FLAGS = ("-s", "-S", "-f", "-i", "-I")
CURL_NUMERIC_FLAGS = ("-m", "--max-time", "--connect-timeout")




def envelope(success: bool, message: str, data: Any = None) -> dict:
    return {"success": success, "message": message, "data": data}


def _resolve_target_path(raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        return Path(".")
    if raw.startswith("~"):
        p = Path(raw).expanduser()
        return p.resolve()
    if raw.startswith("/data/"):
        raw = "data/" + raw[6:]
    elif raw == "/data":
        raw = "data"
    elif raw.startswith("/services/"):
        raw = "services/" + raw[10:]
    elif raw in ("/AGENTS.md", "AGENTS.md"):
        return (HOME / "AGENTS.md").resolve()

    p = Path(raw)
    if not p.is_absolute():
        ws_candidate = (DATA / "workspace" / p).resolve()
        if ws_candidate.exists():
            return ws_candidate
        svc_candidate = (SERVICES / "chatbot" / p).resolve()
        if svc_candidate.exists():
            return svc_candidate
        home_candidate = (HOME / p).resolve()
        if home_candidate.exists():
            return home_candidate
        if str(p).startswith("data/"):
            return (SERVICES / "chatbot" / p).resolve()
        return ws_candidate
    return p.resolve()


def _is_under(path: Path, roots: List[Path]) -> bool:
    try:
        rp = path.resolve()
    except Exception:
        return False
    for root in roots:
        try:
            if root.is_file() and rp == root:
                return True
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
    defs = [
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
            "description": "Write text file under write allowlist roots only (protected paths are refused)",
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
            "description": "Run allowlisted read-only commands (ls/cat/df/ps/..., chatbot-ctl.sh status|doctor|probe|guard, GET-only curl to localhost)",
            "inputSchema": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
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
    if mcp_core is not None:
        defs += list(mcp_core.TOOL_DEFS)
    if HOST_PLUGIN:
        defs += list(getattr(HOST_PLUGIN, "EXTRA_TOOL_DEFS", []))
    return defs


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
        return p.returncode, _scrub_text(p.stdout[-8000:]), _scrub_text(p.stderr[-4000:])
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


# Optional DiskStation host-plugin (Sphere/Hermes/NamuWatcher awareness) --
# a different deployment just doesn't ship nas_mcp_host.py, or sets
# NAS_MCP_HOST_PLUGIN=0, and gets the generic core tool set only. Loaded
# here (not at the top of the file) because nas_mcp_host imports envelope/
# _run/_scrub_text back from this module -- they must already exist in
# this module's namespace when that import runs.
HOST_PLUGIN = None
if os.environ.get("NAS_MCP_HOST_PLUGIN", "1") != "0":
    try:
        import nas_mcp_host as HOST_PLUGIN  # noqa: N813
    except Exception:
        HOST_PLUGIN = None


def _allow_roots() -> List[Path]:
    roots = list(ALLOW_ROOTS)
    if HOST_PLUGIN:
        roots += list(getattr(HOST_PLUGIN, "EXTRA_ALLOW_ROOTS", []))
    return roots


def _read_roots() -> List[Path]:
    roots = list(READ_ROOTS)
    if HOST_PLUGIN:
        roots += list(getattr(HOST_PLUGIN, "EXTRA_READ_ROOTS", []))
    return roots


def _cmd_prefixes() -> tuple:
    prefixes = list(CMD_PREFIXES)
    if HOST_PLUGIN:
        prefixes += list(getattr(HOST_PLUGIN, "EXTRA_CMD_PREFIXES", ()))
    return tuple(prefixes)


def _ctl_refusal(args: List[str]) -> Optional[str]:
    if not args:
        return None  # bare chatbot-ctl.sh == status
    sub, rest = args[0], args[1:]
    if sub not in CTL_SUBCOMMANDS:
        return f"chatbot-ctl.sh {sub}: not allowed here (only {'|'.join(CTL_SUBCOMMANDS)})"
    if sub == "probe" and (not rest or (len(rest) == 1 and re.fullmatch(r"\d{1,2}", rest[0]))):
        return None
    if rest:
        return f"chatbot-ctl.sh {sub}: arguments not allowed here"
    return None


def _curl_refusal(args: List[str]) -> Optional[str]:
    if len(args) < 2 or args[0] not in CURL_LEAD_FLAGS:
        return "curl form not allowed (curl -fsS|-sS http://127.0.0.1:<port>/...)"
    url = args[1]
    if not CURL_URL_RE.match(url):
        return "curl: only http://127.0.0.1:<port> or http://localhost:<port> URLs"
    if "defibrillate" in url.lower():
        return "curl: this endpoint is not available to tools"
    rest, i = args[2:], 0
    while i < len(rest):
        if rest[i] in CURL_FLAGS:
            i += 1
        elif rest[i] in CURL_NUMERIC_FLAGS and i + 1 < len(rest) and re.fullmatch(r"\d{1,3}", rest[i + 1]):
            i += 2
        else:
            return f"curl: option not allowed: {rest[i]}"
    return None


def _command_refusal(cmd: str) -> Optional[str]:
    """Why run_command must refuse `cmd`, or None. Matching is per token, never per string prefix."""
    if not cmd or "\n" in cmd or any(c in cmd for c in ";|&`") or "$(" in cmd:
        return "command rejected (metacharacters or empty)"
    # Redirection would write past write_file's checks. Only `2>/dev/null` is harmless.
    if re.search(r"[<>]", re.sub(r"(?<!\S)2>\s?/dev/null(?!\S)", "", cmd)):
        return "command rejected (redirection)"
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return "command rejected (unparseable)"
    if not tokens:
        return "command rejected (metacharacters or empty)"
    if tokens[0] in CTL_NAMES:
        return _ctl_refusal(tokens[1:])
    if tokens[0] == "curl":
        return _curl_refusal(tokens[1:])
    for prefix in _cmd_prefixes():
        head = shlex.split(prefix)
        if tokens[:len(head)] == head:
            return None
    return "command prefix not allowlisted"


def call_tool(name: str, arguments: dict) -> dict:
    args = arguments or {}
    try:
        if name == "list_dir":
            path = _resolve_target_path(args.get("path"))
            if not _is_under(path, _read_roots()):
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
            path = _resolve_target_path(args.get("path"))
            max_bytes = int(args.get("max_bytes") or 32_000)
            max_bytes = max(1, min(max_bytes, 64_000))
            if not _is_under(path, _read_roots()):
                return envelope(False, "path not allowlisted", None)
            deny = _deny_secret_path(path)
            if deny:
                return envelope(False, deny, None)
            if not path.is_file():
                return envelope(False, "not a file", None)
            size = path.stat().st_size
            raw = path.read_bytes()[:max_bytes]
            text = raw.decode("utf-8", errors="replace")
            return envelope(True, "ok", {
                "path": str(path.resolve()),
                "content": _scrub_text(text),
                "truncated": size > len(raw),
                "bytes_read": len(raw),
                "bytes_total": size,
            })

        if name == "write_file":
            path = _resolve_target_path(args.get("path"))
            content = str(args.get("content") if args.get("content") is not None else "")
            if len(content.encode("utf-8")) > 2_000_000:
                return envelope(False, "content too large", None)
            if not _is_under(path, _allow_roots()):
                return envelope(False, "write path not allowlisted", None)
            if evolution is None:
                return envelope(False, "protection registry unavailable; writes are refused", None)
            why = evolution.match_protected(CODE_ROOT, path)
            if why:
                return envelope(False, f"write path is protected ({why})", {"path": str(path)})
            deny = _deny_secret_path(path)
            if deny:
                return envelope(False, deny, None)
            if SECRET_CONTENT_RE.search(content):
                return envelope(False, "refusing to write secret-like content", None)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return envelope(True, "written", {"path": str(path.resolve()), "bytes": len(content.encode("utf-8"))})

        if name == "run_command":
            cmd = str(args.get("cmd") or "").strip()
            why = _command_refusal(cmd)
            if why:
                return envelope(False, why, {"cmd": cmd})
            # block secret paths in args
            if SECRET_NAME_RE.search(cmd) or "antigravity-oauth" in cmd.lower() or ".env" in cmd:
                return envelope(False, "refusing secret-related command", None)
            code, out, err = _run(["bash", "-lc", cmd], timeout=30)
            return envelope(code == 0, "ok" if code == 0 else "nonzero", {"code": code, "stdout": out, "stderr": err})

        if mcp_core is not None and name in mcp_core.NAMES:
            return mcp_core.call(name, args, DATA, SECRET_CONTENT_RE)

        if name == "search_text":
            path = _resolve_target_path(args.get("path"))
            pattern = str(args.get("pattern") or "")
            if not pattern or len(pattern) > 200:
                return envelope(False, "bad pattern", None)
            if not _is_under(path, _read_roots()):
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

        if HOST_PLUGIN and hasattr(HOST_PLUGIN, "call_tool"):
            handled = HOST_PLUGIN.call_tool(name, args)
            if handled is not None:
                return handled

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
            body = json.dumps({"ok": True, "service": "chatbot-mcp", "port": PORT}).encode("utf-8")
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
                    "serverInfo": {"name": "chatbot-mcp", "version": "1.0.0"},
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
    print(f"chatbot-mcp on http://{HOST}:{PORT}/mcp", flush=True)

    def _stop(*_a):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    httpd.serve_forever()


if __name__ == "__main__":
    # Serve through the imported module, not this __main__ copy: the host plugin imports `mcp_server`, and two
    # copies would leave the plugin with different module state than the server that dispatches to it.
    import mcp_server as _served
    _served.main()
