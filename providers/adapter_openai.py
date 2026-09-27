"""HTTP OpenAI-dialect adapter (providers.json) and the MCP tool bridge it uses. Callers import from adapters (ADAPTER_SPLIT_v1)."""
from __future__ import annotations

import json
import os
import time

from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.request import Request, urlopen

from tool_format import _format_tool_call, _format_tool_result
from providers.adapter_base import AgentAdapter, openai_chunk_model


OPENROUTER_FREE_ROUTERS = frozenset({"openrouter/free"})


def is_openrouter_free_model(model: str) -> bool:
    """OpenRouter ids that cannot bill: `:free` suffix or the free-only router.

    Measured 2026-09-21 against GET /api/v1/models: `openrouter/free` exists
    with prompt=0/completion=0 (name "Free Models Router"). `openrouter/auto`
    is NOT free (pricing -1) and must not pass this check.
    """
    m = (model or "").strip()
    if not m:
        return False
    if m.endswith(":free"):
        return True
    return m in OPENROUTER_FREE_ROUTERS


NAS_MCP_URL = "http://127.0.0.1:3012/mcp"


_MCP_TOOLS_CACHE: Dict[str, Any] = {"ts": 0.0, "tools": []}


MCP_TOOLS_CACHE_TTL_SEC = 300


