"""The adapter base every provider builds on: AgentAdapter (turn finalising, usage, served model) and the served-model helpers. Callers import from adapters (ADAPTER_SPLIT_v1)."""
from __future__ import annotations

import shutil
import signal
import subprocess

from pathlib import Path
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import content_guard
from host_config import HARD_TOKENS, SOFT_TOKENS, _now


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


# OUT_OF_BAND_CHOICES_v1 (docs/plans/out-of-band-choices-actions.md 1a): the choices an answer ends with
# (`<!--choices: A | B-->`) leave the text here, once, for every provider. History, the CLI and the agent's own
# context keep the clean text; the page gets `choices` beside it. Only the last marker counts (a quoted one stays).
_CHOICES_TAIL = re.compile(r"\s*<!--\s*choices\s*:((?:(?!<!--)[\s\S])*?)-->\s*$")
CHOICES_MAX, CHOICE_LEN = 4, 120


# CHOICES_MIDLINE_v1 (2026-09-30): a turn can write its marker, call a tool, then write more -- the marker then
# sits mid-answer and was shown raw. A marker standing on its own line outside code fences is taken out wherever it
# is; the last one (a trailing one first) gives the choices. A marker quoted inside a sentence or a fence stays.
_CHOICES_LINE = re.compile(r"^[ \t]*<!--\s*choices\s*:((?:(?!<!--)[^\n])*?)-->[ \t]*$", re.M)
_FENCE = re.compile(r"```[\s\S]*?(?:```|$)")


def _items(raw: str) -> List[str]:
    return [x.strip()[:CHOICE_LEN] for x in raw.split("|") if x.strip()][:CHOICES_MAX]


def split_choices(text: str) -> Tuple[str, List[str]]:
    """(text without its choices markers, the items of the last one). Items are kept as written ("label -> action")."""
    text = text or ""
    fences = [f.span() for f in _FENCE.finditer(text)]
    lines = [m for m in _CHOICES_LINE.finditer(text) if not any(a <= m.start() < b for a, b in fences)]
    tail = _CHOICES_TAIL.search(text)
    items = _items(tail.group(1)) if tail else []
    if not items and lines:
        items = _items(lines[-1].group(1))
    if not items:
        return text, []
    body = text[:tail.start()] if tail and _items(tail.group(1)) else text
    for m in reversed([m for m in lines if m.end() <= len(body)]):
        end = m.end() + 1 if body[m.end():m.end() + 1] == "\n" else m.end()   # the marker's line goes with it
        body = body[:m.start()] + body[end:]
    return re.sub(r"\n{3,}", "\n\n", body).strip(), items


# CHOICES_LEAK_RESCUE_v1 (2026-09-28): a model sometimes writes its `choices` tool call into the answer as
# text instead of calling the tool -- `</tool_call>\n{"name": "choices", "arguments": {...}}\n</tool_call>`
# (gemini-3.8-flash-high, 2 of 14 private turns). The reader then saw JSON and no buttons. The call is taken
# out of the text here, for every provider, and becomes the turn's choices in the same "label -> action"
# form a marker gives. Commands are not rescued: text must not get past the command allowlist.
_LEAK_OUTER = re.compile(r'"name"\s*:\s*"choices"')
_LEAK_INNER = re.compile(r'"action"\s*:\s*"choices"')
_TOOL_TAG_TAIL = re.compile(r"\s*</?tool_call>\s*$")
_TOOL_TAG_HEAD = re.compile(r"^\s*</?tool_call>")


def _leaked_call(text: str):
    """(start, end, obj) of the last JSON object in `text` that is a choices call, or None."""
    for pattern in (_LEAK_OUTER, _LEAK_INNER):
        for m in reversed(list(pattern.finditer(text))):
            start = text.rfind("{", 0, m.start())
            if start < 0:
                continue
            try:
                obj, end = json.JSONDecoder().raw_decode(text, start)
            except ValueError:
                continue
            if text.count("```", 0, start) % 2:
                continue                                # inside a code block: an example, not a leak
            if isinstance(obj, dict) and end > m.start():
                return start, end, obj
    return None


def _leaked_items(obj: dict) -> List[str]:
    args = obj.get("arguments", obj) if obj.get("name") == "choices" else obj
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return []
    items = args.get("items") if isinstance(args, dict) else None
    if not isinstance(items, list) or not 2 <= len(items) <= CHOICES_MAX:
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            return []
        label = str(it.get("label") or "").strip()[:CHOICE_LEN]
        kind = str(it.get("kind") or "").strip()
        payload = str(it.get("payload") or label).strip()
        if kind == "command" and payload.lstrip("/").lower() in ("act", "action"):
            kind, payload = "action", label           # the model meant "do this", not a command
        if not label or kind not in ("say", "action"):
            return []
        if kind == "action":
            if not payload.startswith('"'):
                payload = "(%s)" % payload.strip("() ")
            out.append("%s -> %s" % (label, payload))
        else:
            out.append(label if payload == label else '%s -> "%s"' % (label, payload.strip('"')))
    return out


def rescue_leaked_choices(text: str) -> Tuple[str, List[str]]:
    """(text without a leaked choices call, the choices it carried). Unchanged when there is none. A leaked call
    whose items do not validate is still taken out of the text -- JSON is never an answer -- with no choices."""
    found = _leaked_call(text or "")
    if not found:
        return text, []
    start, end, obj = found
    left = _TOOL_TAG_TAIL.sub("", text[:start].rstrip())
    right = _TOOL_TAG_HEAD.sub("", text[end:].lstrip()).strip()
    body = left.rstrip() + ("\n\n" + right if right else "")
    return body.strip(), _leaked_items(obj)


