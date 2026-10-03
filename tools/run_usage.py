"""What each delegated CLI call cost (docs/plans/token-economy.md T6).

The worker and the reviewer run as one-shot CLIs. Asked for their machine-readable output, each reports the tokens
of the call; this module adds that switch to the command line, takes the answer text and the raw usage back out of
the output, and appends one line per call to runs/usage.jsonl next to the ticket's state, so a ticket's delegated cost
can be set beside what the chat spent on it. Every CLI's shape was read from its real output on 2026-10-04.

The usage is put in shape by the provider's own adapter (`normalize_usage`), the same code the chat's history goes
through, so both sides count alike: input_tokens is the uncached input, cache_read_tokens the cached part.
Calibrated 2026-10-04: one CLI gives the same numbers in its chat (stream) and its one-shot (json) output.

When an output does not parse (a CLI changed its format, or printed an error) the raw output is returned as the
text and nothing is recorded: measuring must never change what the runner sees.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# flags that switch each CLI to one machine-readable answer, and where they go on its command line
OUTPUT_FLAGS: Dict[str, List[str]] = {
    "agy": ["--output-format", "json"],      # before -p: agy reads the word after -p as the prompt
    "claude": ["--output-format", "json"],
    "grok": ["--output-format", "json"],
    "codex": ["--json"],                     # JSONL events; after `exec`
}
ROOT = Path(__file__).resolve().parent.parent
CONTEXT: Dict[str, object] = {}              # the runner sets {"ticket": n} for the run in progress


def machine(provider: str, cmd: List[str]) -> List[str]:
    """`cmd` with the provider's output switch; unchanged for a provider without one."""
    flags = OUTPUT_FLAGS.get(provider)
    if not flags or any(f in cmd for f in flags[:1]):
        return list(cmd)
    cmd = list(cmd)
    if "-p" in cmd:
        at = cmd.index("-p")
    elif "exec" in cmd:
        at = cmd.index("exec") + 1
    else:
        return cmd
    return cmd[:at] + flags + cmd[at:]


TEXT_KEY = {"agy": "response", "claude": "result", "grok": "text"}   # where the answer is in one JSON object
FIELDS = ("input_tokens", "cache_read_tokens", "output_tokens", "thinking_tokens")


def _raw(provider: str, out: str) -> Tuple[str, Optional[dict]]:
    """(answer text, the CLI's own usage dict) or (out, None)."""
    if provider == "codex":   # JSONL events: the last agent message, the turn's usage
        text, usage = None, None
        for line in out.splitlines():
            ev = json.loads(line) if line.strip().startswith("{") else {}
            item = ev.get("item") or {}
            if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
                text = str(item.get("text") or "")
            if ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
                usage = ev["usage"]
        return (text, usage) if text is not None and usage else (out, None)
    d = json.loads(out)
    return str(d[TEXT_KEY[provider]]), d["usage"]


def _normalize(provider: str, raw: dict) -> Optional[Dict[str, int]]:
    """The adapter's canonical usage (the chat's definition), trimmed to the fields recorded."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from providers.adapters import AGENT_ADAPTERS
    u = AGENT_ADAPTERS[provider].normalize_usage(raw)
    return {k: int(u.get(k) or 0) for k in FIELDS} if u else None


def split(provider: str, out: str) -> Tuple[str, Optional[Dict[str, int]]]:
    """(answer text, usage) from the CLI's output; (out, None) when it is not the shape expected."""
    try:
        text, raw = _raw(provider, out)
        if raw is not None:
            usage = _normalize(provider, raw)
            if usage is not None:
                return text, usage
    except (ValueError, KeyError, TypeError, AttributeError, ImportError):
        pass
    return out, None


def record(base: Path, provider: str, cwd: Optional[Path], usage: Dict[str, int], seconds: float) -> None:
    """One line in <base>/runs/usage.jsonl. Never raises."""
    try:
        role = "reviewer" if cwd is not None and Path(cwd).name == "review-room" else "writer"
        line = {"ts": round(time.time(), 1), "ticket": CONTEXT.get("ticket"), "role": role, "provider": provider,
                "seconds": round(seconds, 1), **usage}
        path = Path(base) / "runs" / "usage.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(path), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:  # noqa: BLE001 -- measuring must never fail a run
        pass
