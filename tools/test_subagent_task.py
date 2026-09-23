#!/usr/bin/env python3
"""Prototype test script for headless CLI subagent invocation.
Tests running claude -p, codex exec, etc. with a small isolated prompt.
"""

import subprocess
import sys
import time
import shutil

TARGETS = {
    "claude": ["claude", "-p", "--dangerously-skip-permissions"],
    "codex": ["codex", "exec"],
}

def run_headless(argv: list, prompt: str) -> dict:
    if not shutil.which(argv[0]):
        return {"success": False, "error": f"{argv[0]} CLI not found"}

    t0 = time.time()
    try:
        proc = subprocess.run(
            argv + [prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False
        )
        elapsed = time.time() - t0
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "elapsed_sec": round(elapsed, 2),
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip()
        }
    except Exception as e:
        return {"success": False, "error": str(e), "elapsed_sec": round(time.time() - t0, 2)}

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "claude"
    test_prompt = "너는 보조 리서처 에이전트다. 'DiskStation NAS에서 서브에이전트가 갖는 최대 장점'을 1문장으로만 답하라."
    
    print(f"=== Testing Subagent CLI: {target} ===")
    if target not in TARGETS:
        print(f"Unknown target: {target}")
        sys.exit(1)
    res = run_headless(TARGETS[target], test_prompt)

    print(f"Success: {res.get('success')}")
    print(f"Elapsed: {res.get('elapsed_sec')}s")
    if res.get("stdout"):
        print(f"Output:\n{res['stdout']}")
    if res.get("stderr"):
        print(f"Stderr:\n{res['stderr']}")
    if res.get("error"):
        print(f"Error:\n{res['error']}")
