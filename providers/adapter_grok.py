"""Grok CLI adapter, its billing rows and where grok keeps media. Callers import from adapters (ADAPTER_SPLIT_v1)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid

from pathlib import Path
from typing import List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote as _quote
from urllib.request import Request, urlopen

from host_config import AGENT_PATH_PREFIX, GROK_BIN, HARD_TOKENS, HOME, SOFT_TOKENS, WORKSPACE
from tool_format import _format_tool_call, _format_tool_result
from providers.adapter_base import AgentAdapter
import media_handler as _media


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


_GROK_MODELS_CACHE = {"ts": 0.0, "models": []}


class GrokAdapter(AgentAdapter):
    """Multi-Provider plan Phase 2. One-shot exec, not persistent stdin
    (keeps_stdin_open=False) -- every turn is its own `grok` process that
    exits when done; AgentSession._send_direct()/_spawn() branch on this.

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

    def normalize_line(self, session: "AgentSession", raw_line: str) -> List[dict]:
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
        now = time.time()
        if _GROK_MODELS_CACHE.get("models") and (now - float(_GROK_MODELS_CACHE.get("ts", 0.0)) < 300):
            return _GROK_MODELS_CACHE["models"]
        try:
            res = subprocess.run(
                [self.find_executable(), "models"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            if res.returncode == 0 or not isinstance(res.returncode, int):
                default_models: List[str] = []
                other_models: List[str] = []
                for line in (res.stdout or "").splitlines():
                    s = line.strip()
                    if s.startswith("*"):
                        cleaned = re.sub(r"\(.*?\)", "", s[1:]).strip()
                        parts = cleaned.split()
                        m = parts[0].strip(" ()") if parts else ""
                        if m.lower() == "default" and len(parts) > 1:
                            m = parts[1].strip(" ()")
                        if m and m not in default_models:
                            default_models.append(m)
                    elif s.startswith("-"):
                        cleaned = re.sub(r"\(.*?\)", "", s[1:]).strip()
                        parts = cleaned.split()
                        m = parts[0].strip(" ()") if parts else ""
                        if m.lower() == "default" and len(parts) > 1:
                            m = parts[1].strip(" ()")
                        if m and m not in other_models:
                            other_models.append(m)
                models: List[str] = []
                for m in default_models:
                    if m not in models:
                        models.append(m)
                for m in other_models:
                    if m not in models:
                        models.append(m)
                if models:
                    _GROK_MODELS_CACHE["ts"] = time.time()
                    _GROK_MODELS_CACHE["models"] = models
                    return models
        except Exception:  # noqa: BLE001
            pass
        return ["grok-4.7", "grok-4.6", "grok-4.5"]

    def mints_own_conversation_id(self) -> bool:
        # Verified live 2026-09-17: `--resume <a fresh uuid grok has never
        # seen>` doesn't start a fresh session either -- it fails harder than
        # claude's, exiting non-zero before emitting any NDJSON at all
        # ("Error: Failed to restore session from remote: ... 404 Not
        # Found"). Same handling as claude: no --resume on the first spawn,
        # capture the real sessionId from the first turn's `end` event.
        return True


class GrokMediaSource(_media.MediaSource):
    """Grok Imagine writes to ~/.grok/sessions/<urlencoded cwd>/<cid>/images/."""

    @staticmethod
    def _newest_with_images(parent):
        newest, newest_mtime = None, -1.0
        try:
            for d in parent.iterdir():
                img = d / "images"
                try:
                    if d.is_dir() and img.is_dir() and img.stat().st_mtime > newest_mtime:
                        newest_mtime, newest = img.stat().st_mtime, d
                except OSError:
                    continue
        except OSError:
            pass
        return newest

    def _dir(self, conversation_id):
        """conversation_id is often still empty on the first grok turn (the CLI reports sessionId only
        on its `end` event); then, or when it matches no folder, use the newest session under this
        workspace that has an images/ folder."""
        root = _media._cfg("HOME") / ".grok" / "sessions"
        if not root.is_dir():
            return None
        ws_enc = root / _quote(str(_media._cfg("WORKSPACE")), safe="")
        cid = str(conversation_id or "").strip()
        if cid:
            if (ws_enc / cid).is_dir():
                return ws_enc / cid
            try:
                for enc in root.iterdir():
                    if (enc / cid).is_dir():
                        return enc / cid
            except OSError:
                pass
        return self._newest_with_images(ws_enc) if ws_enc.is_dir() else None

    def scan_dirs(self, conversation_id, cutoff):
        d = self._dir(conversation_id)
        return [d / "images", d / "videos", d] if d else []

    def rel_bases(self, conversation_id):
        d = self._dir(conversation_id)
        return [d] if d else []
