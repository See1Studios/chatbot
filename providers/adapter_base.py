"""The adapter base every provider builds on: AgentAdapter (turn finalising, usage, served model) and the served-model helpers. Callers import from adapters (ADAPTER_SPLIT_v1)."""
from __future__ import annotations

import shutil
import signal
import subprocess

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

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


def split_choices(text: str) -> Tuple[str, List[str]]:
    """(text without a trailing choices marker, its items). Items are kept as written (e.g. "label -> action")."""
    m = _CHOICES_TAIL.search(text or "")
    if not m:
        return text, []
    items = [x.strip()[:CHOICE_LEN] for x in m.group(1).split("|") if x.strip()][:CHOICES_MAX]
    return (text[:m.start()].rstrip(), items) if items else (text, [])


# PRIVATE_TENSION_v1 (#162): private sessions climb a 4-stage tension ladder. The engine state lives on the session;
# this is the one place its per-turn context is written, so every provider gets the same text.
TENSION_MIN, TENSION_MAX = 1, 4
TENSION_STAGES = {1: "warm-up", 2: "flirting", 3: "rising", 4: "peak"}
TENSION_SLOTS = ("push-pull", "escalate", "peak")   # slot index -> stage delta 0 / +1 / +2
TENSION_RECENT_MAX = 9


def tension_after(stage: int, slot: int = -1, action: bool = False) -> int:
    """Next stage: a picked slot moves it by its index (push-pull holds), an action nudges +1; clamped to 1..4."""
    step = slot if 0 <= slot < len(TENSION_SLOTS) else (1 if action else 0)
    return max(TENSION_MIN, min(TENSION_MAX, int(stage or TENSION_MIN) + step))


def tension_context(stage: int, recent_choices: List[str]) -> str:
    """[Tension Engine Context] block for one private turn: stage, choices not to repeat, the 3-slot contract."""
    stage = max(TENSION_MIN, min(TENSION_MAX, int(stage or TENSION_MIN)))
    lines = [
        "[Tension Engine Context]",
        f"Stage: {stage}/{TENSION_MAX} ({TENSION_STAGES[stage]}). Match the scene's intensity to this stage.",
    ]
    recent = [c for c in (recent_choices or []) if c][-TENSION_RECENT_MAX:]
    if recent:
        lines.append("Do not repeat or rephrase these recent choices: " + " | ".join(recent))
    top = min(TENSION_MAX, stage + 2)
    lines.append(
        "End with exactly 3 choices in this slot order: "
        f"1) push-pull -- tease or hold back, stays at stage {stage}; "
        f"2) escalate -- one step closer, stage {min(TENSION_MAX, stage + 1)}; "
        f"3) peak -- the boldest move, stage {top}."
    )
    return "\n".join(lines)


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
        if not getattr(session, "is_private", False):
            return ""
        return tension_context(getattr(session, "tension_stage", TENSION_MIN), getattr(session, "recent_choices", []))

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
        # QUOTA_SILENT_FIX_v1:
        # agy often returns streamed text AND result.error (e.g. RESOURCE_EXHAUSTED
        # after retries). Persisting both as answer + notice:error with the same
        # ts made every successful turn look like "답 + 쿼터 에러 공지". Error-only
        # turns emitted result with empty text so the UI stayed silent.
        body, choices = split_choices((final or "").strip())
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

        hist_item: dict = {"role": "assistant", "text": hist_text, "ts": ts}
        if choices and not emit_as_error:
            hist_item["choices"] = choices
        if emit_as_error:
            hist_item["notice"] = "error"
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
            out_ev["notice"] = "error"
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
