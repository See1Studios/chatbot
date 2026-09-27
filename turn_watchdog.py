"""Turn watchdogs for AgentSession (moved out of session.py, pew/N1d; behaviour unchanged).

QUOTA_FAILFAST_v1 closes a turn that stalls after a provider `error_message`; SILENT_HANG_v1 closes a busy turn
with no assistant text and no tool/progress activity. Both run on threading.Timer and finish the turn through the
session's own adapter.finalize_turn / _finish_turn / _end_unfinished_turn. AgentSession inherits TurnWatchdog, so
callers and tests keep using session methods and the class attributes ERROR_MESSAGE_FAILFAST_SEC / SILENT_HANG_SEC.
"""
from __future__ import annotations

import threading
from typing import Optional

import obslog
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
        err = (getattr(self, "_err_msg_hint", None) or "").strip()
        if not err:
            err = "쿼터 또는 제공자 오류로 보입니다. 응답이 없어 턴을 닫았습니다."
        elif "quota" not in err.lower() and "소진" not in err:
            err = "쿼터 또는 제공자 오류로 보입니다. " + err
        try:
            out = self.adapter.finalize_turn(
                self, text="", raw_usage=None, is_err=True, error=err
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
    SILENT_HANG_SEC = 90

    def _cancel_silent_hang(self) -> None:
        timer = getattr(self, "_silent_hang_timer", None)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
            self._silent_hang_timer = None

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

    def _touch_turn_activity(self) -> None:
        """Text delta OR tool/progress proves the turn is alive — reset the idle clock."""
        now = _now()
        self._last_turn_activity_at = now
        # Keep legacy stamp so older callers/tests reading delta-at still see activity.
        self._last_assistant_delta_at = now
        # Activity proves the agent is actively responding; cancel any pending failfast timer.
        self._cancel_error_message_failfast()
        if self.busy and not getattr(self, "_silent_hang_done", False):
            self._arm_silent_hang()

    def _touch_assistant_delta(self) -> None:
        """Back-compat alias — assistant deltas are one form of turn activity."""
        self._touch_turn_activity()

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
            self._silent_hang_done = True
        dur = 0.0
        if getattr(self, "turn_started_at", 0):
            dur = max(0.0, _now() - float(self.turn_started_at))
        idle = float(self.SILENT_HANG_SEC)
        last = (
            getattr(self, "_last_turn_activity_at", 0)
            or getattr(self, "_last_assistant_delta_at", 0)
            or 0
        )
        if last:
            idle = max(idle, _now() - float(last))
        err = (
            f"응답이 오랫동안 없어 턴을 닫았습니다(무응답 {int(idle)}초). "
            "남은 작업은 멈췄어요 — 메시지를 보내면 이어서 합니다."
        )
        try:
            out = self.adapter.finalize_turn(
                self, text="", raw_usage=None, is_err=True, error=err
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
