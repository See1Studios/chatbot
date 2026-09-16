#!/usr/bin/env python3
"""Sphere agy chat host — VibeCat-class persistent stream-json session (NAS domain)."""
from __future__ import annotations

import json
import mimetypes
mimetypes.add_type("image/webp", ".webp")
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

HOST = os.environ.get("AGY_CHAT_HOST", "0.0.0.0")
PORT = int(os.environ.get("AGY_CHAT_PORT", "3011"))
AGY = os.environ.get("AGY_BIN", "/volume1/homes/me/.local/bin/agy")
ROOT = Path(os.environ.get("AGY_CHAT_ROOT", "/volume1/homes/me/services/chatbot"))
DATA = Path(os.environ.get("AGY_CHAT_DATA", "/volume1/homes/me/services/chatbot-data"))
STATIC = ROOT / "static"
SESSIONS = DATA / "sessions"
WORKSPACE = DATA / "workspace"
HOME = Path(os.environ.get("HOME", "/volume1/homes/me"))
BRAIN = HOME / ".gemini" / "antigravity-cli" / "brain"
ARTIFACTS_CACHE = DATA / "artifacts"
DEFAULT_MODEL = os.environ.get("AGY_CHAT_MODEL", "gemini-3.8-flash-medium")
MODELS = [
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-high",
    "gemini-3.8-flash-low",
    "gemini-3.1-pro-high",
    "gemini-3.1-pro-low",
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
]

# Narrow ADD_DIRS for spawn latency (2026-09-16).
# Removed: entire HOME, /volume1/web, .hermes, HOME/services, redundant artifacts.
# Keep: chatbot code + chatbot-data + /volume1/web/chat (persona publish mirror).
ADD_DIRS = [
    str(ROOT),                 # /services/chatbot (self-improve)
    str(DATA),                 # chatbot-data (workspace/sessions/artifacts/persona)
    "/volume1/web/chat",       # persona + chat static mirror (NOT all of /volume1/web)
]

# Session length guard thresholds (UI hist + optional conversation.db size)
SOFT_TURNS = 40
SOFT_CHARS = 15_000
HARD_TURNS = 60
HARD_CHARS = 25_000
HARD_DB_BYTES = 8 * 1024 * 1024  # ~8MB conversation.db
SOFT_DB_BYTES = 5 * 1024 * 1024
INACTIVITY_ROTATE_SEC = 3 * 3600  # 3 hours gap triggers auto-compaction and fresh rotate

for p in (SESSIONS, WORKSPACE, STATIC, ARTIFACTS_CACHE):
    p.mkdir(parents=True, exist_ok=True)


def _now() -> float:
    return time.time()


def _conversation_db_path(cid: Optional[str]) -> Optional[Path]:
    if not cid:
        return None
    return HOME / ".gemini" / "antigravity-cli" / "conversations" / f"{cid}.db"


def _conversation_db_size(cid: Optional[str]) -> int:
    p = _conversation_db_path(cid)
    if not p:
        return 0
    try:
        return p.stat().st_size if p.exists() else 0
    except OSError:
        return 0


def _hist_stats(history: List[dict]) -> tuple:
    turns = 0
    chars = 0
    for h in history or []:
        if h.get("role") not in ("user", "assistant"):
            continue
        turns += 1
        chars += len(str(h.get("text") or ""))
    return turns, chars


def _session_weight(history: List[dict], conversation_id: Optional[str]) -> dict:
    turns, chars = _hist_stats(history)
    db_bytes = _conversation_db_size(conversation_id)
    level = "ok"
    if turns >= HARD_TURNS or chars >= HARD_CHARS or db_bytes >= HARD_DB_BYTES:
        level = "hard"
    elif turns >= SOFT_TURNS or chars >= SOFT_CHARS or db_bytes >= SOFT_DB_BYTES:
        level = "soft"
    return {
        "level": level,
        "turns": turns,
        "chars": chars,
        "db_bytes": db_bytes,
        "soft_turns": SOFT_TURNS,
        "hard_turns": HARD_TURNS,
        "message_ko": (
            "세션이 길어져서 느려질 수 있어요. 새 채팅을 권장합니다"
            if level != "ok"
            else ""
        ),
    }


def _safe_session_id(sid: str) -> str:
    sid = (sid or "").strip()
    if not sid or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in sid):
        raise ValueError("invalid session id")
    return sid


def _safe_artifact_rel(rel: str) -> Optional[Path]:
    rel = unquote(rel or "").lstrip("/")
    if not rel or ".." in rel.split("/") or rel.startswith("\\"):
        return None
    candidates = [
        ARTIFACTS_CACHE / rel,
        WORKSPACE / "artifacts" / rel,
        WORKSPACE / rel,
    ]
    # brain/<uuid>/... paths
    if rel.startswith("brain/"):
        candidates.append(HOME / ".gemini" / "antigravity-cli" / rel)
    for fp in candidates:
        try:
            rp = fp.resolve()
        except Exception:
            continue
        allowed_roots = [
            ARTIFACTS_CACHE.resolve(),
            (WORKSPACE / "artifacts").resolve() if (WORKSPACE / "artifacts").exists() else WORKSPACE.resolve(),
            WORKSPACE.resolve(),
            BRAIN.resolve(),
        ]
        for root in allowed_roots:
            try:
                rp.relative_to(root)
                if rp.is_file():
                    return rp
            except ValueError:
                continue
    # Also allow searching brain for basename if path matches allowed artifact extensions
    base = Path(rel).name
    if base and re.search(r"\.(png|jpe?g|gif|webp|svg|mp4|webm|wav|mp3|md|txt|json|pdf|html|csv|yaml|yml|py|js|ts|gd|sh|css)$", base, re.I):
        try:
            for hit in BRAIN.glob(f"**/{base}"):
                if hit.is_file():
                    return hit.resolve()
        except Exception:
            pass
    return None


