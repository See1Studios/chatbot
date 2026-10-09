"""Process-wide paths, env, and session-length constants for the chat host.

Imported by server.py and providers/. Side effect: ensures data dirs exist.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from repo_layout import repo_of

# Default is loopback: a bare `python3 server.py` is local-only. LAN access is an
# explicit choice -- chatbot-ctl.sh cmd_start exports CHATBOT_HOST=0.0.0.0.
def _env(name: str, default: str) -> str:
    """Service settings are CHATBOT_* (PROVIDER_NEUTRAL_v1: the service is not one provider's). The older AGY_CHAT_*
    names were dropped 2026-10-07: nothing set them any more."""
    return os.environ.get(name) or default


HOME = Path(os.environ.get("HOME") or Path.home())
ROOT = Path(_env("CHATBOT_ROOT", str(Path(__file__).resolve().parent)))   # the engine folder (code, settings)
REPO = repo_of(ROOT)          # LAYOUT_v1: the repository root (static/, templates/, tests/, docs/)
TEMPLATES = REPO / "templates"
# 2026-09-16: consolidated from a sibling chatbot-data/ directory (and its
# own separate git repos) into chatbot/data/ -- one project, one folder, one
# repo, instead of code and data living apart and needing separate publish
# subtrees to back up together.
# The user-data directory, decided HERE only (user-data-separation §0, uds/B, uds/F; test_data_paths): the first
# DATA_ENV variable that is set, else a literal CHATBOT_DATA in data-pin.env (dev checkout), else ~/.pe
# (Windows: %USERPROFILE%\\.pe). PE_HOME and PRIVATEENGINE_HOME are brand aliases. tickets.py (a core module, which may not import this one) repeats the same order; the test keeps the two
# identical.
DATA_ENV = ("CHATBOT_DATA", "PE_HOME", "PRIVATEENGINE_HOME")


def test_run_outside_runner() -> bool:
    """LIVE_DATA_GUARD_v1: a unittest or pytest process that run-tests.sh did not start (CHATBOT_TEST_RUNNER). Such a
    run inherits an install's data (a chat agent's CHATBOT_DATA=~/.pe); live 2026-10-05 a subagent ran
    `python3 -m unittest discover tests` against it. tickets.py repeats this check (it may not import this module)."""
    a0 = (sys.argv[0] if sys.argv else "") or ""
    return os.environ.get("CHATBOT_TEST_RUNNER") != "1" and (
        "-m unittest" in a0 or os.path.basename(a0).startswith(("pytest", "py.test")))


if test_run_outside_runner():
    if os.environ.get("CHATBOT_LIVE_AGENT"):   # LIVE_AGENT_SUITE_v1: the one way for a chat agent is the script
        raise SystemExit("tests: a live chat agent runs tests only as engine/run-tests.sh test_x (named modules), "
                         "never unittest/pytest directly")
    for _k in DATA_ENV:
        os.environ.pop(_k, None)
    os.environ["CHATBOT_DATA"] = str(Path(__file__).resolve().parent / "data")   # never an install's data

def _pinned_chatbot_data(root: Path) -> str:
    """Dev pin file (data-pin.env) used only when no DATA_ENV variable is set. Literal CHATBOT_DATA only;
    a value with $ is ignored so this reader and chatbot-ctl.sh (which sources the file) cannot disagree."""
    try:
        lines = (Path(root) / "data-pin.env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, sep, val = line.partition("=")
        if not sep or key.strip() != "CHATBOT_DATA":
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        if val and "$" not in val:
            return val
        return ""
    return ""

DATA = Path(next((os.environ[k] for k in DATA_ENV if os.environ.get(k)),
                 _pinned_chatbot_data(ROOT) or str(HOME / ".pe")))
STATIC = REPO / "static"
SESSIONS = DATA / "sessions"
INCIDENTS = DATA / "dev" / "incidents.json"   # dev data beside the engine tickets (improvement-layers il/D)
WORKSPACE = DATA / "workspace"
# Web Push (push_manager.py): the install's VAPID key pair and the browsers subscribed to it
PUSH_VAPID_FILE = DATA / "push_vapid.json"
PUSH_SUBSCRIPTIONS_FILE = DATA / "push_subscriptions.json"
# An external static web root the install publishes into (persona images, the /chat shortcut). An install with no
# web server leaves it unset and gets a folder in its own data; a host that has one names it in
# $CHATBOT_DATA/host.env (templates/host.env.example). align/F: no host path is baked in.
WEB_ROOT = Path(_env("CHATBOT_WEB_ROOT", str(DATA / "web")))
# Which build this install is (docs/plans/edition-boundary.md): "shipped" (end users -- the agent never touches engine
# code, dev tools are off) unless the install opts in with CHATBOT_EDITION=dev in $CHATBOT_DATA/host.env. Least
# privilege by default; this is the one place the edition is decided.
EDITION = "dev" if os.environ.get("CHATBOT_EDITION", "").strip().lower() == "dev" else "shipped"
AGENT_PATH_PREFIX = f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"

HOST = _env("CHATBOT_HOST", "127.0.0.1")
PORT = int(_env("CHATBOT_PORT", "3011"))
MCP_PORT = int(os.environ.get("NAS_MCP_PORT", "3012"))  # mcp_server.py reads its own copy of the same setting
MCP_URL = "http://127.0.0.1:%d/mcp" % MCP_PORT   # where agents reach the tool server: every adapter writes this one
AGY = os.environ.get("AGY_BIN", str(HOME / ".local" / "bin" / "agy"))
CLAUDE_BIN = _env("CHATBOT_CLAUDE_BIN", str(HOME / ".local" / "bin" / "claude"))
GROK_BIN = _env("CHATBOT_GROK_BIN", str(HOME / ".local" / "bin" / "grok"))
CODEX_BIN = _env("CHATBOT_CODEX_BIN", str(HOME / ".local" / "bin" / "codex"))
# Worktree delegation (docs/plans/multi-agent-worktree-delegation.md §9): which CLI does the delegated work and
# which one confirms the work as the PD persona (empty: the same CLI). Names are keys of tools/worktree_runner.PROVIDERS.
# The default is the one provider the operator uses continuously (2026-09-23); the others are occasional. Models
# empty = the runner's per-provider defaults (tools/worktree_runner.PROVIDERS work_model / review_model).
DELEGATE_PROVIDER = os.environ.get("CHATBOT_DELEGATE_PROVIDER", "agy")
DELEGATE_REVIEWER = os.environ.get("CHATBOT_DELEGATE_REVIEWER", "")
DELEGATE_MODEL = os.environ.get("CHATBOT_DELEGATE_MODEL", "")
DELEGATE_REVIEWER_MODEL = os.environ.get("CHATBOT_DELEGATE_REVIEWER_MODEL", "")
BRAIN = HOME / ".gemini" / "antigravity-cli" / "brain"
# Shared/manual assets not tied to any one session (2026-09-16: merged the
# formerly-separate chatbot-data/artifacts git repo into the sessions repo,
# alongside sessions/<sid>/ -- see_through/ layer-splitting output, a few
# standing brand/persona images). Per-conversation generated images live in
# sessions/<sid>/artifacts/ instead (see _stage_image).
ARTIFACTS_CACHE = SESSIONS / "_shared"
# Log location (LOG_PATH_v1): ONE resolver, so obslog, logdigest and chatbot-ctl.sh cannot drift
# apart. CHATBOT_OBSLOG_PATH still wins where it is set (obslog only writes where it is set, so a
# hand-started server and every test keep their events in memory instead of the production stream).
# The default is the install's data folder, dev and shipped alike (2026-10-09, operator: ~/.pe/logs): logs are user
# data, not engine (docs/plans/user-data-separation.md §2), the daily rollups are kept forever (telemetry tl/C) and
# must outlive a fresh checkout, and ticket evidence reads them from the data folder (tickets._log_dirs).
LOG_DIR = Path(os.environ.get("CHATBOT_LOG_DIR") or DATA / "logs")
EVENTS_LOG = Path(os.environ.get("CHATBOT_OBSLOG_PATH") or LOG_DIR / "events.jsonl")
# Event kinds worth keeping durable (sessions/<sid>/events.jsonl) for both
# operator's log tab history and the self-improve loop's own debugging --
# excludes the high-frequency streaming noise (delta/raw/agy/stderr/user)
# that would otherwise make the log unbounded for no real signal.
PERSISTED_LOG_KINDS = {
    "system", "btw_start", "btw", "error", "queued", "result",
    "session_heavy", "session_rotate", "stopped", "tool", "user_ack", "image",
    "choices", "action",
}
DEFAULT_MODEL = _env("CHATBOT_DEFAULT_MODEL", "gemini-3.8-flash-low")
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
# 2026-09-19 A/B (host-identical stream-json spawn, a one-line "hello"):
#   ROOT + /chat  45970
#   ROOT only     45950
#   /chat only    14296
#   no add-dir    14297
# Live after dropping ROOT but keeping static/: still 45965. static/vendor/
# mermaid.min.js (3.2M) is inside STATIC, so --add-dir static == ROOT tax.
# /chat is free. Do not add ROOT or STATIC. Code/UI edits: MCP ALLOW_ROOTS
# includes services/chatbot.
ADD_DIRS = [d for d in (str(WEB_ROOT / "chat"),) if Path(d).is_dir()] + [   # only a web root that exists (align/F)
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

for p in (SESSIONS, WORKSPACE, STATIC, ARTIFACTS_CACHE, LOG_DIR):
    p.mkdir(parents=True, exist_ok=True)

DEFAULT_PROVIDER = os.environ.get("CHATBOT_DEFAULT_PROVIDER", "agy")
# The provider common features use for a single prompt without a conversation (side questions,
# handoff summaries): adapters' oneshot(). PROVIDER_NEUTRAL_v1.
ONESHOT_PROVIDER = os.environ.get("CHATBOT_ONESHOT_PROVIDER", DEFAULT_PROVIDER)


_now = time.time
