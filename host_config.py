"""Process-wide paths, env, and session-length constants for the chat host.

Imported by server.py and adapters.py. Side effect: ensures data dirs exist.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# Default is loopback: a bare `python3 server.py` is local-only. LAN access is an
# explicit choice -- chatbot-ctl.sh cmd_start exports AGY_CHAT_HOST=0.0.0.0.
HOST = os.environ.get("AGY_CHAT_HOST", "127.0.0.1")
PORT = int(os.environ.get("AGY_CHAT_PORT", "3011"))
MCP_PORT = int(os.environ.get("NAS_MCP_PORT", "3012"))  # informational only (healthz) -- mcp_server.py reads its own copy
AGY = os.environ.get("AGY_BIN", "/volume1/homes/me/.local/bin/agy")
CLAUDE_BIN = os.environ.get("AGY_CLAUDE_BIN", "/volume1/homes/me/.local/bin/claude")
GROK_BIN = os.environ.get("AGY_GROK_BIN", "/volume1/homes/me/.local/bin/grok")
CODEX_BIN = os.environ.get("AGY_CODEX_BIN", "/volume1/homes/me/.local/bin/codex")
ROOT = Path(os.environ.get("AGY_CHAT_ROOT", "/volume1/homes/me/services/chatbot"))
# 2026-09-16: consolidated from a sibling chatbot-data/ directory (and its
# own separate git repos) into chatbot/data/ -- one project, one folder, one
# repo, instead of code and data living apart and needing separate publish
# subtrees to back up together.
DATA = Path(os.environ.get("AGY_CHAT_DATA", str(ROOT / "data")))
STATIC = ROOT / "static"
SESSIONS = DATA / "sessions"
WORKSPACE = DATA / "workspace"
HOME = Path(os.environ.get("HOME", "/volume1/homes/me"))
# Static web host root -- NOT this service's own ROOT/DATA. Only this NAS's
# actual layout (/volume1/web) is DiskStation-specific; the var itself lets
# a different deployment point it anywhere (see docs/plans/chatbot-host-portability.md).
WEB_ROOT = Path(os.environ.get("AGY_CHAT_WEB_ROOT", "/volume1/web"))
AGENT_PATH_PREFIX = f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
BRAIN = HOME / ".gemini" / "antigravity-cli" / "brain"
# Shared/manual assets not tied to any one session (2026-09-16: merged the
# formerly-separate chatbot-data/artifacts git repo into the sessions repo,
# alongside sessions/<sid>/ -- see_through/ layer-splitting output, a few
# standing brand/persona images). Per-conversation generated images live in
# sessions/<sid>/artifacts/ instead (see _stage_image).
ARTIFACTS_CACHE = SESSIONS / "_shared"
# Event kinds worth keeping durable (sessions/<sid>/events.jsonl) for both
# 실장님's 로그 tab history and the self-improve loop's own debugging --
# excludes the high-frequency streaming noise (delta/raw/agy/stderr/user)
# that would otherwise make the log unbounded for no real signal.
PERSISTED_LOG_KINDS = {
    "system", "btw_start", "btw", "error", "queued", "result",
    "session_heavy", "session_rotate", "stopped", "tool", "user_ack", "image",
}
DEFAULT_MODEL = os.environ.get("AGY_CHAT_MODEL", "gemini-3.8-flash-low")
MODELS = [
    "gemini-3.8-flash-low",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-high",
    "gemini-3.1-pro-high",
    "gemini-3.1-pro-low",
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
]

# Narrow ADD_DIRS for spawn latency (2026-09-16).
# Removed: entire HOME, /volume1/web, .hermes, HOME/services, redundant artifacts.
# 2026-09-19 A/B (host-identical stream-json spawn, "안녕" 한 문장):
#   ROOT + /chat  45970
#   ROOT only     45950
#   /chat only    14296
#   no add-dir    14297
# Live after dropping ROOT but keeping static/: still 45965. static/vendor/
# mermaid.min.js (3.2M) is inside STATIC, so --add-dir static == ROOT tax.
# /chat is free. Do not add ROOT or STATIC. Code/UI edits: MCP ALLOW_ROOTS
# includes services/chatbot.
ADD_DIRS = [
    str(WEB_ROOT / "chat"),
    str(WORKSPACE),   # MCP(.gemini/config/mcp_config.json), skills(.agents/), hooks -- required
                      # Measured 2026-09-19: agy adds ~+34k tokens/turn when an add-dir
                      # sits inside the home git repo (independent of the dir's contents --
                      # an identical copy under /tmp costs +0.8k), i.e. host-level
                      # settings/skills leak in; the agy child is not isolated from ~
                      # (docs/plans/instruction-architecture.md). Rules reach every
                      # provider via the host-built bundle (instructions.py, injected in
                      # session.py _send_direct()).
                      # Keep WORKSPACE lean: no large blobs, no log dumps at root level.
]

# Session length guard thresholds (UI hist + optional conversation.db size)
SOFT_TURNS = 40
SOFT_CHARS = 15_000
HARD_TURNS = 60
HARD_CHARS = 25_000
HARD_DB_BYTES = 8 * 1024 * 1024  # ~8MB conversation.db
SOFT_DB_BYTES = 5 * 1024 * 1024
# Catches the case turns/chars/db_bytes miss entirely: a session can rack up
# huge cumulative token cost (and multi-minute per-turn latency) over very
# few turns with short messages -- observed once at 1.38M tokens / 11 turns.
SOFT_TOKENS = 150_000
HARD_TOKENS = 400_000
INACTIVITY_ROTATE_SEC = 3 * 3600  # 3 hours gap triggers auto-compaction and fresh rotate

for p in (SESSIONS, WORKSPACE, STATIC, ARTIFACTS_CACHE):
    p.mkdir(parents=True, exist_ok=True)

DEFAULT_PROVIDER = "agy"


_now = time.time
