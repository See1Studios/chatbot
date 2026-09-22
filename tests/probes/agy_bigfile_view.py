"""agy big-file view probe: what does `view_file` answer when a large file is opened WITHOUT a
line range, and does the model page or repeat? Born from 2026-09-21, when the loop guard stopped a
turn after 10 identical `view_file adapters.py` calls whose streamed output was only
"1949 lines, 94302 bytes".

Spawns agy like the host (AgyAdapter.build_args/build_env, cwd=WORKSPACE, stream-json), sends ONE
read-only message, stores every finished tool step RAW (params + full output) in --out, and kills
the child after --max-calls tool calls or --timeout seconds. Mutates nothing.

    python3 tests/probes/agy_bigfile_view.py
    python3 tests/probes/agy_bigfile_view.py --file /path/big.md --max-calls 6
    python3 tests/probes/agy_bigfile_view.py --task edit --max-calls 15 --timeout 240

`--task edit` asks for a small edit and runs it on a SCRATCH COPY under /tmp (never the real file),
then replays the recorded calls through loop_guard to say whether it would have warned/stopped.

Results and what they proved: docs/providers/agy.md. Record the outcome there afterwards.
"""
import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters import AgyAdapter  # noqa: E402
from host_config import DEFAULT_MODEL, HOME, WORKSPACE  # noqa: E402
from loop_guard import LoopGuard  # noqa: E402

DEFAULT_FILE = str(Path(__file__).resolve().parents[2] / "adapters.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--task", choices=("read", "edit"), default="read")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-calls", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=150)
    ap.add_argument("--out", default="/tmp/agy_bigfile_view.jsonl")
    a = ap.parse_args()

    if a.task == "edit":
        scratch = Path("/tmp/agy_probe_scratch")
        scratch.mkdir(exist_ok=True)
        a.file = str(shutil.copy(a.file, scratch / Path(a.file).name))
        msg = (f"{a.file} 의 OpenAIDialectAdapter 클래스에 OpenRouter 직결을 위한 `base_url` 인자를 "
               f"받는 __init__ 을 바로 적용해줘. 실제로 파일을 수정해.")
    else:
        msg = (f"{a.file} 를 view_file 로 열어서, OpenAI 방언 어댑터 클래스의 이름과 그 클래스가 "
               f"시작하는 줄 번호만 알려줘. 다른 도구는 쓰지 마.")
    ad = AgyAdapter()
    args = ad.build_args(a.model, "", str(uuid.uuid4()), [])
    p = subprocess.Popen(
        args, cwd=str(WORKSPACE), env=ad.build_env(HOME),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, start_new_session=True,
    )
    p.stdin.write(ad.format_stdin(msg))
    p.stdin.flush()

    calls, result, t0 = 0, None, time.time()
    with open(a.out, "w", encoding="utf-8") as out:
        while time.time() - t0 < a.timeout and calls < a.max_calls:
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
            if isinstance(su, dict) and su.get("step_type") == "tool" and su.get("state") == "DONE":
                calls += 1
                ti = su.get("tool_info") or {}
                out.write(json.dumps({"t": round(time.time() - t0, 1), "name": ti.get("name"),
                                      "parameters": ti.get("parameters"), "output": ti.get("output")},
                                     ensure_ascii=False) + "\n")
                out.flush()
            if o.get("event") == "result":
                result = o.get("result")
                break
    try:
        os.killpg(p.pid, 9)
    except OSError:
        pass
    print(f"model={a.model} tool_calls={calls} elapsed={time.time() - t0:.0f}s result={'yes' if result else 'no'} out={a.out}")
    guard, verdicts = LoopGuard(), []
    for l in open(a.out, encoding="utf-8"):
        d = json.loads(l)
        v = guard.observe(d["name"], d["parameters"], d["output"])
        o = d["output"] if isinstance(d["output"], str) else json.dumps(d["output"], ensure_ascii=False)
        print(f"{d['t']:>6}s {d['name']:<14} {json.dumps(d['parameters'], ensure_ascii=False)[:110]} | out {len(o)}: {o[:50]!r}")
        if v:
            verdicts.append((guard.calls, v.level, v.rule))
    print("loop_guard replay:", verdicts or "quiet")
    if result:
        print("answer:", json.dumps(result, ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
