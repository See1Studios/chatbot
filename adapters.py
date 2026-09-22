"""CLI/API agent adapters. One class per provider, picked via get_adapter().

AgySession / REG / the RLock guard live in session.py.
"""
from __future__ import annotations

import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from host_config import (
    AGENT_PATH_PREFIX,
    AGY,
    CLAUDE_BIN,
    CODEX_BIN,
    DATA,
    DEFAULT_PROVIDER,
    GROK_BIN,
    HARD_TOKENS,
    HOME,
    MODELS,
    SOFT_TOKENS,
    WORKSPACE,
    _now,
)
from artifact_manager import _atomic_write_text
from tool_format import _format_tool_call, _format_tool_result


def _redact_err(text: str) -> str:
    """Helper to redact sensitive credentials from error output."""
    try:
        from session import _redact_text
        return _redact_text(text)
    except Exception:
        # Fallback if session circular import happens
        lines = [l for l in (text or "").splitlines()
                 if not any(k in l.lower() for k in ("token", "authorization", "bearer", "api_key", "refresh"))]
        return "\n".join(lines).strip()


class AgentAdapter:
    """Base interface for spawning/talking to a CLI agent backend.

    Mirrors VibeCat's IAgentAdapter (Source/VibeCat/Private/AgentAdapters.cpp:
    Id/FindExecutable/BuildArgs/FormatStdin/PrepareMcpConfig/NormalizeLine, one
    concrete subclass per provider, picked via a factory) so the same seams
    exist here if another provider is ever wired in.

    2026-09-17: `normalize_line` now exists (Multi-Provider plan Phase 0) --
    `AgyAdapter.normalize_line` takes the owning `AgySession` as a parameter
    rather than being a pure per-line function, because agy's own tool/image
    handling (`AgySession._tool_summary`/`_maybe_capture_conversation_id`)
    has real side effects (image staging, history append, conversation_id
    capture) entangled with parsing one stream-json line -- untangling those
    fully was judged not worth the regression risk on code that's been the
    site of real incidents (see docs/EMERGENCY.md, DEVLOG deadlock entries).
    A future adapter that doesn't need those callbacks just won't use them.
    """

    id = "base"
    keeps_stdin_open = True  # False = one-shot exec per prompt (codex/grok-style), not agy/claude-style persistent stdin
    close_stdin_after_prompt = False  # True = codex/grok-style: close stdin right after writing the prompt
    transport_kind = "process"  # "http" = no subprocess at all (API-Provider plan,
    # docs/plans/api-provider-adapters.md) -- AgySession branches on this before
    # touching self.proc/_spawn()/stdin. Every CLI adapter stays "process" by
    # inheriting this default; only an HTTP-dialect adapter overrides it.

    def find_executable(self) -> str:
        raise NotImplementedError

    def build_args(self, model: str, effort: str, conversation_id: Optional[str], add_dirs: List[str], prompt: str = "") -> List[str]:
        """`prompt` (Multi-Provider plan Phase 2) is only used by one-shot
        exec providers (keeps_stdin_open=False) that need the turn's text
        baked into argv or a prompt file at spawn time -- grok's
        --prompt-file, or a future codex-style provider's stdin-at-spawn.
        agy/claude ignore it; they get their prompt via format_stdin() after
        the (persistent) process is already running."""
        raise NotImplementedError

    def build_env(self, home: Path) -> dict:
        raise NotImplementedError

    def format_stdin(self, content: str) -> str:
        raise NotImplementedError

    def normalize_line(self, session: "AgySession", raw_line: str) -> List[dict]:
        """Parse one raw stdout line from the spawned CLI into zero or more
        canonical session events (the same dict shape `_emit()` already
        expects: {"event": ..., "text": ..., "usage"?, "duration_seconds"?,
        "error"?, ...}). May read/write `session` attributes (current_text,
        pending_images, history, conversation_id) for turn-scoped state and
        history persistence -- see class docstring."""
        raise NotImplementedError

    # --- Provider Capability Model (Multi-Provider plan Phase 0.5) -----------
    # Every one of these differs by real, measured amounts across agy/claude/
    # grok (see plan file smooth-hopping-bear.md) -- usage key names, context
    # window size, whether a one-shot rate-limit report even exists, effort
    # vocabularies, and who mints the conversation id. Centralizing them here
    # means `_session_weight()`/`/api/usage`/history storage ask "this
    # session's adapter" instead of hardcoding agy's numbers/shapes.

    def soft_hard_tokens(self, model: str) -> Tuple[int, int]:
        """(soft, hard) token thresholds for `_session_weight()`'s rotation
        warning/force-rotate levels, scaled to this provider's real context
        window. Base default is agy's own empirically-tuned constants --
        every other adapter MUST override with its own numbers, not inherit
        this by accident."""
        return SOFT_TOKENS, HARD_TOKENS

    def normalize_usage(self, raw_usage: Optional[dict]) -> Optional[dict]:
        """Provider-native usage dict -> our canonical
        {input_tokens, output_tokens, thinking_tokens, cache_read_tokens,
        total_tokens} shape (what the token badge / _session_weight / history
        already read). None in, or a provider that doesn't surface usage at
        all (e.g. codex) -> None out, so the UI hides the badge instead of
        showing a zero or wrong number."""
        return raw_usage

    def rate_limit_report(self) -> Optional[dict]:
        """One-shot rate-limit/usage report for the 상태 탭 사용량 바, if this
        CLI has an equivalent of `agy --print /usage`. None = not
        supported by this provider -- caller must show "지원 안 함", not an
        error. Claude uses `--print /cost`; Grok uses the same billing proxy
        the TUI `/usage` modal hits; Codex uses its app-server protocol."""
        return None

    def mints_own_conversation_id(self) -> bool:
        """False (default, agy's behavior): we generate a uuid4 before the
        first spawn and pass it in, specifically to stop the CLI from
        auto-resuming some unrelated stale conversation of its own (see the
        2026-09-17 DEVLOG entry on agy's --conversation auto-resume bug).
        True: the CLI mints its own id on the first turn (from an init/
        result-shaped event) and we must capture that instead of pre-
        assigning one -- verify this per-provider before flipping it,
        don't assume."""
        return False

    def known_models(self) -> List[str]:
        """Model names/aliases to offer in the frontend's model dropdown for
        this provider. Empty = no fixed list to guess at (leaves the
        dropdown at just the CLI's own default) -- don't invent one."""
        return []

    def available(self) -> bool:
        """Whether this provider's CLI is actually installed on this host --
        the frontend uses this to grey out a provider option instead of
        letting the user pick one that will just fail to spawn."""
        exe = self.find_executable()
        return bool(exe) and (shutil.which(exe) is not None or Path(exe).exists())

    def interrupt(self, proc: Optional[subprocess.Popen]) -> bool:
        """Interrupt an in-flight turn if supported by this provider.
        Returns True if an interrupt signal was dispatched."""
        if not proc or proc.poll() is not None:
            return False
        try:
            proc.send_signal(signal.SIGINT)
            return True
        except Exception:
            try:
                proc.terminate()
                return True
            except Exception:
                return False

    def finalize_turn(
        self,
        session: Any,
        text: str,
        raw_usage: Optional[dict],
        is_err: bool = False,
        error: Optional[str] = None,
        served_model: Optional[str] = None,
        images: Optional[List[str]] = None,
    ) -> dict:
        """Single end-of-turn finalizer for all adapters (T3.1).

        Normalizes usage, rewrites artifact paths, appends images, creates and
        persists history item, clears current_text and pending_images, and returns
        the canonical result event.
        """
        final = session._rewrite_artifact_paths(session.current_text or text)
        final = session._append_images_markdown(final, session.turn_started_at or None)

        # Append pending images or passed images
        img_list = list(images if images is not None else getattr(session, "pending_images", []) or [])
        for url in img_list:
            if url and url not in final:
                final = (final.rstrip() + f"\n\n![]({url})\n") if final.strip() else f"![]({url})\n"

        usage = self.normalize_usage(raw_usage) if raw_usage else None
        duration_seconds = None
        if getattr(session, "turn_started_at", 0) > 0:
            duration_seconds = round(_now() - session.turn_started_at, 2)

        ts = _now()
        hist_item: dict = {"role": "assistant", "text": "" if is_err else final, "ts": ts}
        if is_err and error:
            hist_item["error"] = error
        if usage:
            hist_item["usage"] = usage
        if duration_seconds is not None:
            hist_item["duration_seconds"] = duration_seconds
        stamp_served_model(session, hist_item, captured=served_model)

        if final or is_err:
            session.history.append(hist_item)
            session.save_meta()

        session.current_text = ""
        session.pending_images = []

        out_ev = {
            "event": "result",
            "text": "" if is_err else final,
            "raw_event": "result",
            "ts": ts,
        }
        if usage:
            out_ev["usage"] = usage
        if duration_seconds is not None:
            out_ev["duration_seconds"] = duration_seconds
        if is_err and error:
            out_ev["error"] = error
        stamp_served_model(session, hist_item, out_ev, captured=served_model)
        return out_ev