def _mcp_rpc(method: str, params: Optional[dict] = None, timeout: int = 20) -> dict:
    """One JSON-RPC round-trip to mcp_server.py's real HTTP service. **Not** an
    in-process import -- mcp_server.py runs as its own separate `nohup python3
    mcp_server.py` process (chatbot-ctl.sh), listening on 127.0.0.1:3012/mcp,
    the same way claude/grok/codex CLI adapters already reach it (see their
    own hardcoded "http://127.0.0.1:3012/mcp" in build_args/_write_mcp_config
    above). An earlier draft of docs/plans/api-provider-adapters.md assumed
    "same process, direct function call" -- checked live 2026-09-18 (`grep
    "import nas_mcp" server.py` -> nothing, `curl .../healthz` -> a real,
    separately-running server) and corrected before writing this."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    req = Request(
        NAS_MCP_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    err = payload.get("error")
    if err is not None:
        raise RuntimeError(str(err.get("message") if isinstance(err, dict) else err))
    return payload.get("result") or {}


def _mcp_openai_tools(force: bool = False) -> List[dict]:
    """mcp_server.py's `tools/list` (MCP shape: name/description/inputSchema) ->
    OpenAI `tools=[{type:"function", function:{name, description,
    parameters}}]` shape ("설계 원칙 5" wire-dialect conversion, Phase 2).
    Cached -- the tool catalog only changes on a mcp_server.py deploy, not
    per-turn, so fetching it fresh on every single message would be a wasted
    round-trip."""
    now = time.time()
    if not force and _MCP_TOOLS_CACHE["tools"] and (now - _MCP_TOOLS_CACHE["ts"] < MCP_TOOLS_CACHE_TTL_SEC):
        return _MCP_TOOLS_CACHE["tools"]
    result = _mcp_rpc("tools/list")
    tools = []
    for t in result.get("tools") or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description") or "",
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            },
        })
    _MCP_TOOLS_CACHE["ts"] = now
    _MCP_TOOLS_CACHE["tools"] = tools
    return tools


def _persona_system_prompt() -> Optional[str]:
    """The host-assembled instruction bundle (instructions.py: AGENTS.md +
    the character card + skill index + memory snapshot + self-improve status), or
    None when there is nothing to inject. Used by AgentSession._send_direct()
    as the first-turn injection for every process provider, and as the
    system message of the HTTP adapter -- native cwd auto-discovery differs
    per CLI and is not relied on (see ClaudeAdapter's docstring). Rebuilt on
    every call: the inputs are a handful of small files."""
    from instructions import build_instruction_bundle
    return build_instruction_bundle()["text"] or None


def _mcp_call_tool(name: str, arguments: dict) -> str:
    """mcp_server.py's `tools/call` -> the text a `role:"tool"` message's
    `content` should carry. The MCP response already wraps the tool's own
    JSON envelope into `content[0].text`; passed straight through so it's
    encoded once, not re-wrapped."""
    result = _mcp_rpc("tools/call", {"name": name, "arguments": arguments or {}}, timeout=30)
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text") or ""
    return json.dumps(result, ensure_ascii=False)


class OpenAIDialectAdapter(AgentAdapter):
    """API-Provider plan Phase 1 (docs/plans/api-provider-adapters.md) --
    OpenAI chat/completions wire dialect over plain HTTP, no subprocess at
    all. One instance per target *endpoint* (base_url/api_key_env/id), not
    one subclass per vendor: OmniRoute, OpenRouter, or any other
    OpenAI-compatible gateway all speak this exact dialect ("설계 원칙 5" --
    Transport and Wire Dialect are separate axes; this class is the http
    transport + openai dialect combination). A genuinely different wire
    shape (Anthropic Messages API called natively, not through a gateway)
    needs its own dialect adapter later -- not this one.

    Phase 2 (2026-09-18): tool-calling loop against mcp_server.py added, kept in
    a separate method (_stream_once, one raw HTTP call) from the looping
    orchestrator (stream_turn) so a streaming-format bug and a tool-loop bug
    are still never the same stack trace, even though both now live in this
    class (see plan's "순서" section for why Phase 1 shipped without this
    first).

    Live-verified against OmniRoute (localhost:20128) 2026-09-18, real
    `/v1/chat/completions` calls, not docs:
    - `stream` must be set EXPLICITLY. Omitting it still returned an SSE
      response on this deployment (differs from the OpenAI spec's documented
      default of non-streaming) -- don't rely on the implicit default.
    - Streaming responses can lead with synthetic keepalive chunks
      (`id == "omniroute-keepalive"`, empty delta, sent while the routing
      decision is still being made) before the real stream starts -- these
      must be filtered, not treated as content.
    - `usage.total_tokens` is not always `prompt_tokens + completion_tokens`
      -- hidden reasoning/thinking tokens can inflate the total, and
      `completion_tokens_details.reasoning_tokens` isn't consistently
      present even across calls to the same combo. Treat `total_tokens` as
      authoritative for weight/rotation; everything else is best-effort.
    - A model listed in `/v1/models` is not guaranteed callable -- one
      confirmed live 401 "model ... is not supported" for a model this test
      key's connected accounts don't actually have access to, mislabeled
      `type: "authentication_error"` even though it was really a
      routing/entitlement problem, not a bad key.
    - Tool-calling round-trips exactly per the OpenAI spec (verified live,
      request -> tool_calls response -> role:"tool" follow-up -> final
      answer). In streaming mode, a tool_call's `id`/`name`/`arguments` all
      arrived in a single delta chunk for the models this was tested
      against, but nothing in the OpenAI wire format guarantees that --
      other backends OmniRoute might route to can fragment `arguments`
      character-by-character across many deltas the way OpenAI's own models
      do -- so _stream_once() accumulates by `index` and concatenates
      `arguments` instead of assuming one complete chunk.
    - mcp_server.py is a genuinely separate process (its own `nohup python3
      mcp_server.py`, HTTP JSON-RPC on 127.0.0.1:3012/mcp) -- **not**
      importable in-process. An earlier draft of the plan doc assumed it
      was; corrected after actually grepping for the import and confirming
      the live port is a real separate server (see _mcp_rpc() above this
      class).
    """

    transport_kind = "http"
    keeps_stdin_open = False

    def __init__(
        self,
        id: str,
        base_url: str,
        api_key_env: str,
        default_model: str,
        curated_models: Optional[List[str]] = None,
        free_only: bool = False,
        meta: Optional[dict] = None,
        default_params: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
    ):
        self.id = id
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.default_model = default_model
        self._curated_models = curated_models or []
        self.free_only = bool(free_only)
        self.meta = dict(meta or {})
        self.default_params = dict(default_params or {})
        self.extra_headers = dict(extra_headers or {})
        self._models_meta_cache: Dict[str, Any] = {"ts": 0.0, "data": {}}

    def find_executable(self) -> str:
        return ""  # not applicable -- transport_kind="http" means AgentSession never calls this

    def build_env(self, home: Path) -> dict:
        return {}

    def format_stdin(self, content: str) -> str:
        return ""  # not applicable -- no stdin, see stream_turn()

    def available(self) -> bool:
        return bool(os.environ.get(self.api_key_env))

    def known_models(self) -> List[str]:
        models = list(self._curated_models)
        if self.free_only:
            models = [m for m in models if is_openrouter_free_model(m)]
            try:
                for fm in sorted(self._get_models_meta()):
                    if is_openrouter_free_model(fm) and fm not in models:
                        models.append(fm)
            except Exception:
                pass
            if self.default_model and self.default_model not in models:
                models.insert(0, self.default_model)
        return models

    def coerce_openrouter_model(self, model: str) -> str:
        """Paid or empty ids become the free default when free_only is set."""
        if not self.free_only:
            return (model or "").strip() or self.default_model
        m = (model or "").strip()
        if is_openrouter_free_model(m):
            return m
        return self.default_model

    def mints_own_conversation_id(self) -> bool:
        # Not really "mints" -- plain chat/completions is stateless and has
        # no conversation-id concept at all. Returning True has the effect
        # this adapter actually needs either way: _spawn() (process-transport
        # only, never called for this adapter) must not pre-mint a uuid4 for
        # a --resume flag that doesn't exist here.
        return True

    def _get_models_meta(self) -> Dict[str, dict]:
        """Fetch and cache `/v1/models` metadata (context_length, etc.). Cached for 10 min; a failed fetch is
        remembered for 60 s, or an unreachable endpoint costs the 10 s timeout on every call (/api/providers
        took 30 s on 2026-09-27)."""
        now = time.time()
        if self._models_meta_cache["data"] and (now - self._models_meta_cache["ts"] < 600):
            return self._models_meta_cache["data"]
        if now - self._models_meta_cache.get("failed_ts", 0) < 60:
            return {}
        meta_by_id = {}
        try:
            req = Request(
                self.base_url + "/models",
                headers={"Authorization": f"Bearer {os.environ.get(self.api_key_env, '')}"},
                method="GET",
            )
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("data", []):
                mid = m.get("id")
                if mid:
                    meta_by_id[mid] = m
            self._models_meta_cache["ts"] = now
            self._models_meta_cache["data"] = meta_by_id
        except Exception:
            self._models_meta_cache["failed_ts"] = now
        return meta_by_id

    def soft_hard_tokens(self, model: str) -> Tuple[int, int]:
        target = model or self.default_model
        meta = self._get_models_meta().get(target)
        if meta and isinstance(meta.get("context_length"), (int, float)) and meta["context_length"] > 0:
            ctx = int(meta["context_length"])
            # Safety thresholds scaled to actual context length
            soft = int(ctx * 0.4)
            hard = int(ctx * 0.7)
            return min(soft, 400_000), min(hard, 800_000)
        return 128_000, 200_000

    def normalize_usage(self, raw_usage: Optional[dict]) -> Optional[dict]:
        if not isinstance(raw_usage, dict):
            return None
        prompt = int(raw_usage.get("prompt_tokens") or 0)
        completion = int(raw_usage.get("completion_tokens") or 0)
        total = raw_usage.get("total_tokens")
        details = raw_usage.get("completion_tokens_details") or {}
        prompt_details = raw_usage.get("prompt_tokens_details") or {}
        return {
            "input_tokens": prompt,
            "output_tokens": completion,
            "thinking_tokens": int(details.get("reasoning_tokens") or 0),
            "cache_read_tokens": int(prompt_details.get("cached_tokens") or 0),
            "total_tokens": int(total) if total is not None else (prompt + completion),
        }

    def rate_limit_report(self) -> Optional[dict]:
        """Query provider endpoint (OmniRoute connections or OpenRouter credits/key) to surface quota/status."""
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            return {"error": f"{self.api_key_env} 키가 설정되지 않았습니다"}

        if self.id == "openrouter":
            # OpenRouter: query /api/v1/credits and /api/v1/auth/key
            try:
                base = self.base_url.rstrip("/")
                # If base_url already contains /api/v1, use base directly, else strip /v1
                credits_url = f"{base}/credits" if base.endswith("/api/v1") else f"{base}/api/v1/credits"
                auth_url = f"{base}/auth/key" if base.endswith("/api/v1") else f"{base}/api/v1/auth/key"
                req = Request(
                    credits_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    method="GET",
                )
                with urlopen(req, timeout=10) as resp:
                    cdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                total_c = float(cdata.get("total_credits") or 0.0)
                used_c = float(cdata.get("total_usage") or 0.0)
                rem_c = max(0.0, total_c - used_c)
                rows = [
                    {
                        "group": "OpenRouter 잔액",
                        "limit_type": "크레딧",
                        "remaining_pct": f"${rem_c:.2f} / ${total_c:.2f}",
                        "reset_at": "종량제 (잔여)",
                    }
                ]
                # Also check auth/key free model requests if available
                try:
                    kreq = Request(
                        auth_url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        method="GET",
                    )
                    with urlopen(kreq, timeout=10) as resp:
                        kdata = json.loads(resp.read().decode("utf-8")).get("data", {})
                    finfo = kdata.get("free_model_daily_requests") or {}
                    if finfo:
                        used_f = finfo.get("used", 0)
                        lim_f = finfo.get("limit", 0)
                        rem_f = finfo.get("remaining", max(0, lim_f - used_f))
                        pct_f = int((rem_f / lim_f * 100)) if lim_f else 0
                        rows.append({
                            "group": "무료 모델 한도",
                            "limit_type": "일일 쿼터",
                            "remaining_pct": f"{pct_f}% ({rem_f}/{lim_f}회)",
                            "reset_at": "매일 자정 (UTC)",
                        })
                except Exception:
                    pass

                # Also surface currently available top free models status
                try:
                    models_meta = self._get_models_meta()
                    free_models = [m for m in models_meta.values() if ":free" in m.get("id", "")]
                    if free_models:
                        # Top curated free models to show status for
                        curated_free = [m for m in self._curated_models if ":free" in m]
                        free_names = []
                        for mid in curated_free[:4]:
                            name = models_meta.get(mid, {}).get("name") or mid.split("/")[-1]
                            free_names.append(name.replace("(free)", "").strip())
                        preview_str = ", ".join(free_names) if free_names else f"{len(free_models)}개 무료 모델"
                        rows.append({
                            "group": "무료 모델 상태",
                            "limit_type": f"활성 {len(free_models)}종 제공 중",
                            "remaining_pct": f"{len(free_models)}종 정상",
                            "reset_at": preview_str[:60],
                        })
                except Exception:
                    pass

                return {"rows": rows}
            except Exception as e:
                return {"error": f"OpenRouter 크레딧 조회 실패: {str(e)[:200]}"}

        # Default: OmniRoute /api/providers is on the root port (e.g. http://localhost:20128/api/providers)
        # while base_url is typically http://localhost:20128/v1
        base = self.base_url
        if base.endswith("/v1"):
            base = base[:-3]
        url = base + "/api/providers"
        try:
            req = Request(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                method="GET",
            )
            with urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            conns = payload.get("connections") or []
            rows = []
            for c in conns:
                name = c.get("name") or "unknown"
                p = c.get("provider") or "unknown"
                active = bool(c.get("isActive") and c.get("testStatus") == "active")
                exp = c.get("expiresAt") or "-"
                group = f"{p} ({name})"
                limit_type = "연결 상태"
                rem = "정상 (100%)" if active else "주의 (0%)"
                rows.append({
                    "group": group,
                    "limit_type": limit_type,
                    "remaining_pct": rem,
                    "reset_at": exp,
                })
            if not rows:
                return {"error": "연결된 프로바이더 계정이 없습니다"}
            return {"rows": rows}
        except Exception as e:
            return {"error": f"OmniRoute 상태 조회 실패: {str(e)[:200]}"}

    # --- HTTP-transport-only surface (AgentSession's http branch calls this,
    # process-transport adapters never do) ------------------------------------

    MAX_TOOL_HOPS = 20  # safety cap -- expanded from 10 to 20 for complex multi-hop tasks
    # runaway CLI subprocess), the equivalent failure mode for http transport
    # is an unbounded model<->tool ping-pong that never reaches a plain
    # answer, so this is this adapter's version of orphan-process protection.

    HTTP_TURN_TIMEOUT_SEC = 180  # wall-clock cap on one whole turn (all hops).
    # _stream_once()'s urlopen(timeout=120) only bounds the gap between
    # individual reads -- verified live (2026-09-18) that OmniRoute emits a
    # synthetic "omniroute-keepalive" delta every so often while its own
    # upstream call is still stuck, which resets that per-read timeout
    # forever and lets a turn hang indefinitely with session.busy stuck True
    # (no OS process for chatbot-ctl.sh's orphan-killer to ever catch, since
    # this is just a thread blocked in a socket read). AgentSession's watchdog
    # (_start_http_watchdog/_http_turn_watchdog) enforces this by calling
    # stop() once a turn runs past it.

    def _stream_once(self, session: "AgentSession", messages: List[dict], tools: List[dict], seq: Optional[int] = None) -> Iterator[dict]:
        """One raw HTTP POST + SSE read. Yields {"event":"delta"} for content
        pieces as they arrive; returns (text, tool_calls, usage, finish_reason,
        served_model) via StopIteration (consume with
        `x = yield from self._stream_once(...)`) once the stream ends.
        served_model is the wire `model` field (OpenRouter free router may
        differ from the requested slug). No session.history/current_text
        finalization here -- stream_turn() decides whether this hop was a
        plain answer or another round of tool calls."""
        if seq is not None and getattr(session, "_turn_seq", None) != seq:
            return "", {}, None, None, ""
        api_key = os.environ.get(self.api_key_env, "")
        model = self.coerce_openrouter_model(session.model or self.default_model)
        if self.free_only and session.model != model:
            session.model = model
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            # OpenAI-compat last SSE event is often choices=[] + usage={...}.
            # Without this flag some combos never emit usage at all.
            "stream_options": {"include_usage": True},
        }
        if self.default_params:
            for k, v in self.default_params.items():
                if k not in body:
                    body[k] = v
        if tools:
            body["tools"] = tools
        req_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.extra_headers:
            req_headers.update(self.extra_headers)
        req = Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=req_headers,
            method="POST",
        )
        text_buf: List[str] = []
        tool_calls: Dict[int, dict] = {}
        usage = None
        finish_reason = None
        served_model = ""
        if seq is not None and getattr(session, "_turn_seq", None) != seq:
            return "", {}, None, None, ""
        resp = urlopen(req, timeout=120)
        session._http_resp = resp
        try:
            for raw_line in resp:
                if seq is not None and getattr(session, "_turn_seq", None) != seq:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if obj.get("id") == "omniroute-keepalive":
                    continue  # synthetic heartbeat -- verified live, not content
                if isinstance(obj.get("usage"), dict):
                    usage = obj["usage"]
                chunk_model = openai_chunk_model(obj)
                if chunk_model:
                    served_model = chunk_model
                choices = obj.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    text_buf.append(piece)
                    offset = len(session.current_text or "")
                    session.current_text = (session.current_text or "") + piece
                    yield {"event": "delta", "text": piece, "offset": offset}
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
        finally:
            if getattr(session, "_http_resp", None) is resp:
                session._http_resp = None
            try:
                resp.close()
            except Exception:
                pass
        return "".join(text_buf), tool_calls, usage, finish_reason, served_model

    def stream_turn(self, session: "AgentSession", messages: List[dict], seq: Optional[int] = None) -> Iterator[dict]:
        """Orchestrates one or more _stream_once() hops: a plain-answer hop
        ends the turn (finalizes session.history/current_text, mirrors what
        each CLI adapter's normalize_line() does at its own "result" event --
        see e.g. ClaudeAdapter.normalize_line, server.py ~line 746); a
        tool_calls hop executes each call against mcp_server.py, appends the
        assistant tool_calls message + the tool results to a *local* messages
        copy, and loops. That local list -- not session.history -- carries
        the in-turn tool back-and-forth; only the final answer text ever
        gets persisted to session.history, same as every CLI adapter already
        does (the CLI's own process holds its tool-call transcript
        internally the same way this loop holds it in `messages`). Raises on
        transport failure -- the caller (AgentSession._run_http_turn) turns
        that into an {"event":"error"}."""
        messages = list(messages)
        tools = _mcp_openai_tools()
        hop_usages: List[dict] = []
        served_model = ""
        for hop in range(1, self.MAX_TOOL_HOPS + 1):
            if seq is not None and getattr(session, "_turn_seq", None) != seq:
                return
            text, tool_calls, raw_usage, finish_reason, hop_model = yield from self._stream_once(session, messages, tools, seq=seq)
            if seq is not None and getattr(session, "_turn_seq", None) != seq:
                return
            if hop_model:
                served_model = hop_model
            nu = self.normalize_usage(raw_usage) if raw_usage else None
            if nu:
                hop_usages.append(nu)

            if finish_reason == "tool_calls" and tool_calls:
                ordered = [tool_calls[i] for i in sorted(tool_calls)]
                sent_calls = [
                    {
                        "id": tc["id"] or f"call_{hop}_{i}",
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"},
                    }
                    for i, tc in enumerate(ordered)
                ]
                messages.append({"role": "assistant", "content": text or None, "tool_calls": sent_calls})
                for tc, sent in zip(ordered, sent_calls):
                    if seq is not None and getattr(session, "_turn_seq", None) != seq:
                        return
                    try:
                        args = json.loads(tc["arguments"] or "{}")
                        if not isinstance(args, dict):
                            args = {}
                    except json.JSONDecodeError:
                        args = {}
                    call_text = _format_tool_call(tc["name"], args) if args else tc["name"]
                    yield {"event": "tool", "text": call_text[:600], "title": tc["name"][:200], "kind": "call", "status": "tool_calls"}
                    if seq is not None and getattr(session, "_turn_seq", None) != seq:
                        return
                    try:
                        result_text = _mcp_call_tool(tc["name"], args)
                    except Exception as e:
                        result_text = json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
                    if seq is not None and getattr(session, "_turn_seq", None) != seq:
                        return
                    # UI log is already [:600]; the model hop was getting the
                    # full MCP payload (read_file up to 500k). Cap what the
                    # next HTTP request sends.
                    if len(result_text) > 32_000:
                        result_text = result_text[:32_000] + "\n… truncated"
                    messages.append({"role": "tool", "tool_call_id": sent["id"], "content": result_text})
                    yield {"event": "tool", "text": _format_tool_result(result_text)[:600], "title": tc["name"][:200] or "result", "kind": "result", "status": "tool_result"}
                session.current_text = ""
                continue  # another hop, now with tool results in messages

            # Plain answer -- occupancy is the last hop's prompt (includes
            # tool results); billed is the sum of every hop's total_tokens.
            # Dropping earlier hops undercounted OmniRoute tool turns.
            usage = None
            if hop_usages:
                last = hop_usages[-1]
                usage = {
                    "input_tokens": int(last.get("input_tokens") or 0),
                    "output_tokens": sum(int(u.get("output_tokens") or 0) for u in hop_usages),
                    "thinking_tokens": sum(int(u.get("thinking_tokens") or 0) for u in hop_usages),
                    "cache_read_tokens": int(last.get("cache_read_tokens") or 0),
                    "total_tokens": sum(int(u.get("total_tokens") or 0) for u in hop_usages),
                }
            if seq is not None and getattr(session, "_turn_seq", None) != seq:
                return
            out = self.finalize_turn(
                session=session,
                text=text,
                raw_usage=usage,
                is_err=False,
                served_model=served_model,
                finish_reason=finish_reason,
            )
            yield out
            return
        yield {"event": "error", "text": f"툴 호출이 {self.MAX_TOOL_HOPS}회를 넘어 강제 종료했습니다냥."}
