"""What each delegated CLI call cost (docs/plans/token-economy.md T6).

The worker and the reviewer run as one-shot CLIs. Asked for their machine-readable output, each reports the tokens
of the call; this module adds that switch to the command line, takes the answer text and the usage back out of the
output, and appends one line per call to runs/usage.jsonl next to the ticket's state, so a ticket's delegated cost
can be set beside what the chat spent on it. Every CLI's shape was read from its real output on 2026-10-04.

When an output does not parse (a CLI changed its format, or printed an error) the raw output is returned as the
text and nothing is recorded: measuring must never change what the runner sees.
"""
from __future__ import annotations

import json
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


def _norm(u: dict, inp: str, cached: str, created: str = "") -> Dict[str, int]:
    """{input (all of it, cached included), cached, output} from one usage block."""
    fresh = int(u.get(inp) or 0) + (int(u.get(created) or 0) if created else 0)
    hit = int(u.get(cached) or 0)
    return {"input": fresh + hit, "cached": hit, "output": int(u.get("output_tokens") or 0)}


def split(provider: str, out: str) -> Tuple[str, Optional[Dict[str, int]]]:
    """(answer text, usage) from the CLI's output; (out, None) when it is not the shape expected."""
    try:
        if provider == "codex":
            text, usage = "", None
            for line in out.splitlines():
                ev = json.loads(line) if line.strip().startswith("{") else {}
                item = ev.get("item") or {}
                if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
                    text = str(item.get("text") or "")
                if ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
                    u = _norm(ev["usage"], "input_tokens", "cached_input_tokens")
                    u["input"] -= u["cached"]   # codex counts the cached part inside input_tokens
                    usage = {k: usage[k] + u[k] for k in u} if usage else u
            return (text, usage) if usage is not None else (out, None)
        d = json.loads(out)
        if provider == "agy":
            return str(d["response"]), _norm(d["usage"], "input_tokens", "cache_read_tokens")
        if provider in ("claude", "grok"):
            text = d["result"] if provider == "claude" else d["text"]
            return str(text), _norm(d["usage"], "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    except (ValueError, KeyError, TypeError, AttributeError):
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
