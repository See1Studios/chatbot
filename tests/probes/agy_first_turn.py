"""agy first-turn probe: input tokens, steps, tool calls, and what agy's own
log says it loaded. Spawns agy exactly like the host (adapters.AgyAdapter
build_args/build_env, cwd=WORKSPACE, stream-json), sends ONE message, reads
the result, kills the child. No live-server state is touched.

Results and what they proved: docs/providers/agy.md. Read that BEFORE running
anything new, and record the outcome there afterwards.

    python3 tests/probes/agy_first_turn.py                       # baseline vs +WORKSPACE
    python3 tests/probes/agy_first_turn.py --add-dir /some/dir   # extra add-dir(s)
    python3 tests/probes/agy_first_turn.py --flag --disable-slash-commands
    python3 tests/probes/agy_first_turn.py --home /tmp/fakehome  # alternate HOME

Caveats measured the hard way:
  * the very first turn after a host restart can report input_tokens == 0
    (observation 0009) -- re-run, don't conclude;
  * input_tokens sums every LLM step of the turn, so a run where the model
    called tools is not comparable to a 1-step run (compare `steps`).
"""
import argparse
import collections
import glob
import json
import os
import re
import select
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters import AgyAdapter  # noqa: E402
from host_config import DEFAULT_MODEL, HOME, WEB_ROOT, WORKSPACE  # noqa: E402

AGY_LOG_GLOB = os.path.expanduser("~/.gemini/antigravity-cli/log/cli-*.log")


def run(add_dirs, msg="안녕", extra_args=(), home=None, conversation_id=None, timeout=150):
    """-> (result dict | None, step counter, [(tool_name, params)], new log text)"""
    a = AgyAdapter()
    args = a.build_args(DEFAULT_MODEL, "", conversation_id or str(uuid.uuid4()), add_dirs) + list(extra_args)
    before = set(glob.glob(AGY_LOG_GLOB))
    p = subprocess.Popen(
        args, cwd=str(WORKSPACE), env=a.build_env(Path(home) if home else HOME),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, start_new_session=True,
    )
    p.stdin.write(a.format_stdin(msg))
    p.stdin.flush()
    steps, tools, res, t0 = collections.Counter(), [], None, time.time()
    while time.time() - t0 < timeout:
        r, _, _ = select.select([p.stdout], [], [], 2)
        if not r:
            continue
        line = p.stdout.readline()
        if not line:
            break
        try:
            o = json.loads(line)
        except ValueError:
            continue
        su = o.get("step_update")
        if su and su.get("state") == "DONE":
            steps[su.get("step_type")] += 1
            if su.get("step_type") not in ("user_input", "agent_response", "unknown"):
                ti = su.get("tool_info") or {}
                tools.append((ti.get("name"), json.dumps(ti.get("parameters"), ensure_ascii=False)[:100]))
        if o.get("event") == "result":
            res = o["result"]
            break
    try:
        os.killpg(p.pid, 9)
    except OSError:
        pass
    new = sorted(set(glob.glob(AGY_LOG_GLOB)) - before, key=os.path.getmtime)
    log = "\n".join(open(f, errors="replace").read() for f in new[-2:])
    return res, steps, tools, log


def summarize(name, res, steps, tools, log):
    u = (res or {}).get("usage") or {}
    scan = "master-skills" in log
    hooks = re.findall(r"loaded (\d+) named hooks", log)
    print(f"{name:40s} in={u.get('input_tokens')} status={(res or {}).get('status')} "
          f"steps={dict(steps)} tools={[t[0] for t in tools]} skill-scan={scan} hooks={hooks[:1]}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-dir", action="append", default=[])
    ap.add_argument("--flag", nargs=argparse.REMAINDER, default=[])
    ap.add_argument("--home")
    ap.add_argument("--msg", default="안녕")
    ns = ap.parse_args()
    chat = str(WEB_ROOT / "chat")
    if ns.add_dir or ns.flag or ns.home:
        summarize("custom", *run([chat] + ns.add_dir, ns.msg, ns.flag, ns.home))
    else:
        summarize("chat only (baseline)", *run([chat], ns.msg))
        summarize("chat + WORKSPACE (host today)", *run([chat, str(WORKSPACE)], ns.msg))