class AgentAdapter:
    """Base interface for spawning/talking to a CLI agent backend.

    Mirrors VibeCat's IAgentAdapter (Source/VibeCat/Private/AgentAdapters.cpp:
    Id/FindExecutable/BuildArgs/FormatStdin/PrepareMcpConfig/NormalizeLine, one
    concrete subclass per provider, picked via a factory) so the same seams
    exist here if another provider is ever wired in.

    2026-09-17: `normalize_line` now exists (Multi-Provider plan Phase 0) --
    `AgyAdapter.normalize_line` takes the owning `AgentSession` as a parameter
    rather than being a pure per-line function, because agy's own tool/image
    handling (`AgentSession._tool_summary`/`_maybe_capture_conversation_id`)
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
    # docs/plans/api-provider-adapters.md) -- AgentSession branches on this before
    # touching self.proc/_spawn()/stdin. Every CLI adapter stays "process" by
    # inheriting this default; only an HTTP-dialect adapter overrides it.

    def turn_context(self, session: Any) -> str:
        """Per-turn system context prepended to the user message; private sessions get the tension engine block."""
        import private_engine
        return private_engine.turn_context(session)

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

    def normalize_line(self, session: "AgentSession", raw_line: str) -> List[dict]:
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

    # PROVIDER_NEUTRAL_v1: provider features the common code asks for by capability, never by
    # provider name. The base answers "not supported" and the caller falls back on its own.
    def oneshot(self, prompt: str, timeout: float = 20.0) -> Optional[Dict[str, Any]]:
        """One prompt, one answer, no conversation (side questions, handoff summaries), on this
        provider's cheapest model. None = not supported here; otherwise {"text", "usage",
        "duration_seconds", "error"} with text "" when the call failed."""
        return None

    def native_compact(self, conversation_id: Optional[str], timeout: float = 45.0) -> str:
        """This provider's own summary of conversation `conversation_id`, or "" (not supported,
        no conversation, or it failed)."""
        return ""

    # A message that arrives mid-turn can be applied at the next tool-step boundary (steer).
    supports_steer = False

    def has_conversation(self, conversation_id: Optional[str]) -> Optional[bool]:
        """Whether the CLI's own store still holds that conversation (a respawn would resume it).
        None = cannot tell; the session then keeps the id as is."""
        return None

    def last_activity(self, pid: int, started: float) -> Optional[float]:
        """When the one-shot worker process `pid` (started at `started`) last showed it was working -- e.g. a model
        call in the CLI's own log. None = this provider gives no such signal; its runs are then held only to their
        overall timeout, never judged stalled (delegation_watch, WORKER_STALL_v1)."""
        return None

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
        finish_reason: Optional[str] = None,
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
        # QUOTA_SILENT_FIX_v1:
        # agy often returns streamed text AND result.error (e.g. RESOURCE_EXHAUSTED
        # after retries). Persisting both as answer + notice:error with the same
        # ts made every successful turn look like "답 + 쿼터 에러 공지". Error-only
        # turns emitted result with empty text so the UI stayed silent.
        body, choices = split_choices((final or "").strip())
        if not choices:
            body, choices = rescue_leaked_choices(body)   # CHOICES_LEAK_RESCUE_v1
        err_s = (error or "").strip() if is_err else ""
        if body:
            hist_text = body
            emit_as_error = False
        elif err_s:
            # QUOTA_ERR_DEDUP_v1: one Korean-facing notice body
            low = err_s.lower()
            if "quota" in low or "resource_exhausted" in low or "rate limit" in low:
                hist_text = "쿼터가 소진됐습니다. " + err_s
            else:
                hist_text = err_s
            emit_as_error = True
        else:
            hist_text = ""
            emit_as_error = False
        # CONTENT_GUARD_v1: a provider refusal is a warn system notice, not an assistant bubble
        refused, guard_text = content_guard.intercept_refusal(
            getattr(session, "provider", "") or self.id, body or err_s, finish_reason)
        notice_kind = "warn" if refused else ("error" if emit_as_error else "")
        if refused:
            hist_text, choices, emit_as_error = guard_text, [], True

        hist_item: dict = {"role": "assistant", "text": hist_text, "ts": ts}
        if choices and not emit_as_error:
            hist_item["choices"] = choices
        if emit_as_error:
            hist_item["notice"] = notice_kind
            if error:
                hist_item["error"] = error
        elif is_err and error:
            # Residual provider error while we still have an answer — keep on
            # the hist item for debugging but do not mark as notice.
            hist_item["error"] = error
        if usage:
            hist_item["usage"] = usage
        if duration_seconds is not None:
            hist_item["duration_seconds"] = duration_seconds
        stamp_served_model(session, hist_item, captured=served_model)

        if hist_text:
            session.history.append(hist_item)
            session.save_meta()

        session.current_text = ""
        session.pending_images = []

        out_ev = {
            "event": "error" if emit_as_error else "result",
            "text": hist_text,
            "raw_event": "error" if emit_as_error else "result",
            "ts": ts,
        }
        if emit_as_error:
            out_ev["notice"] = notice_kind
        if hist_item.get("choices"):
            out_ev["choices"] = hist_item["choices"]
        if usage:
            out_ev["usage"] = usage
        if duration_seconds is not None:
            out_ev["duration_seconds"] = duration_seconds
        if is_err and error:
            out_ev["error"] = error
        stamp_served_model(session, hist_item, out_ev, captured=served_model)
        return out_ev


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