# agy ends a turn with an EMPTY result when this elapses -- and the agent may keep working unseen.
AGY_PRINT_TIMEOUT_SEC = 8 * 60


class AgyAdapter(AgentAdapter):
    id = "agy"
    keeps_stdin_open = True

    def find_executable(self) -> str:
        return AGY

    def known_models(self) -> List[str]:
        return MODELS

    def build_args(self, model: str, effort: str, conversation_id: Optional[str], add_dirs: List[str], prompt: str = "") -> List[str]:
        args = [
            self.find_executable(),
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--print-timeout", f"{AGY_PRINT_TIMEOUT_SEC // 60}m",
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
        env["PATH"] = f"{AGENT_PATH_PREFIX}:{env.get('PATH','')}"
        mcp_cfg = WORKSPACE / ".gemini" / "config" / "mcp_config.json"
        if mcp_cfg.exists():
            env["AGY_WORKSPACE"] = str(WORKSPACE)
        return env

    def format_stdin(self, content: str) -> str:
        return json.dumps({"event": "user", "message": {"content": content}}, ensure_ascii=False) + "\n"

    def normalize_line(self, session: "AgySession", raw_line: str) -> List[dict]:
        """Moved verbatim out of `AgySession._handle_stdout_line` (Multi-Provider
        plan Phase 0) -- same parsing, same session-mutation order, same
        returned event shapes. Only structural change: events are collected
        and returned instead of emitted inline, so `_handle_stdout_line` can
        stay provider-agnostic (see AgentAdapter.normalize_line docstring for
        why this still takes `session` instead of being a pure function)."""
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            return [{"event": "raw", "text": raw_line[:2000]}]
        if not isinstance(obj, dict):
            return []

        session._maybe_capture_conversation_id(obj)
        session._observe_agent_step(obj)

        events: List[dict] = []
        tool_ev = session._tool_summary(obj)
        if tool_ev:
            if isinstance(tool_ev, list):
                events.extend(tool_ev)
            else:
                events.append(tool_ev)

        ev = obj.get("event") or obj.get("type") or "message"
        text = ""
        is_delta = False
        step = obj.get("step_update")
        if isinstance(step, dict) and step.get("step_type") == "agent_response" and isinstance(step.get("text_delta"), str):
            text = step.get("text_delta") or ""
            ev = "delta"
            is_delta = True
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
            is_delta = True

        if text:
            text = session._rewrite_artifact_paths(text)

        # Compute delta_offset AFTER rewrite so the client assistantBuf index
        # matches the server-side rewritten-length counter (P2 fix).
        delta_offset = None
        if is_delta and text is not None:
            delta_offset = len(session.current_text or "")
            session.current_text = (session.current_text or "") + text

        if ev == "result":
            res_obj = obj.get("result") if isinstance(obj.get("result"), dict) else {}
            raw_usage = res_obj.get("usage") if isinstance(res_obj.get("usage"), dict) else None
            res_err = str(res_obj.get("error") or obj.get("error") or "")
            is_err = bool(res_err)
            out_ev = self.finalize_turn(
                session=session,
                text=text,
                raw_usage=raw_usage,
                is_err=is_err,
                error=res_err if is_err else None,
            )
            final = out_ev.get("text") or ""
            duration_seconds = out_ev.get("duration_seconds")
            status = str(res_obj.get("status") or "")
            dur = float(res_obj.get("duration_seconds") or duration_seconds or 0)
            if not session._stop_requested and (
                status not in ("", "SUCCESS")
                or (not final.strip() and dur >= 0.9 * AGY_PRINT_TIMEOUT_SEC)
            ):
                session._end_unfinished_turn(status, res_err, dur)
            events.append(out_ev)
        elif ev in ("assistant", "message", "delta", "error", "system") or (ev in ("tool_use", "tool_result") and not tool_ev):
            out = {"event": ev, "text": text, "raw_event": ev}
            if ev == "delta" and delta_offset is not None:
                out["offset"] = delta_offset
            if obj.get("error"):
                out["error"] = obj.get("error")
            events.append(out)
        elif not tool_ev:
            events.append({"event": "agy", "text": text, "payload": {k: obj.get(k) for k in list(obj)[:12]}})

        return events

    def rate_limit_report(self) -> Optional[dict]:
        """`agy --print /usage` -- the CLI's own rate-limit report; unavailable
        inside a stream-json session, must be a separate one-shot invocation.
        Moved out of the old module-level `_get_usage()` (Multi-Provider plan
        Phase 0.5) so that function can become a generic provider-dispatching
        + caching wrapper instead of hardcoding this agy-only subprocess call."""
        try:
            proc = subprocess.run([self.find_executable(), "--print", "/usage"], capture_output=True, text=True, timeout=30)
            rows = []
            for line in (proc.stdout or "").splitlines():
                parts = [p.strip() for p in line.split("\t")]
                if len(parts) >= 4:
                    rows.append({"group": parts[0], "limit_type": parts[1], "remaining_pct": parts[2], "reset_at": parts[3]})
            if not rows and proc.stderr:
                return {"error": _redact_err(proc.stderr)[:400]}
            return {"rows": rows}
        except Exception as e:
            return {"error": str(e)}


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
    AgySession._send_direct()'s first-turn injection, the same text every
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
            # 냥피디 should not inherit them.
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

    def normalize_line(self, session: "AgySession", raw_line: str) -> List[dict]:
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
                msg = f"클로드 세션 한도/오류에 도달했습니다냥: {err_text}"
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
                capture_output=True, text=True, timeout=30,
            )
            rows = []
            stdout = proc.stdout or ""
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


def _grok_tool_display(obj: dict) -> Tuple[str, dict]:
    """grok routes every MCP call through one generic `use_tool` dispatcher
    tool (rawInput.tool_name/tool_input names the real target) rather than
    claude's one-distinct-tool-per-MCP-tool model -- verified live 2026-09-17
    calling mcp__nas__ping_nas-equivalent through grok. Unwrap it so the tool
    card shows the real tool name instead of a generic "use_tool" for every
    single MCP call."""
    tool_name = str(obj.get("toolName") or obj.get("title") or "tool")
    raw_input = obj.get("rawInput") if isinstance(obj.get("rawInput"), dict) else {}
    if tool_name == "use_tool" and raw_input.get("tool_name"):
        inner = str(raw_input["tool_name"])
        # grok's own MCP tool naming is "<server>__<tool>" (no claude-style
        # mcp__ prefix) -- verified live: "nas__ping_nas".
        short = inner.rsplit("__", 1)[-1]
        return short, (raw_input.get("tool_input") if isinstance(raw_input.get("tool_input"), dict) else {})
    return tool_name, raw_input


def _grok_tool_output_text(obj: dict) -> str:
    content = obj.get("content")
    if isinstance(content, list):
        parts = []
        for c in content:
            inner = c.get("content") if isinstance(c, dict) else None
            if isinstance(inner, dict) and inner.get("type") == "text":
                parts.append(str(inner.get("text") or ""))
        if parts:
            return "".join(parts)
    raw_out = obj.get("rawOutput")
    if isinstance(raw_out, dict):
        out = raw_out.get("output")
        if isinstance(out, dict):
            for k in ("OkayOutput", "output", "stdout"):
                if k in out:
                    return str(out[k])
        if raw_out.get("stdout"):
            return str(raw_out.get("stdout"))
    return "ok"


_GROK_PERIOD_LABEL = {
    "USAGE_PERIOD_TYPE_WEEKLY": "주간",
    "USAGE_PERIOD_TYPE_MONTHLY": "월간",
    "USAGE_PERIOD_TYPE_DAILY": "일간",
    "USAGE_PERIOD_TYPE_HOURLY": "시간",
}


def _grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME") or str(HOME / ".grok"))


def _grok_access_token() -> Optional[str]:
    """Read grok CLI's own OIDC access token (same file `grok login` writes).
    Adapter-only — not 냥피디 memory SSOT."""
    try:
        data = json.loads((_grok_home() / "auth.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    best_key = None
    best_rank = ""
    for v in data.values():
        if not isinstance(v, dict):
            continue
        key = v.get("key")
        if not key:
            continue
        rank = str(v.get("expires_at") or v.get("create_time") or "")
        if best_key is None or rank > best_rank:
            best_key = str(key)
            best_rank = rank
    return best_key


def _grok_billing_to_rows(payload: dict) -> List[dict]:
    """Grok TUI `/usage` credits config -> status-tab row shape.
    `creditUsagePercent` / `productUsage[].usagePercent` are "% used";
    remaining_pct is inverted to match agy/claude bars."""
    cfg = payload.get("config") if isinstance(payload, dict) else None
    if not isinstance(cfg, dict):
        return []
    period = cfg.get("currentPeriod") if isinstance(cfg.get("currentPeriod"), dict) else {}
    label = _GROK_PERIOD_LABEL.get(str(period.get("type") or ""), "한도")
    reset_at = str(period.get("end") or cfg.get("billingPeriodEnd") or "")
    rows: List[dict] = []
    # The proxy answers in protobuf-JSON, which DROPS zero-valued scalars: a
    # credits response for an account at 0% used carries no `creditUsagePercent`
    # (and no `usagePercent` per product) at all. So "field absent" in a
    # credits-shaped response means 0% used, not "no data" -- the grok TUI
    # /usage reads the same single endpoint and shows 0% there (2026-09-19,
    # docs/providers/grok.md G11). A response with neither the percent nor the
    # credits shape is still "no data".
    credits_shaped = isinstance(cfg.get("currentPeriod"), dict) or bool(cfg.get("billingPeriodEnd"))
    products = cfg.get("productUsage")
    if isinstance(products, list):
        for item in products:
            if not isinstance(item, dict) or (item.get("usagePercent") is None and not item.get("product")):
                continue
            try:
                used = float(item.get("usagePercent") or 0)
            except (TypeError, ValueError):
                continue
            remaining = max(0, min(100, int(round(100 - used))))
            rows.append({
                "group": str(item.get("product") or "Grok"),
                "limit_type": label,
                "remaining_pct": f"{remaining}%",
                "reset_at": reset_at,
            })
    if not rows and (cfg.get("creditUsagePercent") is not None or credits_shaped):
        try:
            used = float(cfg.get("creditUsagePercent") or 0)
        except (TypeError, ValueError):
            used = 0.0
        remaining = max(0, min(100, int(round(100 - used))))
        rows.append({
            "group": "Grok",
            "limit_type": label,
            "remaining_pct": f"{remaining}%",
            "reset_at": reset_at,
        })
    return rows


def _fetch_grok_billing(token: str) -> dict:
    base = (os.environ.get("GROK_CLI_CHAT_PROXY_BASE_URL") or "https://cli-chat-proxy.grok.com/v1").rstrip("/")
    req = Request(
        base + "/billing?format=credits",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "User-Agent": "grok-cli",
        },
    )
    with urlopen(req, timeout=30) as resp:
        raw = resp.read()
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Grok billing 응답이 JSON 객체가 아닙니다")
    return obj


def _codex_rate_limit_to_rows(payload: dict) -> List[dict]:
    """Codex app-server `account/rateLimits/read` -> status-tab row shape."""
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        singular = payload.get("rateLimits")
        buckets = {"codex": singular} if isinstance(singular, dict) else {}
    rows: List[dict] = []
    for bucket_id, snapshot in buckets.items():
        if not isinstance(snapshot, dict):
            continue
        group = str(snapshot.get("limitName") or snapshot.get("normalModelSlug") or snapshot.get("limitId") or bucket_id or "Codex")
        for key, fallback in (("primary", "기본"), ("secondary", "보조")):
            window = snapshot.get(key)
            if not isinstance(window, dict) or window.get("usedPercent") is None:
                continue
            try:
                remaining = max(0, min(100, int(round(100 - float(window["usedPercent"])))))
            except (TypeError, ValueError):
                continue
            try:
                minutes = int(window.get("windowDurationMins"))
            except (TypeError, ValueError):
                minutes = 0
            limit_type = f"{minutes // 1440}일" if minutes >= 1440 and minutes % 1440 == 0 else (f"{minutes}분" if minutes else fallback)
            try:
                reset_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(window.get("resetsAt"))))
            except (TypeError, ValueError, OverflowError, OSError):
                reset_at = "-"
            rows.append({"group": group, "limit_type": limit_type, "remaining_pct": f"{remaining}%", "reset_at": reset_at})
    return rows


