"""Codex CLI adapter and its rate-limit rows. Callers import from adapters (ADAPTER_SPLIT_v1)."""
from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import time

from pathlib import Path
from typing import List, Optional, Tuple

from host_config import AGENT_PATH_PREFIX, CODEX_BIN, HARD_TOKENS, SOFT_TOKENS, _now
from tool_format import _format_tool_call, _format_tool_result
from providers.adapter_base import AgentAdapter


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
    proc = subprocess.Popen(
        [executable, "app-server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1,
        start_new_session=True,  # CODEX_PROC_v1: killpg cleans node+native
    )
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
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass


class CodexAdapter(AgentAdapter):
    """Multi-Provider plan Phase 3. Originally scoped "design only, codex not
    installed" -- operator installed codex-cli 0.154.0 on this host mid-Phase-2,
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
    subagents = True
    subagent_hint = " (spawn_agent, then wait)"
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
        model = (model or "").strip()
        if not model or model == "default":
            model = "gpt-5.6-luna"  # CODEX_DEFAULT_LUNA_v1
        if model and model != "default":
            args.extend(["-m", model])
        if effort and effort != "default":
            args.extend(["-c", f'model_reasoning_effort="{effort}"'])
        # composer-plus-menu plus/E: codex reads a file path as text and cannot see the picture (checked live
        # 2026-09-28: "CANNOT SEE"), so an image attached to this turn goes as --image, which exec and exec resume
        # both take. "--image=<path>": the flag takes several values and would swallow the "-" below otherwise.
        import chat_upload
        for _mime, path in chat_upload.attached_image_paths(prompt):
            args.append("--image=%s" % path)
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

    def normalize_line(self, session: "AgentSession", raw_line: str) -> List[dict]:
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

    def known_models(self) -> List[str]:
        """CODEX_MODELS_v1 + CODEX_DEFAULT_LUNA_v1: luna first = UI/session default."""
        return [
            "gpt-5.6-luna",
            "gpt-5.6-terra",
            "gpt-5.6-sol",
            "gpt-5.6",
            "gpt-5.5",
            "gpt-5.3-codex-spark",
        ]

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
        # codex's input_tokens already holds the cached part (OpenAI usage: cached is a subset): measured 2026-10-04,
        # the same prompt twice gave input 20141 with cached 2816, then 0. The canonical input_tokens is the uncached
        # part, as every other adapter reports it, so cached tokens are not counted twice (token-economy.md T6).
        raw_input = int(raw_usage.get("input_tokens") or 0)
        cache_read = min(int(raw_usage.get("cached_input_tokens") or 0), raw_input)
        cache_write = int(raw_usage.get("cache_write_input_tokens") or 0)
        output_tokens = int(raw_usage.get("output_tokens") or 0)
        thinking_tokens = int(raw_usage.get("reasoning_output_tokens") or 0)
        fresh = raw_input - cache_read + cache_write
        return {
            "input_tokens": fresh,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "cache_read_tokens": cache_read,
            "total_tokens": fresh + output_tokens,
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
