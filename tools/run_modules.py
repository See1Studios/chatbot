#!/usr/bin/env python3
"""run_modules: the test suite without bash -- one process per tests/test_*.py module, like run-tests.sh, on any OS
(platform-portability pp/C, #401). run-tests.sh stays the NAS entry point; this runs on Windows (FIREBAT), macOS and
CI runners, where bash is missing or different.

  python3 tools/run_modules.py              every tests/test_*.py
  python3 tools/run_modules.py --fast       the guard tests (the FAST list, read from run-tests.sh: one list)
  python3 tools/run_modules.py test_x ...   these modules
  --json FILE                               also write {module: {ok, sec, why}} there

Each run gets its own temporary folder (TMPDIR/TEMP/TMP) and removes it after, as run-tests.sh does. The child's
output is read as UTF-8 with replacement, and this runner's own output replaces what the console cannot show (a
Korean Windows console is cp949). Test processes run in Python's UTF-8 mode, as the shipped build does
(platform-portability PP4): engine code names its encodings itself (test_platform_imports), the tests need not.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = int(os.environ.get("TEST_TIMEOUT", "300"))
WHY = re.compile(r"^(\w+Error|\w+Exception|AssertionError|KeyError)\b")


def fast_modules() -> list:
    """The FAST=( ... ) list of run-tests.sh."""
    text = (ROOT / "run-tests.sh").read_text(encoding="utf-8")
    m = re.search(r"^FAST=\((.*?)^\)", text, re.S | re.M)
    return re.findall(r"\b(test_\w+)\b", m.group(1)) if m else []


def run(mods: list) -> dict:
    base = "/tmp" if os.name == "posix" and os.path.isdir("/tmp") else None   # run-tests.sh: not under $HOME
    run_tmp = tempfile.mkdtemp(prefix="chatbot-tests.", dir=base)
    env = dict(os.environ, TMPDIR=run_tmp, TEMP=run_tmp, TMP=run_tmp, PYTHONUTF8="1")
    results = {}
    try:
        for m in mods:
            if not (ROOT / "tests" / (m + ".py")).is_file():
                print("MISSING %s (no tests/%s.py)" % (m, m), flush=True)
                results[m] = {"ok": False, "sec": 0, "why": "missing"}
                continue
            t0 = time.time()
            try:
                p = subprocess.run([sys.executable, "-m", "unittest", "tests." + m], cwd=str(ROOT), env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT)
                out, ok = p.stdout.decode("utf-8", "replace"), p.returncode == 0
                why = "" if ok else next((ln.strip() for ln in out.splitlines() if WHY.match(ln.strip())),
                                         "exit %d" % p.returncode)
            except subprocess.TimeoutExpired:
                out, ok, why = "", False, "timeout %ds" % TIMEOUT
            sec = round(time.time() - t0, 1)
            results[m] = {"ok": ok, "sec": sec, "why": why[:300]}
            print(("ok   %6dms %s" if ok else "FAIL %6dms %s  " + why[:160]) % (int(sec * 1000), m), flush=True)
            if not ok and out:
                for ln in out.splitlines()[-15:]:
                    print("     | " + ln, flush=True)
    finally:
        shutil.rmtree(run_tmp, ignore_errors=True)
    return results


def main(argv: list) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    json_out = None
    if "--json" in argv:
        i = argv.index("--json")
        json_out = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if argv[:1] == ["--fast"]:
        mods = fast_modules()
    elif argv:
        mods = [os.path.basename(a)[:-3] if a.endswith(".py") else os.path.basename(a) for a in argv]
    else:
        mods = sorted(p.stem for p in (ROOT / "tests").glob("test_*.py"))
    t0 = time.time()
    results = run(mods)
    failed = [m for m, r in results.items() if not r["ok"]]
    print("---")
    print("%d/%d modules passed in %ds" % (len(mods) - len(failed), len(mods), time.time() - t0))
    if failed:
        print("failed: " + " ".join(failed))
    if json_out:
        Path(json_out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
