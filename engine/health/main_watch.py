#!/usr/bin/env python3
"""MAIN_WATCH_v1 (#825): after main moves, the whole suite runs once on what main now holds, and the event log says
whether main is green (`main.check`). The commit hook runs only the guards and the staged files' related tests, so a
change that breaks a module far from its files still lands; on 2026-10-08 #817/#821/#822 left four modules red on
main and nobody saw it until another agent's full run. The log digest turns a red main into its first finding.

  python3 engine/tools/main_watch.py run     # check main until it stops moving (the reference-transaction hook
                                             # starts it in the background once main has moved)

One check at a time: a start while one runs only marks main as moved, and the running check goes again when it
ends, so a burst of commits costs one or two runs. The check waits SETTLE_SEC first for the rest of a burst (a
change and its HISTORY commit). It judges a throwaway worktree at main's commit, never the shared working tree.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

ENGINE = Path(__file__).resolve().parent.parent
REPO = ENGINE.parent
sys.path.insert(0, str(ENGINE))
import platform_compat  # noqa: E402

STATE = Path.home() / ".cache" / "chatbot-main-watch"   # lock, the "main moved again" mark, snapshots
SETTLE_SEC = 60
SUITE_TIMEOUT_SEC = 1800   # the suite takes ~4 min alone; it may wait for another test run first (TEST_LOCK_v1)


def no_git_env() -> Dict[str, str]:
    """Started from a hook, GIT_DIR and co. point at the repo that moved; every git call here names its repo."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(*args: str, repo: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120,
                          env=no_git_env())


def suite(sha: str, repo: Path = REPO) -> Dict:
    """Run engine/run-tests.sh on a throwaway worktree at `sha`. {ok, failed, dur_s, tail}."""
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=str(STATE)))
    tree = tmp / "tree"
    t0 = time.time()
    # a developer's shell: no install settings (the suite picks its own data)
    env = {k: v for k, v in no_git_env().items() if not k.startswith(("CHATBOT_", "PE_", "PRIVATEENGINE_"))}
    try:
        add = git("worktree", "add", "--detach", "--quiet", str(tree), sha, repo=repo)
        if add.returncode != 0:
            return {"ok": None, "failed": [], "dur_s": 0, "tail": add.stderr.strip()[-300:]}
        cmd = ["bash", str(tree / "engine" / "run-tests.sh")]   # l10n-ok: the repo's test entry point is bash
        try:
            r = subprocess.run(cmd, cwd=str(tree), env=env, capture_output=True, text=True, timeout=SUITE_TIMEOUT_SEC)
            out, code = r.stdout, r.returncode
        except subprocess.TimeoutExpired:
            out, code = "failed: (the suite timed out after %ds)" % SUITE_TIMEOUT_SEC, 124
        failed = next((l.split(":", 1)[1].split() for l in reversed(out.splitlines()) if l.startswith("failed:")), [])
        return {"ok": code == 0, "failed": failed, "dur_s": round(time.time() - t0),
                "tail": "" if code == 0 else "\n".join(out.strip().splitlines()[-3:])}
    finally:
        git("worktree", "remove", "--force", str(tree), repo=repo)
        shutil.rmtree(str(tmp), ignore_errors=True)
        git("worktree", "prune", repo=repo)


def record(sha: str, result: Dict) -> None:
    import host_config
    from telemetry import obslog
    obslog.configure("watch", path=host_config.EVENTS_LOG, mirror="error")
    subject = git("log", "-1", "--format=%s (%an)", sha).stdout.strip()
    obslog.event("main.check", lvl="info" if result["ok"] else "error", sha=sha[:12], subject=subject[:160],
                 ok=result["ok"], failed=result["failed"][:30], dur_s=result["dur_s"], tail=result["tail"])


def run(settle: float = SETTLE_SEC, repo: Path = REPO, check=suite, note=record) -> int:
    """Check main until it stops moving; one holder at a time. Returns how many checks ran (0: another holds it)."""
    STATE.mkdir(parents=True, exist_ok=True)
    again = STATE / "again"
    with open(STATE / "lock", "w", encoding="utf-8", newline="\n") as lock:
        if not platform_compat.lock_file(lock, blocking=False):
            again.touch()   # the holder goes again when it ends
            return 0
        n = 0
        while True:
            time.sleep(settle)
            again.unlink(missing_ok=True)   # commits up to here are in this check
            sha = git("rev-parse", "main", repo=repo).stdout.strip()
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                return n
            note(sha, check(sha, repo))
            n += 1
            if not again.exists() and git("rev-parse", "main", repo=repo).stdout.strip() == sha:
                return n


def main(argv: Optional[List[str]] = None) -> int:
    if (argv if argv is not None else sys.argv[1:])[:1] != ["run"]:
        print("usage: main_watch.py run", file=sys.stderr)
        return 2
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
