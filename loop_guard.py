"""Repeat detector for an agent's tool calls.

Born from 2026-09-20: after "그래", the Gemini-backed agent spent ~23 minutes calling
`view_file` on the same source file 239 times (79 identical calls for one 15-line window,
then 186 in a row paging through the file 15 lines at a time), never converging. The UI
showed nothing because the stream only repeats a bare step type, and the turn "ended" with
an empty result at the 8-minute print timeout while the agent kept spinning in the
background, burning quota. The operator says Gemini falling into such loops during code
work is common, so this is on by default.

2026-09-21: "the same call" must mean "no new information", not "looks alike". Honest work was
flagged when the arguments the host saw were identical (reads of different ranges of one file)
while the tool outputs differed. So calls now carry a hash of their OUTPUT, and a repeat only
counts when the output did not change. A stop needs the outputs confirmed equal; when no
output is known (a stream shape without one) the call may still warn, and stops only at twice
the usual count.

Pure logic, no I/O. Feed one call per finished tool step; it answers when a pattern crosses
a threshold. Three rules (thresholds are per turn, `reset()` between turns):

  A  the same READ-ONLY call (same tool, same stable arguments, same output) repeated inside a
     sliding window of recent calls. Reading the same range again and again is never progress.
  B  the same call of ANY tool back to back. (Non-consecutive repeats are allowed for
     mutating tools: an edit -> run tests -> edit cycle legitimately reruns a command.)
  C  a long unbroken run of read-only calls on the SAME target file. Real work reads a big
     file in a handful of windows, then acts (edit, run, search) -- which resets this run.

Signatures ignore the model-written prose that rides along in the arguments
(`toolAction`, `toolSummary`, ...): it changes every call and would hide a real repeat.
Each (rule, level) fires once until `reset()`.
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Set, Tuple

# arguments that are commentary by the model, not part of what the call does
NOISE_KEYS = {"toolaction", "toolsummary", "waitforprevioustools", "explanation", "description",
              "thought", "reasoning", "rationale"}
# where a call says which file/dir/url it targets
TARGET_KEYS = ("AbsolutePath", "TargetFile", "FilePath", "filePath", "File", "file", "path", "Path",
               "SearchPath", "DirectoryPath", "Uri", "Url", "url")
READ_ONLY_PREFIXES = ("view", "read", "list", "find", "grep", "search", "glob", "cat", "get_", "stat")


@dataclass(frozen=True)
class Verdict:
    level: str      # "warn" | "stop"
    rule: str       # "exact" | "consecutive" | "run"
    count: int
    tool: str
    target: str
    text: str       # one short line, shown to the operator


def is_read_only(tool: str) -> bool:
    return (tool or "").lower().startswith(READ_ONLY_PREFIXES)


def normalize(params: Optional[dict]) -> Dict[str, object]:
    return {k: v for k, v in (params or {}).items() if str(k).lower() not in NOISE_KEYS}


def target_of(params: Optional[dict]) -> str:
    p = params or {}
    for k in TARGET_KEYS:
        v = p.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def signature(tool: str, params: Optional[dict]) -> Tuple[str, str]:
    try:
        body = json.dumps(normalize(params), sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        body = str(normalize(params))
    return (tool or "", body)


def output_hash(output) -> Optional[str]:
    """A short fingerprint of what a tool answered; None when the stream carried no output at all."""
    if output is None:
        return None
    try:
        text = output if isinstance(output, str) else json.dumps(output, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(output)
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:8]


def _compatible(a: Optional[str], b: Optional[str]) -> bool:
    """Two outputs may belong to the same repeat: equal, or at least one of them unknown."""
    return a is None or b is None or a == b


def _short(path: str, keep: int = 48) -> str:
    return path if len(path) <= keep else "…" + path[-(keep - 1):]


class LoopGuard:
    def __init__(self, exact_warn: int = 6, exact_stop: int = 10, window: int = 40,
                 consec_warn: int = 5, consec_stop: int = 8,
                 run_warn: int = 24, run_stop: int = 48) -> None:
        self.exact_warn, self.exact_stop, self.window = exact_warn, exact_stop, window
        self.consec_warn, self.consec_stop = consec_warn, consec_stop
        self.run_warn, self.run_stop = run_warn, run_stop
        self._stop_defaults = (exact_stop, consec_stop)
        self.reset()

    def tighten(self, stop_at: int = 3) -> None:
        """After the agent was told to change course, a repeat that continues stops sooner. Survives
        reset() (which the resumed turn calls); relax() puts the normal thresholds back."""
        self.exact_stop = min(self.exact_stop, stop_at)
        self.consec_stop = min(self.consec_stop, stop_at)

    def relax(self) -> None:
        self.exact_stop, self.consec_stop = self._stop_defaults

    def reset(self) -> None:
        self._recent: Deque[Optional[Tuple[Tuple[str, str], Optional[str]]]] = deque(maxlen=self.window)
        self._last_sig: Optional[Tuple[str, str]] = None
        self._last_out: Optional[str] = None
        self._consec = 0
        self._consec_confirmed = True
        self._run_target = ""
        self._run_len = 0
        self._fired: Set[Tuple[str, str]] = set()
        self.calls = 0

    def observe(self, tool: str, params: Optional[dict] = None, output=None) -> Optional[Verdict]:
        """Record one finished tool call; return a Verdict the first time a rule trips.
        `output` is what the tool answered (any shape); it decides whether a repeat made no progress."""
        self.calls += 1
        sig = signature(tool, params)
        out = output_hash(output)
        ro = is_read_only(tool)
        target = target_of(params)

        if sig == self._last_sig and _compatible(out, self._last_out):
            self._consec += 1
            self._consec_confirmed = self._consec_confirmed and out is not None and out == self._last_out
        else:
            self._consec, self._consec_confirmed = 1, True
        self._last_sig, self._last_out = sig, out

        self._recent.append((sig, out) if ro else None)
        exact = confirmed_exact = 0
        if ro:
            for e in self._recent:
                if e is not None and e[0] == sig and _compatible(e[1], out):
                    exact += 1
                    confirmed_exact += out is not None and e[1] == out

        if ro and target:
            self._run_len = self._run_len + 1 if target == self._run_target else 1
            self._run_target = target
        else:
            self._run_target, self._run_len = "", 0

        what = f"{tool} {_short(target)}".strip()
        note = f" · 출력 {out} 동일" if out else " · 출력 미확인"
        # a stop wants the outputs confirmed equal; without that it takes twice the count
        stop_exact = confirmed_exact >= self.exact_stop or exact >= 2 * self.exact_stop
        stop_consec = self._consec >= self.consec_stop and (self._consec_confirmed or self._consec >= 2 * self.consec_stop)
        candidates: List[Tuple[str, str, int, str]] = [
            ("stop", "exact", exact, f"같은 조회를 {exact}번 반복 ({what}{note})" if stop_exact else ""),
            ("stop", "consecutive", self._consec, f"같은 호출을 연달아 {self._consec}번 ({what}{note})" if stop_consec else ""),
            ("stop", "run", self._run_len, f"같은 파일을 {self._run_len}번 연속으로 조회 ({_short(target)})" if self._run_len >= self.run_stop else ""),
            ("warn", "exact", exact, f"같은 조회가 {exact}번 반복되고 있어요 ({what}{note})" if exact >= self.exact_warn else ""),
            ("warn", "consecutive", self._consec, f"같은 호출이 연달아 {self._consec}번이에요 ({what}{note})" if self._consec >= self.consec_warn else ""),
            ("warn", "run", self._run_len, f"같은 파일을 {self._run_len}번 연속 조회 중이에요 ({_short(target)})" if self._run_len >= self.run_warn else ""),
        ]
        for level, rule, count, text in candidates:
            if not text or (rule, level) in self._fired:
                continue
            self._fired.add((rule, level))
            return Verdict(level, rule, count, tool, target, text)
        return None


def extract_tool_steps(obj: dict) -> List[Tuple[str, dict, object]]:
    """Finished tool calls carried by one agy stream-json line, as (name, params, output).
    `output` is None when the line does not carry one.

    Real shape (agy 1.2.7, measured 2026-09-20): a `step_update` with step_type "tool";
    it is sent ACTIVE when the call starts and DONE when it finishes, with
    `tool_info: {name, parameters, output}`. Only DONE counts, so a call is seen once.
    Older/other shapes (`tool_calls` list, classic tool_use/tool_call) are accepted too.
    """
    out: List[Tuple[str, dict, object]] = []
    step = obj.get("step_update")
    if isinstance(step, dict):
        if str(step.get("step_type") or "") == "tool" and str(step.get("state") or "") == "DONE":
            info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
            name = str(info.get("name") or step.get("tool_name") or "").strip()
            params = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}
            if name:
                out.append((name, params, info.get("output")))
        return out
    calls = obj.get("tool_calls")
    if isinstance(calls, list):
        for tc in calls:
            if isinstance(tc, dict):
                name = str(tc.get("name") or "").strip()
                args = tc.get("args") or tc.get("input") or tc.get("parameters") or {}
                if name:
                    out.append((name, args if isinstance(args, dict) else {}, tc.get("output", tc.get("result"))))
        return out
    if (obj.get("event") or obj.get("type")) in ("tool_use", "tool_call"):
        name = str(obj.get("name") or obj.get("tool") or "").strip()
        args = obj.get("args") or obj.get("input") or obj.get("parameters") or {}
        if name:
            out.append((name, args if isinstance(args, dict) else {}, obj.get("output", obj.get("result"))))
    return out


def extract_tool_calls(obj: dict) -> List[Tuple[str, dict]]:
    """(name, params) of the finished tool calls in one line; see extract_tool_steps for the outputs."""
    return [(n, p) for n, p, _ in extract_tool_steps(obj)]
