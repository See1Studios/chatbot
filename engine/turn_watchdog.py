"""Turn watchdogs for AgentSession (moved out of session.py, pew/N1d; behaviour unchanged).

QUOTA_FAILFAST_v1 closes a turn that stalls after a provider `error_message`; SILENT_HANG_v1 closes a busy turn
with no assistant text and no tool/progress activity. Both run on threading.Timer and finish the turn through the
session's own adapter.finalize_turn / _finish_turn / _end_unfinished_turn. AgentSession inherits TurnWatchdog, so
callers and tests keep using session methods and the class attributes ERROR_MESSAGE_FAILFAST_SEC / SILENT_HANG_SEC.
"""
from __future__ import annotations

import threading
from typing import Optional

import i18n
from telemetry import obslog
from host_config import _now


class TurnWatchdog:
    # QUOTA_FAILFAST_v1: agy emits step_type=error_message then idles ~2min before result.
    ERROR_MESSAGE_FAILFAST_SEC = 8

    def _cancel_error_message_failfast(self) -> None:
        timer = getattr(self, "_err_msg_failfast_timer", None)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
            self._err_msg_failfast_timer = None
        self._err_msg_failfast_done = False
        self._err_msg_hint = ""

    def _arm_error_message_failfast(self) -> None:
        self._err_msg_failfast_done = False
        if (self.current_text or "").strip():
            return
        # SILENT_HANG_v1: error_message path is owned by QUOTA_FAILFAST
        self._cancel_silent_hang()
        if getattr(self, "_err_msg_failfast_timer", None) is not None:
            return
        timer = threading.Timer(float(self.ERROR_MESSAGE_FAILFAST_SEC), self._error_message_failfast)
        timer.daemon = True
        self._err_msg_failfast_timer = timer
        timer.start()

    def _error_message_failfast(self) -> None:
        """Close a turn that stalled after agy error_message instead of waiting for print-timeout."""
        self._err_msg_failfast_timer = None
        with self.lock:
            if not self.busy or self._stop_requested:
                return
            if getattr(self, "_err_msg_failfast_done", False):
                return
            if (self.current_text or "").strip() or (_now() - float(getattr(self, "_last_turn_activity_at", 0) or 0) < 5.0):
                return
            self._err_msg_failfast_done = True
        dur = 0.0
        if getattr(self, "turn_started_at", 0):
            dur = max(0.0, _now() - float(self.turn_started_at))
        hint = (getattr(self, "_err_msg_hint", None) or "").strip()   # the provider's own error line, as it came
        if "quota" in hint.lower():   # it says so itself: finalize_turn names it a quota notice
            err_msg, err = None, hint
        else:
            err_msg = i18n.msg("srv.quota_or_provider", error=hint) if hint else i18n.msg("srv.quota_or_provider_closed")
            err = err_msg["text"]
        try:
            out = self.adapter.finalize_turn(
                self, text="", raw_usage=None, is_err=True, error=err, error_msg=err_msg
            )
            self._emit(out)
            with self.lock:
                self.busy = False
            try:
                self._finish_turn("error")
            except Exception:
                pass
            already = out.get("event") == "error"
            self._end_unfinished_turn("ERROR", err, dur, emit_error=not already)
        except TypeError:
            # older signature without emit_error
            self._end_unfinished_turn("ERROR", err, dur)
        except Exception as e:
            obslog.exception("turn.failfast_failed", e, sid=self.sid)
            try:
                self._end_unfinished_turn("ERROR", err, dur, emit_error=True)
            except Exception:
                pass


    # SILENT_HANG_v1: busy turn with no assistant text AND no tool/progress activity
    # (and no error_message path) sits idle until agy print-timeout (8m). Close earlier
    # with a clear hang notice. Intent: catch true Gemini/provider stalls — not busy
    # multi-tool turns.
    # Default 90s: inside the approved 60–120s band; longer than QUOTA_FAILFAST (8s),
    # far shorter than AGY_PRINT_TIMEOUT_SEC (480s). Assistant deltas AND tool
    # start/result/progress heartbeats re-arm the timer (a single long tool is OK
    # while progress continues). error_message hands off to QUOTA_FAILFAST;
    # result/error/stopped cancel.
    # SILENT_NOTICE_v1 (#386): 90s closed 7.4% of gemini-3.8-flash-high turns (2026-09-26..29). agy prints nothing
    # while a thinking step runs -- only the step's DONE line afterwards -- so a long think looked like a stall. At
    # SILENT_NOTICE_SEC the page is told the turn is quiet (a `progress` event: it does not re-arm anything); the turn
    # is closed only at SILENT_HANG_SEC, still well inside AGY_PRINT_TIMEOUT_SEC (480s).
    # #513: 300s held the page locked for 5 minutes on a real runtime hang; 180s still doubles the notice window.
    SILENT_NOTICE_SEC = 90
    SILENT_HANG_SEC = 180

    @property
    def is_silent(self) -> bool:
        """A busy turn with no activity for SILENT_NOTICE_SEC (since the later of its start and its last activity)."""
        if not getattr(self, "busy", False):
            return False
        last = max(float(getattr(self, "_last_turn_activity_at", 0) or 0), float(getattr(self, "turn_started_at", 0) or 0))
        return bool(last) and _now() - last >= float(self.SILENT_NOTICE_SEC)

    def _cancel_silent_hang(self) -> None:
        for attr in ("_silent_hang_timer", "_silent_notice_timer"):
            timer = getattr(self, attr, None)
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _arm_silent_hang(self, delay: Optional[float] = None) -> None:
        self._cancel_silent_hang()
        if getattr(self, "_silent_hang_done", False):
            return
        sec = float(self.SILENT_HANG_SEC if delay is None else delay)
        if sec <= 0:
            return
        timer = threading.Timer(sec, self._silent_hang_fire)
        timer.daemon = True
        self._silent_hang_timer = timer
        timer.start()
        notice = float(self.SILENT_NOTICE_SEC)
        if 0 < notice < sec:
            nt = threading.Timer(notice, self._silent_notice_fire)
            nt.daemon = True
            self._silent_notice_timer = nt
            nt.start()

    def _silent_notice_fire(self) -> None:
        """SILENT_NOTICE_v1: tell the page the turn has been quiet for a while; the turn goes on."""
        self._silent_notice_timer = None
        with self.lock:
            if not self.busy or self._stop_requested or getattr(self, "_silent_hang_done", False):
                return
            if getattr(self, "_err_msg_failfast_timer", None) is not None:
                return
        if self._provider_shows_activity():   # SUBAGENT_ACTIVITY_v1: subagents at work, not a quiet turn
            return
        quiet = int(self.SILENT_NOTICE_SEC)
        m = i18n.msg("srv.quiet_progress", s=quiet)
        self.last_progress, self.last_progress_key, self.last_progress_vars = m["text"], m["key"], m["vars"]
        self._emit({"event": "progress", **m, "quiet_sec": quiet})
        try:
            obslog.event("turn.silent_notice", lvl="info", sid=self.sid, provider=self.provider, quiet_sec=quiet)
        except Exception:
            pass

    def _touch_turn_activity(self) -> None:
        """Text delta OR tool/progress proves the turn is alive — reset the idle clock."""
        now = _now()
        self._last_turn_activity_at = now
        # Activity proves the agent is actively responding; cancel any pending failfast timer.
        self._cancel_error_message_failfast()
        if self.busy and not getattr(self, "_silent_hang_done", False):
            self._arm_silent_hang()

    def _provider_shows_activity(self) -> bool:
        """A long think prints nothing on the stream, but the CLI's own log may show model calls. An adapter with a
        `last_activity` probe that saw one inside the window re-arms the clock for the rest of it instead."""
        probe = getattr(self.adapter, "last_activity", None)
        pid = getattr(getattr(self, "proc", None), "pid", None)
        if not callable(probe) or not pid:
            return False
        try:
            seen = float(probe(int(pid), float(getattr(self, "created_at", 0) or 0),
                               conversation_id=str(getattr(self, "conversation_id", "") or "")) or 0)
        except Exception:
            return False
        # A log line from an earlier turn must not extend this one (#513).
        if seen <= float(getattr(self, "_last_turn_activity_at", 0) or 0) or seen < float(getattr(self, "turn_started_at", 0) or 0):
            return False
        left = float(self.SILENT_HANG_SEC) - (_now() - seen)
        if left <= 0:
            return False
        self._last_turn_activity_at = seen
        self._arm_silent_hang(left)
        return True

    def _silent_hang_fire(self) -> None:
        """Close a busy turn with no text and no tool/progress for SILENT_HANG_SEC."""
        self._silent_hang_timer = None
        with self.lock:
            if not self.busy or self._stop_requested:
                return
            if getattr(self, "_silent_hang_done", False):
                return
            # QUOTA_FAILFAST_v1 owns stalls after error_message — do not double-close.
            if getattr(self, "_err_msg_failfast_timer", None) is not None:
                return
            if getattr(self, "_err_msg_failfast_done", False):
                return
        if self._provider_shows_activity():
            return
        with self.lock:
            if not self.busy or getattr(self, "_silent_hang_done", False):
                return
            self._silent_hang_done = True
        dur = 0.0
        if getattr(self, "turn_started_at", 0):
            dur = max(0.0, _now() - float(self.turn_started_at))
        idle = float(self.SILENT_HANG_SEC)
        last = getattr(self, "_last_turn_activity_at", 0) or 0
        if last:
            idle = max(idle, _now() - float(last))
        err_msg = i18n.msg("srv.hang_closed", s=int(idle))
        err = err_msg["text"]
        try:
            out = self.adapter.finalize_turn(
                self, text="", raw_usage=None, is_err=True, error=err, error_msg=err_msg
            )
            self._emit(out)
            with self.lock:
                self.busy = False
            try:
                self._finish_turn("error")
            except Exception:
                pass
            already = out.get("event") == "error"
            # TURN_END_ORDER_v1: terminal event already flushed; stop child after.
            self._end_unfinished_turn("HANG", err, dur, emit_error=not already)
            try:
                obslog.event(
                    "turn.silent_hang",
                    lvl="warn",
                    sid=self.sid,
                    provider=self.provider,
                    idle_sec=int(idle),
                    duration_sec=int(dur),
                )
            except Exception:
                pass
        except TypeError:
            self._end_unfinished_turn("HANG", err, dur)
        except Exception as e:
            obslog.exception("turn.silent_hang_failed", e, sid=self.sid)
            try:
                self._end_unfinished_turn("HANG", err, dur, emit_error=True)
            except Exception:
                pass