def _is_inquiry(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("/btw ") or t.startswith("/btw\n") or t == "/btw":
        return True
    if t.startswith("/q ") or t.startswith("/queue ") or t.startswith("/next "):
        return False
    if re.search(r"[\?？]\s*$", t):
        return True
    if re.match(r"^(what|why|how|where|when|who|is|are|can|could)\b", t, re.I):
        return True
    q_endings = (
        "인가", "인가요", "는가", "는가요", "은가", "은가요",
        "나요", "나", "니", "냐", "냐고", "니까", "까", "까요",
        "는지", "은지", "는지요", "지요", "죠", "건가", "건가요",
        "어때", "어때요", "뭐해", "뭐하니", "뭐야", "을까", "ㄹ까",
    )
    clean_end = re.sub(r"[.!~^;\s]+$", "", t)
    for qe in q_endings:
        if clean_end.endswith(qe):
            return True
    if len(t) <= 40:
        q_words = ("어디", "어떻게", "얼마나", "언제", "왜", "무슨", "무엇", "몇", "진행상황", "진행 상태", "현재 상태")
        for qw in q_words:
            if qw in t:
                return True
    return False


class AgentAdapter:
    """Base interface for spawning/talking to a CLI agent backend.

    Mirrors VibeCat's IAgentAdapter (Source/VibeCat/Private/AgentAdapters.cpp:
    Id/FindExecutable/BuildArgs/FormatStdin/PrepareMcpConfig/NormalizeLine, one
    concrete subclass per provider, picked via a factory) so the same seams
    exist here if another provider is ever wired in.

    Only `AgyAdapter` is implemented today — `claude`/`codex` CLIs aren't even
    installed on this host, and `grok` (the one that is) hasn't been asked
    for. Output-stream normalization (VibeCat's `NormalizeLine`) is
    deliberately NOT abstracted yet: `_read_stdout`'s stream-json event
    parsing is large, agy-specific, and has been the site of real incidents
    today (see docs/EMERGENCY.md, DEVLOG deadlock entries) — moving it behind
    this interface is future work for whenever a second provider actually
    needs it, not something to risk for a structure-only pass.
    """

    id = "base"
    keeps_stdin_open = True  # False = one-shot exec per prompt (codex/grok-style), not agy/claude-style persistent stdin

    def find_executable(self) -> str:
        raise NotImplementedError

    def build_args(self, model: str, effort: str, conversation_id: Optional[str], add_dirs: List[str]) -> List[str]:
        raise NotImplementedError

    def build_env(self, home: Path) -> dict:
        raise NotImplementedError

    def format_stdin(self, content: str) -> str:
        raise NotImplementedError


class AgyAdapter(AgentAdapter):
    id = "agy"
    keeps_stdin_open = True

    def find_executable(self) -> str:
        return AGY

    def build_args(self, model: str, effort: str, conversation_id: Optional[str], add_dirs: List[str]) -> List[str]:
        args = [
            self.find_executable(),
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--print-timeout", "8m",
            "--dangerously-skip-permissions",
            "--mode", "accept-edits",
            "--model", model,
        ]
        # Skills / AGENTS.md should expand; do NOT disable slash commands by default
        for d in add_dirs:
            if Path(d).exists():
                args.extend(["--add-dir", d])
        if effort:
            args.extend(["--effort", effort])
        if conversation_id:
            args.extend(["--conversation", conversation_id])
        return args

    def build_env(self, home: Path) -> dict:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"/volume1/homes/me/.local/bin:/usr/local/bin:/usr/bin:/bin:{env.get('PATH','')}"
        mcp_cfg = WORKSPACE / ".gemini" / "config" / "mcp_config.json"
        if mcp_cfg.exists():
            env["AGY_WORKSPACE"] = str(WORKSPACE)
        return env

    def format_stdin(self, content: str) -> str:
        return json.dumps({"event": "user", "message": {"content": content}}, ensure_ascii=False) + "\n"


AGENT_ADAPTERS: Dict[str, AgentAdapter] = {"agy": AgyAdapter()}
DEFAULT_PROVIDER = "agy"


def get_adapter(provider_id: str = DEFAULT_PROVIDER) -> AgentAdapter:
    return AGENT_ADAPTERS.get(provider_id, AGENT_ADAPTERS[DEFAULT_PROVIDER])


class _StandbyPool:
    """Keeps one pre-spawned, idle agy process warm so a brand-new session's
    first message can skip the ~7-9s cold-start tax (measured 2026-09-16 via
    isolated `agy --print` calls — a fixed per-process-spawn cost, independent
    of model/effort/ADD_DIRS; see docs/DEVLOG.md). Only used when the incoming
    session matches DEFAULT_MODEL with no effort override and no
    conversation_id yet (i.e. genuinely fresh) — anything else falls back to
    a normal cold spawn, since a standby's --model/--effort are fixed at
    spawn time and can't be changed after adoption.

    An unclaimed standby carries no --conversation flag like a stale probe
    leftover would, so it needs an explicit exemption from
    chatbot-ctl.sh's kill_orphan_agy() 90s no-conversation grace period —
    see standby.pid below, which that script checks and skips.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None

    def _marker_path(self) -> Path:
        return DATA / "standby.pid"

    def try_take(self) -> Optional[subprocess.Popen]:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                self._marker_path().unlink(missing_ok=True)
            except Exception:
                pass
            return proc
        return None

    def ensure_warm(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            adapter = get_adapter(DEFAULT_PROVIDER)
            args = adapter.build_args(DEFAULT_MODEL, "", None, ADD_DIRS)
            env = adapter.build_env(HOME)
            try:
                self._proc = subprocess.Popen(
                    args,
                    cwd=str(WORKSPACE),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                )
                try:
                    self._marker_path().write_text(str(self._proc.pid), encoding="utf-8")
                except Exception:
                    pass
            except Exception:
                self._proc = None


STANDBY_POOL = _StandbyPool()


def _standby_maintenance_loop() -> None:
    while True:
        try:
            STANDBY_POOL.ensure_warm()
        except Exception:
            pass
        time.sleep(15)


class AgySession:
    def __init__(self, sid: str, model: str = DEFAULT_MODEL, effort: str = ""):
        self.sid = sid
        self.adapter = get_adapter(DEFAULT_PROVIDER)
        self.model = model or DEFAULT_MODEL
        self.effort = effort or ""
        self.conversation_id: Optional[str] = None
        self.proc: Optional[subprocess.Popen] = None
        self.events: "queue.Queue[dict]" = queue.Queue()
        self.subscribers: List["queue.Queue[dict]"] = []
        self.lock = threading.RLock()  # DEADLOCK GUARD: must stay RLock — ensure()->_spawn()->stop() nests
        if type(self.lock) is type(threading.Lock()):  # pragma: no cover
            raise RuntimeError('AgySession.lock must be RLock, not Lock')
        self.created_at = _now()
        self.last_activity = self.created_at
        self.history: List[dict] = []
        self.busy = False
        self.msg_queue: List[str] = []
        self.current_text = ""
        self.turn_started_at = 0.0
        self.pending_images: List[str] = []
        self._stderr_tail: List[str] = []
        self.meta_path = SESSIONS / f"{sid}.json"
        self._heavy_warned_level = ""  # '', soft, hard — avoid spam
        self.successor_session_id = ""  # sticky rotate target
        self.predecessor_session_id = ""  # previous session ID if continued/rotated
        self.handoff_summary = ""  # concise handover summary from predecessor
        self.handoff_injected = False  # True once prepended to first agy stdin payload
        self._cached_summary = ""  # memoized handover summary for zero-delay rotate
        self._summary_generating = False
        self._load_meta()

    def _load_meta(self) -> None:
        if self.meta_path.exists():
            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                self.conversation_id = meta.get("conversation_id")
                self.model = meta.get("model") or self.model
                self.effort = meta.get("effort") or self.effort
                self.history = meta.get("history") or []
                self.successor_session_id = str(meta.get("successor_session_id") or "")
                self.predecessor_session_id = str(meta.get("predecessor_session_id") or "")
                self.handoff_summary = str(meta.get("handoff_summary") or "")
                self.handoff_injected = bool(meta.get("handoff_injected", False))
                ts_list = [h.get("ts") for h in self.history if isinstance(h.get("ts"), (int, float))]
                if ts_list:
                    self.last_activity = max(ts_list)
                elif self.meta_path.exists():
                    self.last_activity = self.meta_path.stat().st_mtime
            except Exception:
                pass

    def save_meta(self) -> None:
        payload = {
            "id": self.sid,
            "model": self.model,
            "effort": self.effort,
            "conversation_id": self.conversation_id,
            "history": self.history[-80:],
            "successor_session_id": getattr(self, "successor_session_id", "") or "",
            "predecessor_session_id": getattr(self, "predecessor_session_id", "") or "",
            "handoff_summary": getattr(self, "handoff_summary", "") or "",
            "handoff_injected": getattr(self, "handoff_injected", False),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.meta_path)

    def _emit(self, event: dict) -> None:
        self.last_activity = _now()
        try:
            self.events.put_nowait(event)
        except Exception:
            pass
        with self.lock:
            for q in list(self.subscribers):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

    def _spawn(self) -> None:
        self.stop(notify=False)
        adopted = None
        if self.conversation_id is None and self.model == DEFAULT_MODEL and not self.effort:
            adopted = STANDBY_POOL.try_take()
        if adopted is not None:
            self.proc = adopted
            self._emit({"event": "system", "text": f"agy started model={self.model} (warm standby, skip-permissions, accept-edits, NAS)"})
        else:
            args = self.adapter.build_args(self.model, self.effort, self.conversation_id, ADD_DIRS)
            env = self.adapter.build_env(HOME)
            self.proc = subprocess.Popen(
                args,
                cwd=str(WORKSPACE),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            self._emit({"event": "system", "text": f"agy started model={self.model} (skip-permissions, accept-edits, NAS)"})
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _maybe_capture_conversation_id(self, obj: dict) -> None:
        if self.conversation_id:
            return
        sources = [obj]
        step = obj.get("step_update")
        if isinstance(step, dict):
            sources.append(step)
        result = obj.get("result")
        if isinstance(result, dict):
            sources.append(result)
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in ("conversation_id", "session_id", "id"):
                val = source.get(key)
                if isinstance(val, str) and len(val) >= 8 and not self.conversation_id:
                    # avoid capturing random short ids / step ids that aren't conversations
                    if key == "id" and source is obj and obj.get("event") not in (None, "result", "system"):
                        continue
                    self.conversation_id = val
                    self.save_meta()
                    self._emit({"event": "system", "text": f"conversation_id={val}"})
                    return

    def _clean_str(self, val: Any) -> str:
        if val is None:
            return ""
        s = str(val).strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
        return s

    def _short_path(self, p: str) -> str:
        if not p:
            return ""
        p = p.replace("/volume1/homes/me/", "")
        p = p.replace("/volume1/web/", "web/")
        return p

    def _format_tool_call(self, name: str, args: dict) -> str:
        if not isinstance(args, dict):
            return name
        action = self._clean_str(args.get("toolAction") or args.get("action"))
        summary = self._clean_str(args.get("toolSummary") or args.get("summary") or args.get("description"))

        if name == "run_command":
            cmd = self._clean_str(args.get("CommandLine") or args.get("command") or args.get("cmd"))
            parts = [f"run_command: {cmd}"]
            if summary and summary.lower() != cmd.lower():
                parts.append(f"({summary})")
            elif action and action.lower() != cmd.lower():
                parts.append(f"({action})")
            return " ".join(parts)

        if name in ("view_file", "read_file"):
            raw_path = self._clean_str(args.get("AbsolutePath") or args.get("TargetFile") or args.get("path") or args.get("file"))
            path = self._short_path(raw_path)
            start = args.get("StartLine")
            end = args.get("EndLine")
            line_info = f" [L{start}-{end}]" if (start or end) else ""
            parts = [f"view_file: {path}{line_info}"]
            if summary:
                parts.append(f"({summary})")
            elif action:
                parts.append(f"({action})")
            return " ".join(parts)

        if name == "grep_search":
            q = self._clean_str(args.get("Query") or args.get("query") or args.get("pattern"))
            sp = self._short_path(self._clean_str(args.get("SearchPath") or args.get("path")))
            parts = [f"grep_search: '{q}' in {sp or '.'}"]
            if summary:
                parts.append(f"({summary})")
            return " ".join(parts)

        if name == "find_by_name":
            p = self._clean_str(args.get("Pattern") or args.get("pattern"))
            sd = self._short_path(self._clean_str(args.get("SearchDirectory") or args.get("directory") or args.get("path")))
            parts = [f"find_by_name: '{p}' in {sd or '.'}"]
            if summary:
                parts.append(f"({summary})")
            return " ".join(parts)

        if name == "list_dir":
            dp = self._short_path(self._clean_str(args.get("DirectoryPath") or args.get("path") or args.get("dir")))
            parts = [f"list_dir: {dp}"]
            if summary:
                parts.append(f"({summary})")
            return " ".join(parts)

        if name in ("replace_file_content", "edit_file"):
            raw_path = self._clean_str(args.get("TargetFile") or args.get("path") or args.get("file"))
            tf = self._short_path(raw_path)
            inst = self._clean_str(args.get("Instruction") or summary or action)
            parts = [f"replace_file_content: {tf}"]
            if inst:
                parts.append(f"({inst})")
            return " ".join(parts)

        if name in ("write_to_file", "write_file"):
            raw_path = self._clean_str(args.get("TargetFile") or args.get("path") or args.get("file"))
            tf = self._short_path(raw_path)
            desc = self._clean_str(args.get("Description") or summary or action)
            parts = [f"write_to_file: {tf}"]
            if desc:
                parts.append(f"({desc})")
            return " ".join(parts)

        if name in ("read_url_content", "fetch_url"):
            url = self._clean_str(args.get("Url") or args.get("url"))
            return f"read_url: {url}"

        if name in ("search_web", "web_search"):
            q = self._clean_str(args.get("query") or args.get("Query"))
            return f"search_web: '{q}'"

        if name == "call_mcp_tool":
            server = self._clean_str(args.get("ServerName"))
            tool = self._clean_str(args.get("ToolName"))
            mcp_args = args.get("Arguments")
            mcp_desc = ""
            if isinstance(mcp_args, dict):
                for k in ("path", "command", "query", "action"):
                    if k in mcp_args:
                        mcp_desc = f"{k}={mcp_args[k]}"
                        break
            return f"mcp: {server}/{tool}" + (f" ({mcp_desc})" if mcp_desc else "")

        target = ""
        for k in ("path", "file", "AbsolutePath", "TargetFile", "command", "CommandLine", "query", "Query", "pattern", "url", "Url", "DirectoryPath"):
            if k in args:
                target = self._short_path(self._clean_str(args[k]))
                break
        desc = summary or action
        res = f"{name}"
        if target:
            res += f": {target}"
        if desc and desc.lower() != target.lower():
            res += f" ({desc})"
        return res

    def _format_tool_result(self, content: str) -> str:
        if not content:
            return ""
        lines = [l.strip() for l in str(content).splitlines() if l.strip()]
        filtered = [l for l in lines if not l.startswith("Created At:") and not l.startswith("Completed At:")]
        if not filtered:
            return "↳ 완료"
        first = filtered[0]
        if len(first) > 120:
            first = first[:117] + "..."
        if len(filtered) > 1:
            return f"↳ {first} (외 {len(filtered)-1}줄)"
        return f"↳ {first}"

    def _tool_summary(self, obj: dict) -> Union[dict, List[dict], None]:
        """Surface tool activity with detailed arguments and results."""
        SKIP_TOOL_NOISE = {"", "tool", "step", "step_update", "unknown", "agent_response"}
        if not hasattr(self, "_last_tool_sig"):
            self._last_tool_sig = None

        # 1. Antigravity PLANNER_RESPONSE with tool_calls
        tool_calls = obj.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            events = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = str(tc.get("name") or "").strip()
                    args = tc.get("args") or tc.get("input") or {}
                    if not isinstance(args, dict):
                        args = {}
                    text = self._format_tool_call(name, args)
                    if text and text != self._last_tool_sig:
                        self._last_tool_sig = text
                        events.append({"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": "calling"})
            if events:
                return events

        # 2. Antigravity GENERIC tool execution result
        if obj.get("type") == "GENERIC" and isinstance(obj.get("content"), str) and obj.get("content").strip():
            res_summary = self._format_tool_result(obj["content"])
            if res_summary and res_summary != self._last_tool_sig:
                self._last_tool_sig = res_summary
                return {"event": "tool", "text": res_summary[:600], "title": "result", "kind": "result", "status": "done"}

        # 3. step_update format
        step = obj.get("step_update")
        if isinstance(step, dict):
            stype = str(step.get("step_type") or step.get("type") or "").strip()
            if stype in ("agent_response",):
                return None
            title = (
                step.get("title")
                or step.get("name")
                or step.get("tool")
                or step.get("tool_name")
                or step.get("function")
                or ""
            )
            step_args = {}
            for nest in (step.get("tool_call"), step.get("toolUse"), step.get("args"), step.get("input")):
                if isinstance(nest, dict):
                    title = title or nest.get("name") or nest.get("tool") or nest.get("Name") or ""
                    tc = nest.get("toolCall")
                    if not title and isinstance(tc, dict):
                        title = tc.get("name") or ""
                    step_args.update(nest)
            title = str(title or "").strip()
            status = str(step.get("status") or step.get("state") or "").strip()

            blob = json.dumps(step, ensure_ascii=False)
            if "generate_image" in blob.lower() or "image" in title.lower():
                for src in self._collect_new_images(self.turn_started_at or None):
                    url = self._stage_image(src)
                    if url and url not in self.pending_images:
                        self.pending_images.append(url)
                        self._emit({"event": "image", "text": url, "url": url, "name": src.name})

            if title and title.lower() not in SKIP_TOOL_NOISE:
                text = self._format_tool_call(title, step_args if step_args else step)
            else:
                text = ""
                for k in ("command", "CommandLine", "path", "query", "text", "summary", "description"):
                    val = step.get(k)
                    if isinstance(val, str) and val.strip():
                        text = val.strip()[:400]
                        break
                if not text and stype and stype.lower() not in SKIP_TOOL_NOISE:
                    text = stype
            if not text or text == self._last_tool_sig:
                return None
            self._last_tool_sig = text
            return {"event": "tool", "text": text[:600], "step_type": stype[:80], "title": title[:200] or stype[:80], "kind": "call", "status": status[:80]}

        # 4. classic tool_use / tool_call / tool_result / tool_error
        ev = obj.get("event") or obj.get("type")
        if ev in ("tool_use", "tool_call"):
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            args = obj.get("args") or obj.get("input") or obj.get("parameters") or {}
            if not isinstance(args, dict):
                args = {}
            text = self._format_tool_call(name, args) if args else f"{name}"
            if not text or text.lower() in SKIP_TOOL_NOISE:
                return None
            if text == self._last_tool_sig:
                return None
            self._last_tool_sig = text
            return {"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": str(ev)}

        if ev in ("tool_result", "tool_error"):
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            content = obj.get("output") or obj.get("content") or obj.get("result") or ""
            if isinstance(content, dict):
                content = json.dumps(content, ensure_ascii=False)
            res_text = self._format_tool_result(str(content)) if content else f"{ev}: {name or 'done'}"
            if res_text == self._last_tool_sig:
                return None
            self._last_tool_sig = res_text
            return {"event": "tool", "text": res_text[:600], "title": name[:200] or "result", "kind": "result", "status": str(ev)}

        # 5. nested message tool_use / tool_result blocks
        msg = obj.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list):
                events = []
                for part in content:
                    if isinstance(part, dict):
                        ptype = part.get("type")
                        if ptype == "tool_use":
                            name = str(part.get("name") or "").strip()
                            args = part.get("input") or {}
                            text = self._format_tool_call(name, args if isinstance(args, dict) else {})
                            if text and text != self._last_tool_sig:
                                self._last_tool_sig = text
                                events.append({"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": "tool_use"})
                        elif ptype == "tool_result":
                            res = str(part.get("content") or part.get("output") or "")
                            text = self._format_tool_result(res) if res else "↳ tool_result: 완료"
                            if text and text != self._last_tool_sig:
                                self._last_tool_sig = text
                                events.append({"event": "tool", "text": text[:600], "title": "result", "kind": "result", "status": "tool_result"})
                if events:
                    return events
        return None


    def _rewrite_artifact_paths(self, text: str) -> str:
        if not text:
            return text

        def repl_path(m: re.Match) -> str:
            raw = m.group(0)
            # map absolute brain/workspace media paths to /artifacts/...
            for prefix, label in (
                (str(BRAIN) + "/", "brain/"),
                (str(WORKSPACE / "artifacts") + "/", ""),
                (str(ARTIFACTS_CACHE) + "/", ""),
                (str(WORKSPACE) + "/", ""),
            ):
                if raw.startswith(prefix):
                    rel = label + raw[len(prefix):] if label.startswith("brain") else raw[len(prefix):]
                    # copy into artifacts cache for stable serving when under brain
                    try:
                        src = Path(raw)
                        if src.is_file() and label.startswith("brain"):
                            dest = ARTIFACTS_CACHE / "brain" / src.name
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
                                shutil.copy2(src, dest)
                            return f"/artifacts/brain/{src.name}"
                    except Exception:
                        pass
                    return "/artifacts/" + rel.lstrip("/")
            return raw

        # file:// and absolute paths ending with media extensions
        text = re.sub(
            r"(?:file://)?(/volume1/homes/me/\.gemini/antigravity-cli/brain/[^\s\)\"']+\.(?:png|jpe?g|gif|webp|svg|mp4|webm))",
            repl_path,
            text,
            flags=re.I,
        )
        text = re.sub(
            r"(?:file://)?(/volume1/homes/me/services/chatbot-data/(?:workspace/)?artifacts/[^\s\)\"']+)",
            repl_path,
            text,
            flags=re.I,
        )
        return text


    def _conversation_brain_dir(self) -> Optional[Path]:
        if not self.conversation_id:
            return None
        d = BRAIN / self.conversation_id
        return d if d.is_dir() else None

    def _collect_new_images(self, since_ts: Optional[float] = None) -> list:
        """Find recent image files for this conversation / workspace."""
        exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        found: List[Path] = []
        roots = []
        bdir = self._conversation_brain_dir()
        if bdir:
            roots.append(bdir)
            roots.append(bdir / ".tempmediaStorage")
            roots.append(bdir / ".system_generated")
        roots.append(WORKSPACE / "artifacts")
        roots.append(ARTIFACTS_CACHE)
        cutoff = since_ts or (self.last_activity - 600)
        for root in roots:
            if not root or not Path(root).exists():
                continue
            try:
                for fp in Path(root).rglob("*"):
                    if not fp.is_file():
                        continue
                    if fp.suffix.lower() not in exts:
                        continue
                    try:
                        if fp.stat().st_mtime >= cutoff - 5:
                            found.append(fp)
                    except OSError:
                        continue
            except Exception:
                continue
        # newest first, unique by name and size
        found.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        uniq = []
        seen_names = set()
        seen_sizes = set()
        for fp in found:
            if fp.name in seen_names:
                continue
            try:
                sz = fp.stat().st_size
                if sz in seen_sizes and sz > 5000:
                    continue
                seen_sizes.add(sz)
            except OSError:
                pass
            seen_names.add(fp.name)
            uniq.append(fp)
        return uniq[:8]

    def _stage_image(self, src: Path) -> Optional[str]:
        try:
            dest_dir = ARTIFACTS_CACHE / "brain"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
                shutil.copy2(src, dest)
            return f"/artifacts/brain/{src.name}"
        except Exception:
            return None

    def _append_images_markdown(self, text: str, since_ts: Optional[float] = None) -> str:
        text = text or ""
        imgs = self._collect_new_images(since_ts)
        if not imgs:
            return text
        existing_imgs = re.findall(r"!\[.*?\]\((.*?)\)", text)
        existing_stems = {Path(u.split("?")[0]).stem.lower() for u in existing_imgs}
        lines = []
        for src in imgs:
            if src.stem.lower() in existing_stems:
                continue
            url = self._stage_image(src)
            if not url:
                continue
            if url in text:
                continue
            existing_stems.add(src.stem.lower())
            lines.append(f"![{src.stem}]({url})")
        if not lines:
            return text
        sep = "\n\n" if text.strip() else ""
        return text.rstrip() + sep + "\n".join(lines) + "\n"

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                self._emit({"event": "raw", "text": line[:2000]})
                continue
            if not isinstance(obj, dict):
                continue
            self._maybe_capture_conversation_id(obj)

            tool_ev = self._tool_summary(obj)
            if tool_ev:
                if isinstance(tool_ev, list):
                    for tev in tool_ev:
                        self._emit(tev)
                else:
                    self._emit(tool_ev)

            ev = obj.get("event") or obj.get("type") or "message"
            text = ""
            step = obj.get("step_update")
            if isinstance(step, dict) and step.get("step_type") == "agent_response" and isinstance(step.get("text_delta"), str):
                text = step.get("text_delta") or ""
                ev = "delta"
                self.current_text += text
            if isinstance(obj.get("text"), str) and not text:
                text = obj["text"]
            msg = obj.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    bits = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            bits.append(str(part.get("text") or ""))
                        elif isinstance(part, str):
                            bits.append(part)
                    if bits:
                        text = "".join(bits)
            delta = obj.get("delta") or obj.get("content_block_delta")
            if isinstance(delta, dict) and delta.get("text"):
                text = str(delta.get("text"))
                ev = "delta"
                self.current_text += text

            if text:
                text = self._rewrite_artifact_paths(text)

            if ev == "result":
                final = self._rewrite_artifact_paths(self.current_text or text)
                final = self._append_images_markdown(final, self.turn_started_at or None)
                # also pending image urls from tool events
                for url in list(getattr(self, "pending_images", []) or []):
                    if url and url not in final:
                        final = (final.rstrip() + f"\n\n![]({url})\n") if final.strip() else f"![]({url})\n"
                if final:
                    self.history.append({"role": "assistant", "text": final, "ts": _now()})
                    self.save_meta()
                text = final
                self.current_text = ""
                self.pending_images = []

            if ev in ("result", "assistant", "message", "delta", "error", "system") or (ev in ("tool_use", "tool_result") and not tool_ev):
                out = {"event": ev, "text": text, "raw_event": ev}
                if obj.get("error"):
                    out["error"] = obj.get("error")
                self._emit(out)
            elif not tool_ev:
                self._emit({"event": "agy", "text": text, "payload": {k: obj.get(k) for k in list(obj)[:12]}})
            if ev in ("result", "error"):
                self.busy = False
                try:
                    self._emit_heavy_if_needed()
                except Exception:
                    pass
                with self.lock:
                    has_queued = bool(getattr(self, "msg_queue", []))
                if has_queued:
                    threading.Thread(target=self._dispatch_queued, daemon=True).start()

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            self._stderr_tail.append(line[-500:])
            self._stderr_tail = self._stderr_tail[-30:]
            low = line.lower()
            if any(x in low for x in ("token", "authorization", "bearer", "api_key", "refresh")):
                continue
            # Surface jetski/sandbox denials as tool events for visibility
            if "jetski" in low or "sandbox" in low or "soft-denying" in low or "permission" in low:
                self._emit({"event": "tool", "text": line[:500], "title": "permission", "status": "stderr"})
            else:
                self._emit({"event": "stderr", "text": line[:500]})

    def ensure(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            self._spawn()

    def _dispatch_queued(self) -> None:
        time.sleep(0.35)
        with self.lock:
            if not getattr(self, "msg_queue", []):
                return
            next_text = self.msg_queue.pop(0)
        self._send_direct(next_text)

    def _run_btw(self, query: str) -> None:
        query = (query or "").strip()
        if not query:
            self._emit({"event": "btw", "query": "", "text": "실장님, `/btw <질문 내용>` 형태로 궁금한 점을 적어주세요냥!"})
            return
        self._emit({"event": "btw_start", "query": query})
        context_snippets = []
        with self.lock:
            cur_tool = getattr(self, "_last_tool_sig", "") or ""
            recent_hist = [f"{h.get('role')}: {str(h.get('text') or '')[:120]}" for h in self.history[-4:] if h.get("role") in ("user", "assistant")]
        if cur_tool:
            context_snippets.append(f"[현재 백그라운드 진행 중인 메인 작업: {cur_tool}]")
        if recent_hist:
            context_snippets.append("[최근 대화 맥락:\n" + "\n".join(recent_hist) + "]")

        prompt = (
            "Sphere DiskStation 냥피디(냥PD)입니다. (사용자: 실장님)\n"
            "백그라운드 메인 작업 진행 중 들어온 샛길 질문(/btw)입니다.\n"
            + ("\n".join(context_snippets) + "\n" if context_snippets else "")
            + f"실장님 질문: {query}\n\n"
            "메인 작업을 방해하지 않는 핵심만 2~3문장의 친근한 냥피디 말투(~냥, ✦)로 간결하게 즉답하세요."
        )
        cmd = [
            AGY, "-p", prompt,
            "--model", "gemini-3.8-flash-low",
            "--dangerously-skip-permissions",
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
            ans = res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else (res.stderr.strip() or "답변을 가져오지 못했습니다냥.")
        except subprocess.TimeoutExpired:
            ans = "간이 질문 응답 시간이 초과되었습니다냥."
        except Exception as e:
            ans = f"간이 질문 처리 중 오류가 발생했습니다: {e}"

        with self.lock:
            self.history.append({"role": "btw", "query": query, "text": ans, "ts": _now()})
            self.save_meta()
        self._emit({"event": "btw", "query": query, "text": ans})

    def weight(self) -> dict:
        return _session_weight(self.history, self.conversation_id)

    def get_handover_summary(self, max_turns: int = 8) -> str:
        """Extract a lean, compact 3~5 line handoff memo from history."""
        if getattr(self, "_cached_summary", ""):
            return self._cached_summary

        dialogue = []
        with self.lock:
            for h in self.history:
                role = h.get("role")
                text = str(h.get("text") or "").strip()
                if not text:
                    continue
                if role in ("user", "assistant"):
                    dialogue.append(f"{role}: {text[:250]}")
                elif role == "btw":
                    dialogue.append(f"user(btw): {str(h.get('query') or '')[:100]} -> {text[:150]}")

        if not dialogue:
            return ""
        if len(dialogue) <= 1:
            return dialogue[0]

        recent_dialogue = dialogue[-max_turns:]
        dialogue_blob = "\n".join(recent_dialogue)

        prompt = (
            "Sphere DiskStation 냥피디 챗봇 인계 요약기입니다.\n"
            "다음 대화 내역을 바탕으로 새 세션에 전달할 핵심 맥락을 3~4줄 내외로 한국어로 간결하게 요약하세요.\n\n"
            "[대화 내역]\n"
            f"{dialogue_blob}\n\n"
            "[작성 양식]\n"
            "- 진행 중인 핵심 주제:\n"
            "- 확인/결정된 사항 및 파일:\n"
            "- 실장님의 최근 요구사항:"
        )

        cmd = [
            AGY, "-p", prompt,
            "--model", "gemini-3.8-flash-low",
            "--dangerously-skip-permissions",
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=12,
            )
            summary = res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else ""
            if summary:
                self._cached_summary = summary
                return summary
        except Exception:
            pass

        # Deterministic fallback if subprocess fails or times out
        user_turns = [h.get("text") for h in self.history if h.get("role") == "user"]
        asst_turns = [h.get("text") for h in self.history if h.get("role") == "assistant"]
        last_u = str(user_turns[-1] if user_turns else "")[:120]
        last_a = str(asst_turns[-1] if asst_turns else "")[:120]
        fallback = f"- 최근 실장님 지시: {last_u}\n- 최근 답변 요약: {last_a}"
        self._cached_summary = fallback
        return fallback

    def _precompute_summary(self) -> None:
        if getattr(self, "_summary_generating", False) or getattr(self, "_cached_summary", ""):
            return
        self._summary_generating = True
        try:
            self.get_handover_summary()
        finally:
            self._summary_generating = False

    def _emit_heavy_if_needed(self, force: bool = False) -> dict:
        w = self.weight()
        level = w.get("level") or "ok"
        if level in ("soft", "hard") and not getattr(self, "_cached_summary", ""):
            threading.Thread(target=self._precompute_summary, daemon=True).start()
        if level == "ok":
            return w
        if force or self._heavy_warned_level != level:
            self._heavy_warned_level = level
            self._emit({
                "event": "session_heavy",
                "level": level,
                "text": w.get("message_ko") or "세션이 길어져서 느려질 수 있어요. 새 채팅을 권장합니다",
                "weight": w,
            })
        return w

    def _successor_usable(self, sid: str) -> bool:
        """True if sid resolves to a non-hard session with meta on disk."""
        sid = (sid or "").strip()
        if not sid or sid == self.sid:
            return False
        try:
            meta_path = SESSIONS / f"{sid}.json"
            if not meta_path.exists():
                return False
            succ = REG.get(sid)
            w = succ.weight() if hasattr(succ, "weight") else {}
            if (w.get("level") or "ok") == "hard":
                return False
            return True
        except Exception:
            return False

    def _rotate_to_fresh_session(self, text: str, reason: str = "heavy") -> "AgySession":
        """Sticky rotate: reuse successor_session_id when usable; else create once and remember with handover."""
        if reason == "inactivity":
            msg = (
                "이전 대화 이후 시간이 경과하여 이전 맥락을 인계받아 새 세션으로 이어갑니다냥 ✦ (이전 대화는 보존됩니다)"
            )
        else:
            msg = (
                "세션이 길어져서 이전 맥락을 인계받아 새 채팅으로 전환합니다. 이전 세션 데이터는 그대로 보존됩니다냥 ✦"
            )
        succ_id = getattr(self, "successor_session_id", "") or ""
        if succ_id and self._successor_usable(succ_id):
            new_sess = REG.get(succ_id)
        else:
            summary = self.get_handover_summary()
            new_sess = REG.create(
                model=self.model,
                effort=self.effort,
                predecessor_sid=self.sid,
                handoff_summary=summary,
            )
            self.successor_session_id = new_sess.sid
            try:
                self.save_meta()
            except Exception:
                pass
        self._emit({
            "event": "session_rotate",
            "text": msg,
            "reason": reason,
            "new_session_id": new_sess.sid,
            "weight": self.weight(),
            "handoff_summary": getattr(new_sess, "handoff_summary", ""),
        })
        try:
            self.stop(notify=False)
        except Exception:
            pass
        new_sess._send_direct(text)
        return new_sess

    def send(self, text: str):
        """Return None (same session) or AgySession if hard-rotated to a fresh session."""
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")

        if text.startswith("/btw ") or text.startswith("/btw\n") or text == "/btw":
            query = text[4:].strip()
            threading.Thread(target=self._run_btw, args=(query,), daemon=True).start()
            return None

        # Soft warn anytime; hard rotate before appending more to bloated conversation.
        # Skip rotate for doctor probes and queued follow-ups while busy.
        w = self._emit_heavy_if_needed()
        is_probe = text.strip().startswith("[doctor-probe]")
        if (w.get("level") == "hard") and (not is_probe) and (not self.busy):
            return self._rotate_to_fresh_session(text, reason="heavy")

        # Inactivity auto-rotate: if session had prior conversation and was inactive > INACTIVITY_ROTATE_SEC
        user_or_asst_turns = [h for h in self.history if h.get("role") in ("user", "assistant")]
        time_since_active = _now() - getattr(self, "last_activity", _now())
        if len(user_or_asst_turns) >= 2 and (time_since_active >= INACTIVITY_ROTATE_SEC) and (not is_probe) and (not self.busy):
            return self._rotate_to_fresh_session(text, reason="inactivity")

        with self.lock:
            if self.busy:
                if _is_inquiry(text):
                    threading.Thread(target=self._run_btw, args=(text,), daemon=True).start()
                    return None
                if not hasattr(self, "msg_queue"):
                    self.msg_queue = []
                self.msg_queue.append(text)
                self.history.append({"role": "user", "text": text, "ts": _now(), "queued": True})
                self.save_meta()
                self._emit({"event": "queued", "text": text, "queue_len": len(self.msg_queue)})
                return None

        self._send_direct(text)
        return None

    def _send_direct(self, text: str) -> None:
        self.ensure()
        assert self.proc and self.proc.stdin

        stdin_content = text
        with self.lock:
            if not getattr(self, "handoff_injected", False) and getattr(self, "handoff_summary", ""):
                pred = getattr(self, "predecessor_session_id", "") or "이전"
                stdin_content = (
                    f"[이전 세션({pred[:8]}) 인계 맥락]\n"
                    f"{self.handoff_summary}\n"
                    f"--------------------------------------------------\n"
                    f"[실장님의 현재 메시지]\n"
                    f"{text}"
                )
                self.handoff_injected = True
                self._emit({
                    "event": "system",
                    "text": f"이전 세션({pred[:8]}) 맥락을 인계받아 대화를 시작했습니다냥 ✦",
                })

        payload = self.adapter.format_stdin(stdin_content)
        with self.lock:
            self.busy = True
            self.current_text = ""
            self.turn_started_at = _now()
            self.pending_images = []
            self.history.append({"role": "user", "text": text, "ts": _now()})
            self.proc.stdin.write(payload)
            self.proc.stdin.flush()
            self.last_activity = _now()
            self.save_meta()
        self._emit({"event": "user_ack", "text": text})

    def stop(self, notify: bool = True) -> None:
        proc = self.proc
        self.proc = None
        with self.lock:
            if hasattr(self, "msg_queue"):
                self.msg_queue.clear()
            self.busy = False
        if proc:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if notify:
            self._emit({"event": "stopped", "text": "실장님의 요청으로 작업이 중지되었습니다냥."})

    def to_public(self) -> dict:
        out = {
            "id": self.sid,
            "model": self.model,
            "effort": self.effort,
            "conversation_id": self.conversation_id,
            "busy": self.busy,
            "queue_len": len(getattr(self, "msg_queue", [])),
            "alive": bool(self.proc and self.proc.poll() is None),
            "history": self.history[-40:],
            "updated_at": self.meta_path.stat().st_mtime if self.meta_path.exists() else self.last_activity,
            "class": "NAS agent (VibeCat-class)",
            "weight": self.weight(),
            "add_dirs": [d for d in ADD_DIRS if Path(d).exists()],
        }
        if not out["alive"] and self._stderr_tail:
            out["debug_stderr_tail"] = self._stderr_tail[-15:]
        w = out.get("weight") or {}
        succ = getattr(self, "successor_session_id", "") or ""
        if succ:
            out["successor_session_id"] = succ
            if (w.get("level") or "") == "hard":
                out["redirect_session_id"] = succ
        pred = getattr(self, "predecessor_session_id", "") or ""
        if pred:
            out["predecessor_session_id"] = pred
            out["has_handover"] = bool(getattr(self, "handoff_summary", ""))
            out["handoff_summary"] = getattr(self, "handoff_summary", "")
        return out

    def get_artifacts(self) -> List[dict]:
        exts_img = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
        exts_doc = {".md", ".txt", ".json", ".pdf", ".html", ".csv", ".yaml", ".yml"}
        exts_code = {".py", ".js", ".ts", ".gd", ".sh", ".sql", ".css"}

        roots = []
        bdir = self._conversation_brain_dir()
        if bdir:
            roots.append(bdir)
            roots.append(bdir / ".tempmediaStorage")
        roots.append(WORKSPACE / "artifacts")
        roots.append(ARTIFACTS_CACHE)
        roots.append(DATA / "persona" / "gallery")

        found = []
        seen_sizes = set()
        seen_names = set()

        for root in roots:
            if not root or not Path(root).exists():
                continue
            try:
                for fp in Path(root).rglob("*"):
                    if not fp.is_file() or fp.name.startswith("."):
                        continue
                    if any(part.startswith(".") for part in fp.parts[:-1]):
                        continue
                    suffix = fp.suffix.lower()
                    if suffix not in exts_img and suffix not in exts_doc and suffix not in exts_code:
                        continue
                    try:
                        sz = fp.stat().st_size
                    except OSError:
                        continue
                    if sz in seen_sizes and sz > 5000:
                        continue
                    if fp.name in seen_names:
                        continue
                    seen_sizes.add(sz)
                    seen_names.add(fp.name)

                    kind = "image" if suffix in exts_img else ("document" if suffix in exts_doc else "code")
                    url = self._stage_image(fp) if kind == "image" else f"/artifacts/{fp.name}"

                    if sz >= 1024 * 1024:
                        sz_str = f"{sz / (1024 * 1024):.1f} MB"
                    elif sz >= 1024:
                        sz_str = f"{sz / 1024:.0f} KB"
                    else:
                        sz_str = f"{sz} B"

                    mtime = fp.stat().st_mtime
                    found.append({
                        "name": fp.name,
                        "stem": fp.stem,
                        "kind": kind,
                        "ext": suffix.lstrip("."),
                        "size": sz,
                        "size_human": sz_str,
                        "url": url or f"/artifacts/{fp.name}",
                        "mtime": mtime,
                        "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
                    })
            except Exception:
                continue

        found.sort(key=lambda x: x["mtime"], reverse=True)
        return found


class Registry:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sessions: Dict[str, AgySession] = {}

    def create(
        self,
        model: str = DEFAULT_MODEL,
        effort: str = "",
        predecessor_sid: str = "",
        handoff_summary: str = "",
    ) -> AgySession:
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        sess = AgySession(sid, model=model, effort=effort)
        sess.predecessor_session_id = predecessor_sid
        sess.handoff_summary = handoff_summary
        sess.handoff_injected = False
        sess.save_meta()
        with self.lock:
            self.sessions[sid] = sess
        return sess

    def get(self, sid: str) -> AgySession:
        sid = _safe_session_id(sid)
        with self.lock:
            if sid in self.sessions:
                return self.sessions[sid]
            sess = AgySession(sid)
            self.sessions[sid] = sess
            return sess

    def list(self) -> List[dict]:
        items = []
        for p in sorted(SESSIONS.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:40]:
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
                items.append({
                    "id": meta.get("id") or p.stem,
                    "model": meta.get("model"),
                    "updated_at": meta.get("updated_at"),
                    "preview": (meta.get("history") or [{}])[-1:].pop().get("text", "")[:80] if meta.get("history") else "",
                })
            except Exception:
                continue
        return items

    def get_active(self) -> AgySession:
        with self.lock:
            # 1st pass: most recently active session with real conversation history
            for p in sorted(SESSIONS.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    meta = json.loads(p.read_text(encoding="utf-8"))
                    hist = meta.get("history") or []
                    if not hist:
                        continue
                    if len(hist) <= 2:
                        sample = " ".join(str(h.get("text") or "") for h in hist)
                        if "[doctor-probe]" in sample or "[diag]" in sample:
                            continue
                    sid = meta.get("id") or p.stem
                    sess = self.get(sid)
                    succ = getattr(sess, "successor_session_id", "")
                    if succ and sess._successor_usable(succ):
                        return self.get(succ)
                    return sess
                except Exception:
                    continue
            # 2nd pass: if all are empty shells, reuse the newest valid session
            for p in sorted(SESSIONS.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    meta = json.loads(p.read_text(encoding="utf-8"))
                    sid = meta.get("id") or p.stem
                    return self.get(sid)
                except Exception:
                    continue
            return self.create()


REG = Registry()


def _json_bytes(obj: Any, code: int = 200):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return code, raw


_SKILLS_CACHE = {"ts": 0.0, "data": []}
_USAGE_CACHE = {"ts": 0.0, "data": None}
USAGE_CACHE_TTL_SEC = 300


def _get_usage(force: bool = False) -> dict:
    """Run `agy --print /usage` (the CLI's own rate-limit report; unavailable inside
    a stream-json session — must be a separate one-shot invocation) and parse its
    tab-separated output. Cached for USAGE_CACHE_TTL_SEC since each check is a real
    network round-trip, not free."""
    now = time.time()
    if not force and (now - _USAGE_CACHE["ts"] < USAGE_CACHE_TTL_SEC) and _USAGE_CACHE["data"]:
        return _USAGE_CACHE["data"]
    try:
        proc = subprocess.run([AGY, "--print", "/usage"], capture_output=True, text=True, timeout=30)
        rows = []
        for line in (proc.stdout or "").splitlines():
            parts = [p.strip() for p in line.split("\t")]
            if len(parts) >= 4:
                rows.append({"group": parts[0], "limit_type": parts[1], "remaining_pct": parts[2], "reset_at": parts[3]})
        data = {"ok": True, "rows": rows, "checked_at": now}
        if not rows and proc.stderr:
            data = {"ok": False, "error": proc.stderr.strip()[:400], "checked_at": now}
    except Exception as e:
        data = {"ok": False, "error": str(e), "checked_at": now}
    _USAGE_CACHE["ts"] = now
    _USAGE_CACHE["data"] = data
    return data


def _extract_yaml_desc(txt: str) -> str:
    """Parse a SKILL.md frontmatter `description:` field, handling both inline
    values and YAML folded/literal block scalars (`description: >` / `|`)."""
    m = re.search(r"^description:\s*(.*)$", txt, re.MULTILINE)
    if not m:
        return ""
    first = m.group(1).strip()
    if first in (">", "|", ">-", "|-", ">+", "|+", ""):
        block = []
        for line in txt[m.end():].splitlines():
            if not line.strip():
                if first.startswith("|"):
                    block.append("")
                continue
            if line[:1] in (" ", "\t"):
                block.append(line.strip())
            else:
                break
        return ("\n".join(block) if first.startswith("|") else " ".join(block)).strip()
    if len(first) >= 2 and first[0] == first[-1] and first[0] in ('"', "'"):
        first = first[1:-1]
    return first


def _get_available_skills() -> list:
    now = time.time()
    if now - _SKILLS_CACHE["ts"] < 60 and _SKILLS_CACHE["data"]:
        return _SKILLS_CACHE["data"]
    skills_dir = Path("/volume1/homes/me/.agents/skills")
    results = []
    if skills_dir.exists():
        for p in sorted(skills_dir.iterdir()):
            if p.name.startswith((".", "_")):
                continue
            if p.is_dir() or p.is_symlink():
                sm = p / "SKILL.md"
                desc = ""
                if sm.exists():
                    try:
                        desc = _extract_yaml_desc(sm.read_text(encoding="utf-8", errors="replace")[:2000])
                    except Exception:
                        pass
                results.append({"name": p.name, "desc": desc, "template": f"/skill {p.name} "})
    _SKILLS_CACHE["ts"] = now
    _SKILLS_CACHE["data"] = results
    return results


RULE_FILES = ["AGENTS.md", "PERSONA.md", "PROJECT.md", "SELF-MODIFY.md"]
WS_SKILLS_DIR = WORKSPACE / ".agents" / "skills"


def _rule_path(name: str) -> Optional[Path]:
    if name not in RULE_FILES:
        return None
    return WORKSPACE / name


def _skill_desc(skill_md: Path) -> str:
    try:
        return _extract_yaml_desc(skill_md.read_text(encoding="utf-8", errors="replace")[:2000])
    except Exception:
        return ""


def _get_workspace_skills() -> list:
    """Project-scoped skills (chatbot-self-improve, nas-sphere, task-observer, ...).
    Disabled skills are stored with a leading underscore (mirrors _get_available_skills' own skip rule)."""
    results = []
    if WS_SKILLS_DIR.exists():
        for p in sorted(WS_SKILLS_DIR.iterdir()):
            if not p.is_dir():
                continue
            enabled = not p.name.startswith("_")
            name = p.name[1:] if not enabled else p.name
            results.append({"name": name, "enabled": enabled, "desc": _skill_desc(p / "SKILL.md")})
    return results


def _hooks_config_path() -> Path:
    return WORKSPACE / ".agents" / "hooks.json"


def _read_hooks_config() -> dict:
    p = _hooks_config_path()
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                return cfg
        except Exception:
            pass
    return {}


def _mcp_config_path() -> Path:
    return WORKSPACE / ".gemini" / "config" / "mcp_config.json"


def _read_mcp_config() -> dict:
    p = _mcp_config_path()
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cfg, dict) and isinstance(cfg.get("mcpServers"), dict):
                return cfg
        except Exception:
            pass
    return {"mcpServers": {}}


def _write_mcp_config(cfg: dict) -> None:
    p = _mcp_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _self_status() -> dict:
    rules = []
    for name in RULE_FILES:
        fp = WORKSPACE / name
        if not fp.exists():
            continue
        try:
            st = fp.stat()
            text = fp.read_text(encoding="utf-8", errors="replace")
            preview = "\n".join(text.splitlines()[:3])
        except Exception:
            st = None
            preview = ""
        rules.append({
            "name": name,
            "size": st.st_size if st else 0,
            "mtime": st.st_mtime if st else 0,
            "preview": preview,
        })
    mcp_cfg = _read_mcp_config()
    mcp_list = [dict(v, name=k) for k, v in mcp_cfg.get("mcpServers", {}).items()]
    obs_dir = WORKSPACE / "skill-observations" / "observation-log"
    last_review_fp = WORKSPACE / "skill-observations" / "last-review-date.txt"
    n_obs_open = 0
    n_obs_total = 0
    if obs_dir.exists():
        for f in obs_dir.glob("*.md"):
            n_obs_total += 1
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:400]
                if re.search(r"status:\s*open", head):
                    n_obs_open += 1
            except Exception:
                pass
    last_review = "never"
    if last_review_fp.exists():
        try:
            last_review = last_review_fp.read_text(encoding="utf-8").strip() or "never"
        except Exception:
            pass
    return {
        "ok": True,
        "rules": rules,
        "skills": _get_workspace_skills(),
        "host_skill_library_count": len(_get_available_skills()),
        "mcp": mcp_list,
        "hooks": {
            "supported": True,
            "configured": [
                {"name": name, "enabled": bool(cfg.get("enabled", True)), "events": [k for k in cfg.keys() if k != "enabled"]}
                for name, cfg in _read_hooks_config().items()
            ],
            "note": "Antigravity는 PreToolUse/PostToolUse/PreInvocation/PostInvocation/Stop 5종 훅 지원 (SessionStart 전용 이벤트는 없음 — PreInvocation이 대체). 이 워크스페이스 .agents/hooks.json에 실제로 설정돼 있음.",
        },
        "plugins": {
            "note": "이 스택에서 '플러그인'은 별도 개념이 아니라 스킬(.agents/skills) + MCP로 표현됨.",
        },
        "task_observer": {
            "open_observations": n_obs_open,
            "total_observations": n_obs_total,
            "last_review_date": last_review,
        },
    }


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
            subprocess.run(
                ["bash", "/volume1/homes/me/services/chatbot-ctl.sh", "repair"],
                env=env,
                timeout=180,
                check=False,
            )
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "Chatbot/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys_stderr = getattr(__import__("sys"), "stderr")
        sys_stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
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

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/healthz", "/health"):
            ok = shutil.which(AGY) is not None or Path(AGY).exists()
            code, body = _json_bytes({
                "ok": ok,
                "agy": AGY,
                "models": MODELS,
                "class": "NAS agent (VibeCat-class)",
                "skip_permissions": True,
                "mcp_port": 3012,
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
        if path == "/api/models":
            code, body = _json_bytes({"models": MODELS, "default": DEFAULT_MODEL})
            return self._send(code, body, "application/json; charset=utf-8")
        if path in ("/api/skills", "/api/commands"):
            skills = _get_available_skills()
            commands = [
                {"name": "/btw", "label": "샛길 질문", "desc": "작업 중 즉시 경량 샛길 답변", "template": "/btw "},
                {"name": "/continue", "label": "이어하기", "desc": "현재 대화 맥락 인계 새 세션", "template": "/continue"},
                {"name": "/new", "label": "새 세션", "desc": "완전한 새 대화 세션 시작", "template": "/new"},
                {"name": "/defib", "label": "심폐소생", "desc": "⚡ 호스트 전기충격·소생 (repair)", "template": "/defib"},
                {"name": "/status", "label": "상태 확인", "desc": "챗봇 및 NAS 시스템 상태 확인", "template": "/status"},
                {"name": "/clear", "label": "화면 비우기", "desc": "대화창 화면 로그 초기화", "template": "/clear"},
                {"name": "/compact", "label": "세션 압축", "desc": "대화 히스토리 수동 압축/요약", "template": "/compact"},
            ]
            popular = [
                {"name": "/weather", "skill": "korea-weather", "label": "날씨 조회", "desc": "한국 실시간 날씨 및 단기예보", "template": "/skill korea-weather "},
                {"name": "/geeknews", "skill": "geeknews-search", "label": "긱뉴스", "desc": "최신 IT 트렌드 및 개발 소식 검색", "template": "/skill geeknews-search "},
                {"name": "/kopis", "skill": "kopis-performance-search", "label": "공연 정보", "desc": "KOPIS 공연·뮤지컬·전시 검색", "template": "/skill kopis-performance-search "},
                {"name": "/news", "skill": "naver-news-search", "label": "네이버 뉴스", "desc": "네이버 실시간 뉴스 검색", "template": "/skill naver-news-search "},
                {"name": "/shopping", "skill": "naver-shopping-search", "label": "네이버 쇼핑", "desc": "네이버 쇼핑 최저가 검색", "template": "/skill naver-shopping-search "},
                {"name": "/delivery", "skill": "delivery-tracking", "label": "택배 배송", "desc": "택배 배송 실시간 추적", "template": "/skill delivery-tracking "},
                {"name": "/daangn", "skill": "daangn-used-goods-search", "label": "당근마켓", "desc": "당근마켓 중고 매물 검색", "template": "/skill daangn-used-goods-search "},
                {"name": "/lotto", "skill": "lotto-results", "label": "로또 번호", "desc": "로또 당첨 번호 및 추첨 결과", "template": "/skill lotto-results "},
                {"name": "/stock", "skill": "korean-stock-search", "label": "주식 시세", "desc": "국내 주식 시세 및 종목 정보", "template": "/skill korean-stock-search "},
                {"name": "/bus", "skill": "express-bus-booking", "label": "고속버스", "desc": "고속·시외버스 예매 및 시간표", "template": "/skill express-bus-booking "},
            ]
            code, body = _json_bytes({"ok": True, "commands": commands, "popular": popular, "skills": skills})
            return self._send(code, body, "application/json; charset=utf-8", cache_control="public, max-age=300")
        if path == "/api/self-status":
            code, body = _json_bytes(_self_status())
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/api/rules/"):
            name = unquote(path[len("/api/rules/"):])
            fp = _rule_path(name)
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
            code, body = _json_bytes(_get_usage(force=force))
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/sessions":
            code, body = _json_bytes({"sessions": REG.list()})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/sessions/active":
            sess = REG.get_active()
            code, body = _json_bytes(sess.to_public())
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/api/sessions/") and path.endswith("/events"):
            sid = path[len("/api/sessions/"):-len("/events")]
            return self._sse(sid)
        if path.startswith("/api/sessions/") and path.endswith("/artifacts"):
            sid = path[len("/api/sessions/"):-len("/artifacts")]
            sess = REG.get(sid)
            code, body = _json_bytes({"artifacts": sess.get_artifacts()})
            return self._send(code, body, "application/json; charset=utf-8")
        if path == "/api/artifacts":
            sess = AgySession("global")
            code, body = _json_bytes({"artifacts": sess.get_artifacts()})
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/api/sessions/"):
            sid = path.split("/")[3]
            sess = REG.get(sid)
            code, body = _json_bytes(sess.to_public())
            return self._send(code, body, "application/json; charset=utf-8")
        if path.startswith("/artifacts/"):
            rel = path[len("/artifacts/"):]
            fp = _safe_artifact_rel(rel)
            if not fp:
                return self._send(404, b"not found", "text/plain")
            data = fp.read_bytes()
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            return self._send(200, data, ctype, cache_control="public, max-age=3600")
        # persona assets
        if path.startswith("/chat/persona/") or path.startswith("/persona/"):
            rel_p = path[len("/chat/persona/"):] if path.startswith("/chat/persona/") else path[len("/persona/"):]
            fp_p = (DATA / "persona" / rel_p).resolve()
            if not fp_p.exists() or not fp_p.is_file():
                fp_p = Path("/volume1/web/chat/persona") / rel_p
            if fp_p.exists() and fp_p.is_file():
                data = fp_p.read_bytes()
                ctype = mimetypes.guess_type(str(fp_p))[0] or "application/octet-stream"
                return self._send(200, data, ctype, cache_control="public, max-age=86400")

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
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if len(raw) > 200_000:
            raise ValueError("payload too large")
        return json.loads(raw.decode("utf-8") or "{}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json()
        except Exception as e:
            code, raw = _json_bytes({"ok": False, "error": str(e)}, 400)
            return self._send(code, raw, "application/json; charset=utf-8")
        try:
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
            if path == "/api/host/defibrillate":
                # Respond first, then schedule repair (kills/restarts this server).
                code, raw = _json_bytes({
                    "ok": True,
                    "scheduled": True,
                    "message_ko": "전기충격(심폐소생) 예약됨. 호스트가 재기동됩니다. 잠시 후 자동으로 다시 연결합니다.",
                })
                self._send(code, raw, "application/json; charset=utf-8")
                _schedule_host_defibrillate()
                return
            if path == "/api/sessions":
                sess = REG.create(model=str(body.get("model") or DEFAULT_MODEL), effort=str(body.get("effort") or ""))
                code, raw = _json_bytes({"ok": True, "session": sess.to_public()})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/sessions/") and path.endswith("/message"):
                sid = path[len("/api/sessions/"):-len("/message")]
                sess = REG.get(sid)
                if body.get("model") and body.get("model") != sess.model:
                    sess.model = str(body["model"])
                    sess.stop()
                text = str(body.get("text") or body.get("message") or "")
                rotated = sess.send(text)
                if rotated is not None:
                    code, raw = _json_bytes({
                        "ok": True,
                        "rotated": True,
                        "old_session_id": sid,
                        "session": rotated.to_public(),
                        "handoff_summary": getattr(rotated, "handoff_summary", ""),
                    })
                else:
                    code, raw = _json_bytes({"ok": True, "session": sess.to_public()})
                return self._send(code, raw, "application/json; charset=utf-8")
            if path.startswith("/api/sessions/") and path.endswith("/continue"):
                sid = path[len("/api/sessions/"):-len("/continue")]
                sess = REG.get(sid)
                summary = sess.get_handover_summary()
                model = str(body.get("model") or sess.model)
                new_sess = REG.create(
                    model=model,
                    effort=sess.effort,
                    predecessor_sid=sess.sid,
                    handoff_summary=summary,
                )
                sess.successor_session_id = new_sess.sid
                try:
                    sess.save_meta()
                except Exception:
                    pass
                code, raw = _json_bytes({
                    "ok": True,
                    "session": new_sess.to_public(),
                    "old_session_id": sid,
                    "summary": summary,
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
                if not fp:
                    code, raw = _json_bytes({"ok": False, "error": "unknown rule file"}, 404)
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
                fp.write_text(content, encoding="utf-8")
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
            end = _now() + 900
            while _now() < end:
                try:
                    ev = sub_queue.get(timeout=15)
                except queue.Empty:
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except Exception:
                        break
                    continue
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
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=_standby_maintenance_loop, daemon=True).start()
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
