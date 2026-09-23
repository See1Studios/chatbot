#!/usr/bin/env python3
"""Process facts for chatbot-ctl.sh (WATCHDOG_OS_FACTS_v1).

The watchdog decides from what it owns -- the OS process table, /proc, and the pid file ctl wrote
when it spawned the chat server -- never from what the service reports about itself (session
meta.json, live_pids.json, standby.pid, the HTTP API). docs/plans/recursive-self-evolution.md §7-7.

Standard library only; imports nothing from the service.

Rules
  ours   : an agent-shaped process (agy/claude stream-json, grok --prompt-file, codex --json/login)
           whose cwd is the service workspace (every spawn in the service uses it). Anything else --
           a person's terminal agy, another tool's agent, another instance -- is never touched.
  owned  : ours and a descendant of the live chat server -> the server's business, left alone.
  orphan : ours and not a descendant of the live chat server -> reaped (SIGTERM).
  busy   : a descendant agent of the live server shows CPU or I/O over a short window, or a one-shot
           turn process (grok/codex) exists. Calibrated 2026-09-23: idle standby 0 ticks / 80 B in 3 s;
           a working agy 1-34 ticks / 0.1-0.8 MB per 2 s.

Command line (used by chatbot-ctl.sh):
  ctl_proc.py reap CODE_DIR     reap orphans; prints the count, logs agent.reaped
  ctl_proc.py busy CODE_DIR     exit 0 when the live server's agents are working, 1 when quiet
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

BUSY_CPU_TICKS = 2          # per sample window
BUSY_IO_BYTES = 4096        # rchar+wchar per sample window
SAMPLE_SEC = 2.0
QUIET_SAMPLES = 3           # consecutive quiet samples = idle

Proc = Dict[str, object]    # pid, ppid, age, args, cwd


def agent_kind(args: str) -> Optional[str]:
    """'stream' (agy/claude persistent), 'oneshot' (grok/codex per turn), or None."""
    if ("/.local/bin/agy" in args or "/.local/bin/claude" in args) and "--input-format stream-json" in args:
        return "stream"
    if "/.local/bin/grok" in args and "--prompt-file" in args:
        return "oneshot"
    tok0 = args.split(None, 1)[0] if args else ""
    if (tok0.endswith("/codex") or tok0 == "codex") and (
            "--json" in args or "app-server" in args or " login" in (" " + args + " ") or args.rstrip().endswith(" login")):
        return "oneshot"
    return None


def process_table() -> List[Proc]:
    out = subprocess.check_output(["ps", "-eo", "pid=,ppid=,etimes=,args="], text=True, errors="replace")
    rows: List[Proc] = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3 or not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        pid = int(parts[0])
        try:
            cwd = os.readlink("/proc/%d/cwd" % pid)
        except OSError:
            cwd = ""
        rows.append({"pid": pid, "ppid": int(parts[1]), "age": int(parts[2]) if parts[2].isdigit() else 0,
                     "args": parts[3] if len(parts) > 3 else "", "cwd": cwd})
    return rows


def live_chat_pid(table: List[Proc], code_dir: str) -> Optional[int]:
    """ctl's own pid file, trusted only if that pid is a running server.py."""
    try:
        pid = int(open(os.path.join(code_dir, "logs", "chatbot.pid"), encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return None
    for p in table:
        if p["pid"] == pid and "server.py" in str(p["args"]):
            return pid
    return None


def descends_from(table: List[Proc], pid: int, ancestor: Optional[int]) -> bool:
    if not ancestor:
        return False
    parent = {int(p["pid"]): int(p["ppid"]) for p in table}
    cur, hops = pid, 0
    while cur and cur != 1 and hops < 32:
        cur = parent.get(cur, 0)
        if cur == ancestor:
            return True
        hops += 1
    return False


def is_ours(p: Proc, workspace: str) -> bool:
    cwd = str(p.get("cwd") or "")
    return bool(agent_kind(str(p["args"]))) and (cwd == workspace or cwd.startswith(workspace + os.sep))


def classify(table: List[Proc], code_dir: str) -> Tuple[Optional[int], List[Proc], List[Proc]]:
    """(chat_pid, owned, orphans) among our agent processes."""
    workspace = os.path.join(os.path.realpath(code_dir), "data", "workspace")
    chat = live_chat_pid(table, code_dir)
    owned, orphans = [], []
    for p in table:
        if not is_ours(p, workspace):
            continue
        (owned if descends_from(table, int(p["pid"]), chat) else orphans).append(p)
    return chat, owned, orphans


def _log(code_dir: str, **fields) -> None:
    try:
        sys.path.insert(0, code_dir)
        import obslog  # the log library only (a file writer), not the service
        obslog.configure("ctl", mirror="error")
        obslog.event("agent.reaped", lvl="warn", caller=os.environ.get("CHATBOT_CALLER"), **fields)
    except Exception:
        pass


def reap(code_dir: str, table: Optional[List[Proc]] = None, kill=os.kill) -> int:
    table = process_table() if table is None else table
    chat, _owned, orphans = classify(table, code_dir)
    parent_args = {int(p["pid"]): str(p["args"]) for p in table}
    n = 0
    for p in orphans:
        try:
            kill(int(p["pid"]), signal.SIGTERM)
        except OSError:
            continue
        n += 1
        print("killed pid=%s reason=orphan ppid=%s" % (p["pid"], p["ppid"]), file=sys.stderr)
        _log(code_dir, agent_pid=p["pid"], ppid=p["ppid"], reason="orphan" if p["ppid"] != 1 else "ppid1",
             parent_cmd=parent_args.get(int(p["ppid"]), "")[:100], chat_pid=chat, age_s=p["age"], cmd=str(p["args"])[:200])
    return n


def _activity(pid: int) -> Tuple[int, int]:
    """(cpu ticks, rchar+wchar); (0, 0) when the process is gone or unreadable."""
    try:
        with open("/proc/%d/stat" % pid) as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = int(fields[11]) + int(fields[12])
        io = 0
        with open("/proc/%d/io" % pid) as f:
            for line in f:
                if line.startswith(("rchar:", "wchar:")):
                    io += int(line.split()[1])
        return ticks, io
    except (OSError, ValueError, IndexError):
        return 0, 0


def working(before: Dict[int, Tuple[int, int]], after: Dict[int, Tuple[int, int]]) -> bool:
    for pid, (t1, io1) in after.items():
        t0, io0 = before.get(pid, (t1, io1))
        if t1 - t0 >= BUSY_CPU_TICKS or io1 - io0 > BUSY_IO_BYTES:
            return True
    return False


def busy(code_dir: str, samples: int = QUIET_SAMPLES, sample_sec: float = SAMPLE_SEC,
         table_fn=process_table, activity=_activity, sleep=time.sleep) -> bool:
    """True when the live server's agents are working. Idle needs `samples` quiet windows in a row."""
    for _ in range(samples):
        table = table_fn()
        _chat, owned, _orphans = classify(table, code_dir)
        if any(agent_kind(str(p["args"])) == "oneshot" for p in owned):
            return True
        pids = [int(p["pid"]) for p in owned]
        if not pids:
            return False
        before = {pid: activity(pid) for pid in pids}
        sleep(sample_sec)
        if working(before, {pid: activity(pid) for pid in pids}):
            return True
    return False


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("reap", "busy"):
        sys.stderr.write(__doc__.split("Command line", 1)[1])
        return 2
    code_dir = os.path.realpath(argv[1])
    if argv[0] == "reap":
        print(reap(code_dir))
        return 0
    return 0 if busy(code_dir) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
