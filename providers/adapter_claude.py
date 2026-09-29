"""Claude Code CLI adapter. Callers import from adapters (ADAPTER_SPLIT_v1)."""
from __future__ import annotations

import json
import os
import re
import subprocess

from pathlib import Path
from typing import List, Optional, Tuple

from artifact_manager import _atomic_write_text
from host_config import AGENT_PATH_PREFIX, CLAUDE_BIN, HARD_TOKENS, SOFT_TOKENS, WORKSPACE, _now
from tool_format import _format_tool_call, _format_tool_result
from providers.adapter_base import AgentAdapter, _redact_err


class ClaudeAdapter(AgentAdapter):
    """Multi-Provider plan Phase 1. Ported from VibeCat's
    Standalone/vibecat_host/providers/claude.py (Python, same language --
    near-verbatim) with the Windows/isolated-workspace specifics dropped:
    this host is Linux and uses the REAL $HOME directly (no
    CLAUDE_CONFIG_DIR redirect, no auth-seeding step -- ~/.claude/.credentials.json
    is already a real claude.ai subscription login, confirmed 2026-09-17 via
    `claude auth status`). Also skips VibeCat's --append-system-prompt-file /
    system_head.txt machinery entirely: that exists there to inject a
    dynamically-assembled system head. The persona/rules reach this CLI via
    AgentSession._send_direct()'s first-turn injection, the same text every
    provider gets. Do NOT rely on cwd auto-discovery here: measured
    2026-09-19, Claude Code reads only CLAUDE.md and .claude/skills, never
    AGENTS.md or .agents/skills (docs/plans/instruction-architecture.md F3).
    """

    id = "claude"
    keeps_stdin_open = True

    _NAS_MCP_TOOLS = (
        "ping_nas", "list_services", "service_ctl", "list_dir", "read_file",
        "write_file", "run_command", "sphere_hub_status", "factory_status",
        "hermes_status", "search_text", "wiki",
        "delegate", "ticket", "observation", "memory",
    )
    ALLOWED_TOOLS = ",".join(
        [f"mcp__nas__{t}" for t in _NAS_MCP_TOOLS]
        + ["Read", "Glob", "Grep", "Bash", "Write", "Edit", "Skill", "ToolSearch", "WebFetch", "WebSearch"]
    )
    DISALLOWED_TOOLS = ",".join([
        "mcp__slack__post_message", "mcp__slack__send_message",
        "mcp__notion__create_page", "mcp__notion__update_page", "mcp__m365__send_mail",
    ])

    def find_executable(self) -> str:
        return CLAUDE_BIN

    def _write_mcp_config(self) -> Path:
        """claude_adapter_guidelines.md section 2: the mcp-config JSON key is
        `url`, NOT agy's `serverUrl`. Rewritten on every spawn (cheap, a few
        bytes) rather than kept as a static file, so it self-heals if
        WORKSPACE is ever reset."""
        cfg_path = WORKSPACE / ".mcp.json"
        content = json.dumps({"mcpServers": {"nas": {"type": "http", "url": "http://127.0.0.1:3012/mcp"}}})
        try:
            if cfg_path.is_file() and cfg_path.read_text(encoding="utf-8") == content:
                return cfg_path
        except Exception:
            pass
        _atomic_write_text(cfg_path, content)
        return cfg_path

    def build_args(self, model: str, effort: str, conversation_id: Optional[str], add_dirs: List[str], prompt: str = "") -> List[str]:
        exe = self.find_executable()
        mcp_cfg = self._write_mcp_config()
        args = [
            exe,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--mcp-config", str(mcp_cfg),
            # --setting-sources project without --strict-mcp-config still leaks
            # every MCP server registered in ~/.claude.json (measured by
            # VibeCat: 11 unrelated servers) -- --strict-mcp-config makes
            # --mcp-config the sole MCP source, matching agy's own scoped setup.
            "--strict-mcp-config",
            # Isolates this child from this real account's own ~/.claude
            # skills/plugins (the ones this very assistant session uses) --
            # The character should not inherit them.
            "--setting-sources", "project",
            "--allowedTools", self.ALLOWED_TOOLS,
            "--disallowedTools", self.DISALLOWED_TOOLS,
        ]
        if model and model != "default":
            args.extend(["--model", model])
        if effort and effort != "default":
            args.extend(["--effort", effort.lower()])
        if conversation_id:
            args.extend(["--resume", conversation_id])
        return args

    def build_env(self, home: Path) -> dict:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{AGENT_PATH_PREFIX}:{env.get('PATH','')}"
        # Billing containment (claude_adapter_guidelines.md section 3): any of
        # these makes claude.exe bill an API key instead of the subscription
        # login this host is actually authenticated with. Not currently set
        # on this host (checked 2026-09-17) -- defensive pop, not a fix for
        # an observed problem, in case some other skill/cron ever exports one.
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
            env.pop(k, None)
        return env

    def format_stdin(self, content: str) -> str:
        payload = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": content}]}}
        return json.dumps(payload, ensure_ascii=False) + "\n"

    def normalize_line(self, session: "AgentSession", raw_line: str) -> List[dict]:
        """Ported from claude.py's parse_stdout_line -- same dispatch on
        `type`, retargeted to our event shape (see AgentAdapter.normalize_line
        docstring) instead of VibeCat's step_update/result shape. Unlike agy,
        claude's own text deltas/tool events/history bookkeeping don't need
        session's image-staging side effects (claude doesn't have agy's
        Antigravity-specific generate_image tool convention), so this one
        really is close to a pure per-line function -- it only touches
        `session` for conversation_id capture and history append."""
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            return [{"event": "raw", "text": raw_line[:2000]}]
        if not isinstance(obj, dict):
            return []

        kind = obj.get("type")

        # 1. system / init -- capture claude's own session_id as our conversation_id
        if kind == "system" and obj.get("subtype") == "init":
            sid = obj.get("session_id")
            if sid and not session.conversation_id:
                session.conversation_id = sid
                session.save_meta()
                return [{"event": "system", "text": f"conversation_id={sid}"}]
            return []

        # 2. stream_event -- text streaming deltas only from content_block_delta/text_delta
        if kind == "stream_event":
            ev = obj.get("event") or {}
            delta = ev.get("delta") or {}
            if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                text = delta.get("text") or ""
                if text:
                    rewritten = session._rewrite_artifact_paths(text)
                    offset = len(session.current_text or "")
                    session.current_text = (session.current_text or "") + rewritten
                    return [{"event": "delta", "text": rewritten, "offset": offset, "raw_event": "delta"}]
            if ev.get("type") == "content_block_delta" and delta.get("type") == "thinking_delta":
                text = delta.get("thinking") or ""        # THINKING_VIEW_v1: shown folded, never stored
                return [{"event": "thinking", "text": text}] if text else []
            return []

        # 3. assistant -- whole message; tool_use calls live here. content[].type=="text"
        # arrives after the same text already streamed as deltas -- dropped to avoid
        # doubling the answer (claude_adapter_guidelines.md Gap 6).
        # Exception: synthetic error messages (e.g. rate limit / 429 session limit),
        # which have isApiErrorMessage=true and do NOT stream delta tokens or produce a result event.
        if kind == "assistant":
            if obj.get("isApiErrorMessage") or obj.get("error"):
                err_text = ""
                for block in (obj.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        err_text = block.get("text", "")
                        break
                if not err_text:
                    err_text = str(obj.get("error") or "Claude API 에러")
                msg = f"클로드 세션 한도/오류에 도달했습니다: {err_text}"
                session.history.append({"role": "assistant", "text": msg, "ts": _now()})
                session.save_meta()
                return [
                    {"event": "delta", "text": msg, "raw_event": "delta"},
                    {"event": "result", "text": msg, "error": err_text, "raw_event": "result", "ts": _now()},
                ]

            events: List[dict] = []
            for block in (obj.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                full_name = str(block.get("name") or "tool")
                short_name = full_name.rsplit("__", 1)[-1]
                text = _format_tool_call(short_name, block.get("input") or {})
                events.append({"event": "tool", "text": text[:600], "title": short_name[:200], "kind": "call", "status": "calling"})
            return events

        # 4. user -- tool results flow back as user messages (Gap 7)
        if kind == "user":
            output_str = "ok"
            msg = obj.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                output_str = content
            elif isinstance(content, list) and content:
                first = content[0] if isinstance(content[0], dict) else {}
                c = first.get("content")
                if isinstance(c, str):
                    output_str = c
                elif isinstance(c, list):
                    parts = [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"]
                    if parts:
                        output_str = "".join(parts)
            tur = obj.get("tool_use_result")
            if isinstance(tur, dict) and tur.get("stdout"):
                output_str = str(tur["stdout"])
            return [{"event": "tool", "text": _format_tool_result(output_str)[:600], "title": "result", "kind": "result", "status": "done"}]

        # 5. result -- end of turn (Gap 8: surface permission_denials)
        if kind == "result":
            subtype = obj.get("subtype", "")
            is_err = bool(obj.get("is_error")) or (subtype not in ("success", "") and "error" in subtype)
            text = str(obj.get("result") or obj.get("error") or "")
            denials = obj.get("permission_denials") or []
            if denials:
                denied_names = [d if isinstance(d, str) else d.get("tool_name", str(d)) for d in denials]
                text += f"\n[Permission denied tools: {', '.join(denied_names)}]"

            new_cid = obj.get("session_id")
            if new_cid and not session.conversation_id:
                session.conversation_id = new_cid
                session.save_meta()

            raw_usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
            out = self.finalize_turn(
                session=session,
                text=text,
                raw_usage=raw_usage,
                is_err=is_err,
                error=text if is_err else None,
            )
            return [out]

        # 6. rate_limit_event and anything else -- ignored (same as VibeCat)
        return []

    # --- Provider Capability Model (Phase 0.5) --------------------------------

    def soft_hard_tokens(self, model: str) -> Tuple[int, int]:
        # Verified live 2026-09-17 (real spawn, no --model override -> default
        # model): the result event's modelUsage carries a real contextWindow
        # per model -- "claude-sonnet-5": 1_000_000, but
        # "claude-haiku-4-5-20251001": 200_000. VibeCat's guidelines assumed a
        # flat 200k because they were captured against an older
        # claude-3.x/4.x generation -- current sonnet/opus are already
        # Gemini-1M-scale, only haiku is still the smaller window. Branch on
        # the model name actually asked for rather than assume one number.
        m = (model or "").lower()
        if "haiku" in m:
            return 80_000, 170_000  # ~40%/85% of a real 200k window
        return SOFT_TOKENS, HARD_TOKENS  # sonnet/opus/default: same 1M-scale as agy

    def normalize_usage(self, raw_usage: Optional[dict]) -> Optional[dict]:
        if not raw_usage:
            return None
        input_tokens = int(raw_usage.get("input_tokens") or 0)
        cache_read = int(raw_usage.get("cache_read_input_tokens") or 0)
        cache_creation = int(raw_usage.get("cache_creation_input_tokens") or 0)
        output_tokens = int(raw_usage.get("output_tokens") or 0)
        # thinking_tokens is nested under output_tokens_details, not top-level
        # (verified live 2026-09-17 real result event) -- easy to miss since
        # agy's own usage shape has it as a top-level sibling key.
        thinking_tokens = int((raw_usage.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
        # cache_creation_input_tokens is real spend (writing to the cache) but
        # isn't input_tokens or cache_read_tokens in our canonical shape --
        # folded into input_tokens so total_tokens still reflects the turn's
        # real context size (matches how agy's own total_tokens already
        # behaves per the 2026-09-17 _current_context_tokens fix).
        return {
            "input_tokens": input_tokens + cache_creation,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "cache_read_tokens": cache_read,
            "total_tokens": input_tokens + cache_creation + output_tokens,
        }

    def rate_limit_report(self) -> Optional[dict]:
        """`claude --print "/cost"` runs the interactive /cost slash command
        one-shot and prints the account usage statistics.
        Supports both:
        1) Legacy rate-limit lines: "Current session: 2% used · resets Sep 18, 2:30pm (Asia/Seoul)"
        2) Modern stats summary (Claude Code >= 2.1):
           "Last 24h · 681 requests · 5 sessions"
           "Last 7d · 3513 requests · 30 sessions"
        Rows conform to {group, limit_type, remaining_pct, reset_at}.
        """
        try:
            proc = subprocess.run(
                [self.find_executable(), "--print", "/cost"],
                capture_output=True, text=True, timeout=45,
            )
            rows = []
            # Strip CSI/C0 so post-login banners with colors still parse.
            raw_out = proc.stdout or ""
            stdout = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw_out)
            stdout = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", stdout)
            # Format 1: legacy rate limit
            pattern_legacy = re.compile(r"^(.+?):\s*(\d+)%\s*used\s*·\s*resets\s*(.+)$")
            # Format 2: modern stats summary ("Last 24h · 681 requests · 5 sessions")
            pattern_stats = re.compile(r"^Last\s+([0-9a-zA-Z]+)\s*·\s*(\d+)\s*requests\s*·\s*(\d+)\s*sessions", re.IGNORECASE)

            for line in stdout.splitlines():
                line_str = line.strip()
                m_legacy = pattern_legacy.match(line_str)
                if m_legacy:
                    group, used_pct, reset_at = m_legacy.groups()
                    remaining = max(0, 100 - int(used_pct))
                    rows.append({
                        "group": group.strip(),
                        "limit_type": "사용률",
                        "remaining_pct": f"{remaining}%",
                        "reset_at": reset_at.strip(),
                    })
                    continue

                m_stats = pattern_stats.match(line_str)
                if m_stats:
                    period, req_cnt, sess_cnt = m_stats.groups()
                    rows.append({
                        "group": f"Claude ({period})",
                        "limit_type": f"{sess_cnt} sessions",
                        "remaining_pct": f"{req_cnt} reqs",
                        "reset_at": f"최근 {period} 통계",
                    })

            if rows:
                return {"rows": rows}
            if proc.stderr:
                return {"error": _redact_err(proc.stderr)[:400]}
            return {"error": "/cost 출력에서 사용량 정보를 찾지 못했습니다"}
        except Exception as e:
            return {"error": str(e)}

    def known_models(self) -> List[str]:
        # Aliases, not dated snapshot ids -- claude_adapter_guidelines.md
        # section 2: `--help` documents these as tracking the current
        # generation, so they stay correct as models update underneath them.
        return ["sonnet", "opus", "haiku", "fable"]

    def mints_own_conversation_id(self) -> bool:
        # Verified live 2026-09-17: spawning with `--resume <a fresh uuid
        # claude has never seen>` fails the entire turn --
        # {"is_error":true,...,"errors":["No conversation found with session
        # ID: ..."]} -- it does NOT silently ignore --resume and start fresh.
        # So unlike agy, claude must start with no --resume at all on the
        # first spawn and hand us its own session_id from that turn's
        # system/init (or result) event instead.
        return True