def _fetch_codex_rate_limits(executable: str) -> dict:
    """Read Codex's authenticated local app-server; credentials stay internal."""
    proc = subprocess.Popen([executable, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        if not proc.stdin or not proc.stdout:
            raise RuntimeError("Codex app-server 입출력을 열 수 없습니다")
        for request in (
            {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "nyangpd-chatbot", "version": "1.0"}}},
            {"id": 2, "method": "account/rateLimits/read", "params": {"excludeResetCreditDetails": True}},
        ):
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            readable, _, _ = select.select([proc.stdout], [], [], 0.5)
            if not readable:
                continue
            try:
                response = json.loads(proc.stdout.readline())
            except json.JSONDecodeError:
                continue
            if response.get("id") != 2:
                continue
            if response.get("error"):
                raise RuntimeError(str(response["error"].get("message") or response["error"]))
            result = response.get("result")
            if isinstance(result, dict):
                return result
            raise RuntimeError("Codex 사용량 응답 형식이 올바르지 않습니다")
        raise TimeoutError("Codex 사용량 조회가 20초 안에 응답하지 않았습니다")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


class GrokAdapter(AgentAdapter):
    """Multi-Provider plan Phase 2. One-shot exec, not persistent stdin
    (keeps_stdin_open=False) -- every turn is its own `grok` process that
    exits when done; AgySession._send_direct()/_spawn() branch on this.

    VibeCat's own guidelines for grok were captured against an older CLI
    build and turned out stale in several ways once checked live against
    the 1.0.25 actually installed here (`grok --help` re-run 2026-09-17):
    `--trust` isn't even in `--help`'s own listing but is required and
    accepted anyway (a real, if undocumented, flag -- confirmed by testing:
    without it, `grok mcp doctor` reports "folder untrusted" and MCP tools
    are unreachable; with it, project-scoped MCP tools actually connect and
    get called). `--reasoning-effort` is the primary flag name now
    (`--effort` is only a compat alias). None of VibeCat's `--allow`/`--deny`
    tool-scoping is used here either -- matches VibeCat's OWN choice for
    grok (only claude got an allow/deny list there), and grok routes every
    MCP call through one generic `use_tool` dispatcher rather than
    per-tool flags anyway, so `--always-approve` is the only gate.
    """

    id = "grok"
    keeps_stdin_open = False

    def find_executable(self) -> str:
        return GROK_BIN

    def _ensure_mcp_registered(self) -> None:
        """`grok mcp add --scope project` writes WORKSPACE/.grok/config.toml
        once; idempotent re-check-then-add rather than re-running the CLI
        subprocess on every single turn (each turn is already its own
        process spawn for this provider -- no need to add another)."""
        cfg_path = WORKSPACE / ".grok" / "config.toml"
        want_url = "http://127.0.0.1:3012/mcp"
        try:
            if cfg_path.exists() and want_url in cfg_path.read_text(encoding="utf-8"):
                return
        except Exception:
            pass
        try:
            subprocess.run(
                [self.find_executable(), "mcp", "add", "--transport", "http", "--scope", "project", "nas", want_url],
                cwd=str(WORKSPACE),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            pass

    def build_args(self, model: str, effort: str, conversation_id: Optional[str], add_dirs: List[str], prompt: str = "") -> List[str]:
        exe = self.find_executable()
        self._ensure_mcp_registered()
        # Unique per spawn, not a fixed shared filename -- two concurrent
        # grok sessions (different browser tabs, both one-shot-exec so both
        # legitimately spawn at once) would otherwise overwrite each other's
        # prompt file mid-flight. Left on disk after the turn (harmless,
        # tiny) rather than cleaned up here, since the process reads it
        # asynchronously after this call returns.
        prompt_path = WORKSPACE / ".grok" / "prompts" / f".grok_prompt_{uuid.uuid4().hex}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt or "", encoding="utf-8")
        self._last_prompt_path = prompt_path
        args = [
            exe,
            "--prompt-file", str(prompt_path),
            "--output-format", "streaming-json",
            "--always-approve",
            "--trust",
        ]
        if model and model != "default":
            args.extend(["--model", model])
        if effort and effort != "default":
            args.extend(["--reasoning-effort", effort])
        if conversation_id:
            args.extend(["--resume", conversation_id])
        return args

    def build_env(self, home: Path) -> dict:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{AGENT_PATH_PREFIX}:{env.get('PATH','')}"
        # Billing containment, grok's own equivalent of claude's env vars
        # (claude_adapter_guidelines.md section 3's list plus XAI_API_KEY,
        # which that same doc calls out as grok's variant) -- not currently
        # set on this host, defensive only.
        env.pop("XAI_API_KEY", None)
        return env

    def format_stdin(self, content: str) -> str:
        # Prompt goes via --prompt-file at spawn time (build_args), not
        # stdin -- empty return tells _send_direct() there's nothing further
        # to write after spawning.
        return ""

    def normalize_line(self, session: "AgySession", raw_line: str) -> List[dict]:
        """Shaped from a real live capture (2026-09-17, this exact grok
        1.0.25 binary) via `grok --prompt-file <f> --output-format
        streaming-json --always-approve --trust`, not from VibeCat's
        (stale, older-version) documented contract -- see class docstring."""
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            return [{"event": "raw", "text": raw_line[:2000]}]
        if not isinstance(obj, dict):
            return []

        kind = obj.get("type")

        # available_commands: repeated boilerplate (skills/tools catalog),
        # not turn content -- ignore.
        if kind == "available_commands":
            return []

        # thought: internal reasoning streamed word-by-word -- never
        # surfaced, same convention as claude's thinking blocks.
        if kind == "thought":
            return []

        # text: the actual answer. Arrived as a single whole-answer frame in
        # simple test turns and could plausibly stream in multiple frames for
        # longer answers -- treat as a delta either way (accumulate, don't
        # assume it's the only one).
        if kind == "text":
            text = obj.get("data") or ""
            if not text:
                return []
            offset = len(session.current_text or "")
            rewritten = session._rewrite_artifact_paths(text)
            session.current_text = (session.current_text or "") + rewritten
            return [{"event": "delta", "text": rewritten, "offset": offset, "raw_event": "delta"}]

        if kind == "tool_call":
            name, args = _grok_tool_display(obj)
            text = _format_tool_call(name, args)
            return [{"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": "calling"}]

        if kind == "tool_call_update":
            if obj.get("status") != "completed":
                return []
            name, _args = _grok_tool_display(obj)
            out = _grok_tool_output_text(obj)
            return [{"event": "tool", "text": _format_tool_result(out)[:600], "title": "result", "kind": "result", "status": "done"}]

        # usage: redundant with `end`'s own usage field -- ignore here,
        # normalize once at end-of-turn instead of twice.
        if kind == "usage":
            return []

        if kind == "end":
            stop_reason = obj.get("stopReason") or ""
            is_err = stop_reason not in ("end_turn",) or bool(obj.get("error"))
            # sessionId lands on `end`. Capture it *before* rewriting
            # `images/1.jpg` so the grok session folder can be found on the
            # first Imagine turn (live 2026-09-21: rewrite ran with cid=None).
            new_cid = obj.get("sessionId") or obj.get("session_id")
            if isinstance(new_cid, str):
                new_cid = new_cid.strip()
            if new_cid and not session.conversation_id:
                session.conversation_id = new_cid
                session.save_meta()

            raw_usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
            err_msg = stop_reason or str(obj.get("error") or "error") if is_err else None
            out_ev = self.finalize_turn(
                session=session,
                text="",
                raw_usage=raw_usage,
                is_err=is_err,
                error=err_msg,
            )
            return [out_ev]

        return []

    # --- Provider Capability Model (Phase 0.5) --------------------------------

    def soft_hard_tokens(self, model: str) -> Tuple[int, int]:
        # No confirmed contextWindow figure for grok-4.6 the way claude's
        # modelUsage exposed one live (2026-09-17 capture had no equivalent
        # field) -- xAI's public docs put grok-4-class models at 256k-2M
        # depending on variant, so inheriting agy's 150k/400k (tuned for a
        # ~1M-scale window) is a deliberately conservative placeholder, not a
        # verified number. Revisit once real grok sessions accumulate usage
        # data to tune against, same as agy's own constants were.
        return SOFT_TOKENS, HARD_TOKENS

    def normalize_usage(self, raw_usage: Optional[dict]) -> Optional[dict]:
        if not raw_usage:
            return None
        input_tokens = int(raw_usage.get("input_tokens") or 0)
        cache_read = int(raw_usage.get("cache_read_input_tokens") or 0)
        cache_creation = int(raw_usage.get("cache_creation_input_tokens") or 0)
        output_tokens = int(raw_usage.get("output_tokens") or 0)
        thinking_tokens = int(raw_usage.get("reasoning_tokens") or 0)
        return {
            "input_tokens": input_tokens + cache_creation,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "cache_read_tokens": cache_read,
            "total_tokens": input_tokens + cache_creation + output_tokens,
        }

    def rate_limit_report(self) -> Optional[dict]:
        """Account-wide Grok Build credit remaining (TUI `/usage` / `/cost`).

        `grok usage <session_id>` is still per-session cost (already on each
        turn). There is no session-less CLI subcommand, but grok 1.0.34's
        billing client GETs `{GROK_CLI_CHAT_PROXY_BASE_URL}/billing?format=credits`
        with the OIDC token from `grok login` (verified live 2026-09-18).
        Parsed into agy/claude's {group, limit_type, remaining_pct, reset_at}
        row shape so the status-tab bar renders unchanged; remaining_pct is
        inverted from `creditUsagePercent` ("% used").
        """
        token = _grok_access_token()
        if not token:
            return {"error": "Grok 로그인이 필요합니다 (grok login)"}
        try:
            payload = _fetch_grok_billing(token)
        except HTTPError as e:
            if e.code not in (401, 403):
                return {"error": f"Grok billing HTTP {e.code}"}
            # Token may be stale; `grok models` is a cheap call that goes
            # through the CLI's own refresh path, then we re-read auth.json.
            try:
                subprocess.run(
                    [self.find_executable(), "models"],
                    capture_output=True, text=True, timeout=20,
                )
            except Exception:
                pass
            token = _grok_access_token()
            if not token:
                return {"error": "Grok 인증이 만료됐습니다. grok login 후 다시 시도해 주세요"}
            try:
                payload = _fetch_grok_billing(token)
            except Exception as e2:
                return {"error": str(e2)[:400]}
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
            return {"error": str(e)[:400]}
        except Exception as e:
            return {"error": str(e)[:400]}
        rows = _grok_billing_to_rows(payload)
        if not rows:
            return {"error": "Grok billing 출력에서 사용량 정보를 찾지 못했습니다"}
        return {"rows": rows}

    def known_models(self) -> List[str]:
        # From `grok models` output (2026-09-17): "grok-4.6 (default)",
        # "grok-4.5".
        return ["grok-4.6", "grok-4.5"]

    def mints_own_conversation_id(self) -> bool:
        # Verified live 2026-09-17: `--resume <a fresh uuid grok has never
        # seen>` doesn't start a fresh session either -- it fails harder than
        # claude's, exiting non-zero before emitting any NDJSON at all
        # ("Error: Failed to restore session from remote: ... 404 Not
        # Found"). Same handling as claude: no --resume on the first spawn,
        # capture the real sessionId from the first turn's `end` event.
        return True


class CodexAdapter(AgentAdapter):
    """Multi-Provider plan Phase 3. Originally scoped "design only, codex not
    installed" -- 실장님 installed codex-cli 0.154.0 on this host mid-Phase-2,
    so this got the same live-verification treatment as claude/grok instead
    of staying a paper design.

    One-shot exec like grok (keeps_stdin_open=False), but prompt delivery
    matches VibeCat's own choice for codex specifically: stdin with a
    trailing `-` positional arg (close_stdin_after_prompt=True), not a
    prompt file. Verified live both ways (a positional prompt arg, and
    piping via stdin with `-`) -- kept the stdin form since it avoids any
    ARG_MAX concern for a long handoff-summary prompt that a positional argv
    string would eventually hit.
    """

    id = "codex"
    keeps_stdin_open = False
    close_stdin_after_prompt = True

    def find_executable(self) -> str:
        return CODEX_BIN

    def build_args(self, model: str, effort: str, conversation_id: Optional[str], add_dirs: List[str], prompt: str = "") -> List[str]:
        exe = self.find_executable()
        args = [exe, "exec"]
        if conversation_id:
            args.extend(["resume", conversation_id])
        args.extend([
            "--json",
            # Isolates this child from ~/.codex/config.toml (same reasoning
            # as claude's --setting-sources project) -- the -c mcp_servers.nas
            # override below is then the sole MCP source, no need for a
            # claude-style --strict-mcp-config since there's no user config
            # left to leak from.
            "--ignore-user-config",
            "--skip-git-repo-check",
            "-c", "mcp_servers.nas.url=http://127.0.0.1:3012/mcp",
            # Tried VibeCat's own choice first (--approve-for-me: workspace-
            # write sandbox via automatic review) and hit two real problems
            # live 2026-09-17: (1) this host's kernel doesn't support user
            # namespaces, so every bwrap-sandboxed shell command fails once
            # ("Creating new namespace failed") before transparently retrying
            # unsandboxed -- a wasted round-trip on every single shell tool
            # call; (2) it's rejected outright on `codex exec resume`
            # ("error: unexpected argument '--approve-for-me' found") --
            # resume keeps whatever approval/sandbox mode the thread started
            # with, and without an explicit override that mode defaults to
            # requiring interactive approval, which then hard-blocks even
            # MCP tool calls with nobody able to approve them
            # ("MCP tool call requires approval, but approval policy is
            # never"). --dangerously-bypass-approvals-and-sandbox works
            # identically on both the first turn and every resume, and is no
            # more permissive in practice on this host than agy's own
            # --dangerously-skip-permissions already is for every provider
            # here -- same trust model, same single-operator NAS context.
            "--dangerously-bypass-approvals-and-sandbox",
        ])
        if model and model != "default":
            args.extend(["-m", model])
        if effort and effort != "default":
            args.extend(["-c", f'model_reasoning_effort="{effort}"'])
        args.append("-")  # prompt on stdin
        return args

    def build_env(self, home: Path) -> dict:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{AGENT_PATH_PREFIX}:{env.get('PATH','')}"
        # Billing containment, codex's variant of the same footgun claude/grok
        # have -- this host's auth is ChatGPT-subscription mode (confirmed via
        # `codex doctor`: "stored auth mode: chatgpt"), not currently set,
        # defensive only.
        env.pop("OPENAI_API_KEY", None)
        return env

    def format_stdin(self, content: str) -> str:
        return content if content.endswith("\n") else content + "\n"

    def normalize_line(self, session: "AgySession", raw_line: str) -> List[dict]:
        """Shaped from a real live capture (2026-09-17, codex-cli 0.154.0)
        via `codex exec --json --ignore-user-config --approve-for-me
        --skip-git-repo-check -c mcp_servers.nas.url=... -`, cross-checked
        against VibeCat's documented contract (thread.started/item.*/
        turn.completed matched closely) but with the actual usage key names
        VibeCat didn't have right (cached_input_tokens/
        cache_write_input_tokens/reasoning_output_tokens, not
        cache_read_input_tokens/cache_creation_input_tokens/thinking_tokens)."""
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            return [{"event": "raw", "text": raw_line[:2000]}]
        if not isinstance(obj, dict):
            return []

        kind = obj.get("type")

        if kind == "thread.started":
            tid = obj.get("thread_id")
            if tid and not session.conversation_id:
                session.conversation_id = tid
                session.save_meta()
                return [{"event": "system", "text": f"conversation_id={tid}"}]
            return []

        if kind == "turn.started":
            return []

        item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
        itype = item.get("type")

        if kind == "item.started":
            if itype == "mcp_tool_call":
                name = str(item.get("tool") or "tool")
                server = item.get("server")
                if server:
                    name = f"{server}/{name}"
                text = _format_tool_call(name, item.get("arguments") or {})
                return [{"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": "calling"}]
            if itype == "command_execution":
                text = _format_tool_call("run_command", {"command": item.get("command")})
                return [{"event": "tool", "text": text[:600], "title": "run_command", "kind": "call", "status": "calling"}]
            return []

        if kind == "item.completed":
            # item.type=="error" here is an informational notice (verified
            # live: "Skill descriptions were shortened to fit the skills
            # context budget..."), not a turn failure -- ignored like a
            # system aside, same treatment as grok's available_commands
            # noise.
            if itype == "error":
                return []
            if itype == "agent_message":
                text = str(item.get("text") or "")
                if not text:
                    return []
                # Arrives as one complete block per captured turns, not
                # streamed deltas -- accumulate the same way regardless, in
                # case a longer answer ever splits into more than one.
                offset = len(session.current_text or "")
                rewritten = session._rewrite_artifact_paths(text)
                session.current_text = (session.current_text or "") + rewritten
                return [{"event": "delta", "text": rewritten, "offset": offset, "raw_event": "delta"}]
            if itype == "mcp_tool_call":
                name = str(item.get("tool") or "tool")
                server = item.get("server")
                if server:
                    name = f"{server}/{name}"
                out_text = "ok"
                result = item.get("result")
                if isinstance(result, dict):
                    content = result.get("content")
                    if isinstance(content, list):
                        parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                        if parts:
                            out_text = "".join(parts)
                elif item.get("error"):
                    out_text = str(item.get("error"))
                return [{"event": "tool", "text": _format_tool_result(out_text)[:600], "title": "result", "kind": "result", "status": "done"}]
            if itype == "command_execution":
                out_text = str(item.get("aggregated_output") or "ok")
                return [{"event": "tool", "text": _format_tool_result(out_text)[:600], "title": "result", "kind": "result", "status": "done"}]
            return []

        if kind == "turn.completed":
            raw_usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
            out_ev = self.finalize_turn(
                session=session,
                text="",
                raw_usage=raw_usage,
                is_err=False,
            )
            return [out_ev]

        # turn.failed / top-level error: not captured live (the
        # nonexistent-resume-id failure exited before emitting any JSON at
        # all, same failure shape as grok), handled defensively per
        # VibeCat's own pattern rather than left unhandled.
        if kind in ("turn.failed", "error"):
            session.current_text = ""
            err = str(obj.get("message") or obj.get("error") or kind)
            return [{"event": "result", "text": "", "raw_event": "result", "error": err, "ts": _now()}]

        return []

    # --- Provider Capability Model (Phase 0.5) --------------------------------

    def soft_hard_tokens(self, model: str) -> Tuple[int, int]:
        # No confirmed context-window figure surfaced anywhere in codex's own
        # output (unlike claude's modelUsage.contextWindow) -- inheriting
        # agy's 150k/400k as a deliberate conservative placeholder, same
        # reasoning as grok's. Revisit once real codex sessions accumulate
        # usage data to tune against.
        return SOFT_TOKENS, HARD_TOKENS

    def normalize_usage(self, raw_usage: Optional[dict]) -> Optional[dict]:
        if not raw_usage:
            return None
        input_tokens = int(raw_usage.get("input_tokens") or 0)
        cache_read = int(raw_usage.get("cached_input_tokens") or 0)
        cache_write = int(raw_usage.get("cache_write_input_tokens") or 0)
        output_tokens = int(raw_usage.get("output_tokens") or 0)
        thinking_tokens = int(raw_usage.get("reasoning_output_tokens") or 0)
        return {
            "input_tokens": input_tokens + cache_write,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "cache_read_tokens": cache_read,
            "total_tokens": input_tokens + cache_write + output_tokens,
        }

    def rate_limit_report(self) -> Optional[dict]:
        """Account-wide Codex quota via read-only app-server JSON-RPC."""
        try:
            rows = _codex_rate_limit_to_rows(_fetch_codex_rate_limits(self.find_executable()))
        except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as e:
            return {"error": str(e)[:400]}
        except Exception as e:
            return {"error": str(e)[:400]}
        if not rows:
            return {"error": "Codex 사용량 응답에서 제한 정보를 찾지 못했습니다"}
        return {"rows": rows}

    def mints_own_conversation_id(self) -> bool:
        # Verified live 2026-09-17: `codex exec resume <a fresh uuid codex
        # has never seen>` fails immediately -- "Error: thread/resume:
        # thread/resume failed: no rollout found for thread id ... (code
        # -32600)" -- same failure category as claude/grok. No --resume/
        # `resume <id>` on the first spawn; capture the real thread_id from
        # thread.started instead.
        return True


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
    PERSONA.md + skill index + memory snapshot + self-improve status), or
    None when there is nothing to inject. Used by AgySession._send_direct()
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


