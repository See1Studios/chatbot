"""Provider adapters: the registry and get_adapter(). Each provider lives in its own module (ADAPTER_SPLIT_v1):

  adapter_base.py    AgentAdapter (turn finalising, usage, served model) -- every adapter builds on it
  adapter_agy.py     Antigravity CLI          adapter_claude.py  Claude Code CLI
  adapter_grok.py    Grok CLI (+ billing)     adapter_codex.py   Codex CLI (+ rate limits)
  adapter_openai.py  HTTP OpenAI dialect from data/providers.json (+ MCP tool bridge)

Every name is re-exported here: callers keep `from adapters import ...`. AgentSession lives in session.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from host_config import DATA, DEFAULT_PROVIDER

# ADAPTER_SPLIT_v1: one module per provider; every name is re-exported here, so callers keep `from adapters import ...`.
from providers.adapter_base import (  # noqa: E402,F401
    _redact_err,
    AgentAdapter,
    openai_chunk_model,
    stamp_served_model,
)
from providers.adapter_agy import (  # noqa: E402,F401
    AGY_PRINT_TIMEOUT_SEC,
    AgyAdapter,
    AgyMediaSource,
)
from providers.adapter_claude import (  # noqa: E402,F401
    ClaudeAdapter,
)
from providers.adapter_grok import (  # noqa: E402,F401
    _grok_tool_display,
    _grok_tool_output_text,
    _GROK_PERIOD_LABEL,
    _grok_home,
    _grok_access_token,
    _grok_billing_to_rows,
    _fetch_grok_billing,
    GrokAdapter,
    GrokMediaSource,
)
from providers.adapter_codex import (  # noqa: E402,F401
    _codex_rate_limit_to_rows,
    _fetch_codex_rate_limits,
    CodexAdapter,
)
from providers.adapter_openai import (  # noqa: E402,F401
    OPENROUTER_FREE_ROUTERS,
    is_openrouter_free_model,
    NAS_MCP_URL,
    MCP_TOOLS_CACHE_TTL_SEC,
    _MCP_TOOLS_CACHE,
    _mcp_rpc,
    _mcp_openai_tools,
    _persona_system_prompt,
    _mcp_call_tool,
    OpenAIDialectAdapter,
)


_CLI_PROVIDER_IDS = frozenset({"agy", "claude", "grok", "codex"})
PROVIDERS_JSON = DATA / "providers.json"


def load_openai_dialect_adapters(path: Path) -> Dict[str, OpenAIDialectAdapter]:
    """HTTP OpenAI-dialect adapters from data/providers.json. CLI ids cannot be replaced."""
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    specs = raw.get("providers") if isinstance(raw, dict) else None
    if not isinstance(specs, dict):
        return {}
    out: Dict[str, OpenAIDialectAdapter] = {}
    for pid, cfg in specs.items():
        if not isinstance(pid, str) or not isinstance(cfg, dict):
            continue
        if cfg.get("type") != "openai_dialect" or pid in _CLI_PROVIDER_IDS:
            continue
        base_url = str(cfg.get("base_url") or "").strip()
        api_key_env = str(cfg.get("api_key_env") or "").strip()
        if not base_url or not api_key_env:
            raise ValueError(f"providers.json {pid}: base_url and api_key_env required")
        curated = [str(m).strip() for m in (cfg.get("curated_models") or []) if str(m).strip()]
        default_model = str(cfg.get("default_model") or "").strip()
        free_only = bool(cfg.get("free_only"))
        if free_only:
            curated = [m for m in curated if is_openrouter_free_model(m)]
            if not is_openrouter_free_model(default_model):
                default_model = curated[0] if curated else "openrouter/free"
        meta = cfg.get("meta") if isinstance(cfg.get("meta"), dict) else {}
        default_params = cfg.get("default_params") if isinstance(cfg.get("default_params"), dict) else {}
        extra_headers = cfg.get("extra_headers") if isinstance(cfg.get("extra_headers"), dict) else {}
        out[pid] = OpenAIDialectAdapter(
            id=pid,
            base_url=base_url,
            api_key_env=api_key_env,
            default_model=default_model,
            curated_models=curated,
            free_only=free_only,
            meta=meta,
            default_params=default_params,
            extra_headers=extra_headers,
        )
    return out


# ---- where each CLI keeps the media it generates (media_handler asks; PROVIDER_NEUTRAL_v1) -----
import media_handler as _media  # noqa: E402  (no provider knowledge of its own)
from urllib.parse import quote as _quote  # noqa: E402


_media.register_media_source(AgyMediaSource())
_media.register_media_source(GrokMediaSource())


# Display facts per provider for the catalog (/api/providers). A provider is a vendor, not the persona.
PROVIDER_META: Dict[str, Dict[str, str]] = {
    "agy": {"name": "Antigravity", "role": "Google Antigravity", "theme": "spark", "icon": "/chat/providers/agy.webp?v=9"},
    "claude": {"name": "Claude", "role": "Anthropic AI", "theme": "amber", "icon": "/chat/providers/claude.webp?v=10"},
    "grok": {"name": "Grok", "role": "xAI Explorer", "theme": "mono", "icon": "/chat/providers/grok.webp?v=6"},
    "codex": {"name": "Codex", "role": "OpenAI Engine", "theme": "emerald", "icon": "/chat/providers/codex.webp?v=10"},
}


AGENT_ADAPTERS: Dict[str, AgentAdapter] = {
    "agy": AgyAdapter(),
    "claude": ClaudeAdapter(),
    "grok": GrokAdapter(),
    "codex": CodexAdapter(),
}
AGENT_ADAPTERS.update(load_openai_dialect_adapters(PROVIDERS_JSON))


def get_adapter(provider_id: str = DEFAULT_PROVIDER) -> AgentAdapter:
    return AGENT_ADAPTERS.get(provider_id, AGENT_ADAPTERS[DEFAULT_PROVIDER])