def openai_chunk_model(obj: Optional[dict]) -> str:
    """Wire `model` on one OpenAI-dialect SSE/JSON object. Empty if absent.

    OpenRouter `openrouter/free` (and similar routers) echo the *served*
    id here, which can differ from the requested router slug. Usage-only
    trailing chunks still carry it, so callers must read this before
    skipping empty `choices`.
    """
    if not isinstance(obj, dict):
        return ""
    m = obj.get("model")
    return m.strip() if isinstance(m, str) else ""


def stamp_served_model(
    session: Any,
    hist_item: dict,
    out: Optional[dict] = None,
    captured: Optional[str] = None,
) -> None:
    """Record the model that produced this turn on history + the result event.

    HTTP gateways may serve a different id than `session.model` (OpenRouter
    free router). The wire `model` field is SSOT when present; CLI adapters
    have no separate served id, so `session.model` is what ran. Does not
    rewrite `session.model` — the picker selection stays the requested id.
    """
    m = (captured or "").strip() or (getattr(session, "model", None) or "").strip()
    if not m:
        return
    hist_item["served_model"] = m
    if out is not None:
        out["served_model"] = m


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
        return ""  # not applicable -- transport_kind="http" means AgySession never calls this

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
        """Fetch and cache `/v1/models` metadata (context_length, etc.). Cached for 10 min."""
        now = time.time()
        if self._models_meta_cache["data"] and (now - self._models_meta_cache["ts"] < 600):
            return self._models_meta_cache["data"]
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
            pass
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

    # --- HTTP-transport-only surface (AgySession's http branch calls this,
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
    # this is just a thread blocked in a socket read). AgySession's watchdog
    # (_start_http_watchdog/_http_turn_watchdog) enforces this by calling
    # stop() once a turn runs past it.

    def _stream_once(self, session: "AgySession", messages: List[dict], tools: List[dict], seq: Optional[int] = None) -> Iterator[dict]:
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

    def stream_turn(self, session: "AgySession", messages: List[dict], seq: Optional[int] = None) -> Iterator[dict]:
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
        transport failure -- the caller (AgySession._run_http_turn) turns
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
            )
            yield out
            return
        yield {"event": "error", "text": f"툴 호출이 {self.MAX_TOOL_HOPS}회를 넘어 강제 종료했습니다냥."}


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


AGENT_ADAPTERS: Dict[str, AgentAdapter] = {
    "agy": AgyAdapter(),
    "claude": ClaudeAdapter(),
    "grok": GrokAdapter(),
    "codex": CodexAdapter(),
}
AGENT_ADAPTERS.update(load_openai_dialect_adapters(PROVIDERS_JSON))


def get_adapter(provider_id: str = DEFAULT_PROVIDER) -> AgentAdapter:
    return AGENT_ADAPTERS.get(provider_id, AGENT_ADAPTERS[DEFAULT_PROVIDER])
