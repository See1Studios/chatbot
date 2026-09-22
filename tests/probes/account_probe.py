#!/usr/bin/env python3
"""Read-only probe behind the account claims in docs/providers/*.md
(agy A29-A32, claude C11-C12, codex X9-X11, grok G9-G10).

Prints, per provider: the account as accounts.py resolves it, the SHAPE of the
raw auth source (key names + value types only -- never values), and the running
CLI processes. Tokens are never printed. /proc/<pid>/environ is never read.

    python3 tests/probes/account_probe.py            # all providers
    python3 tests/probes/account_probe.py agy codex  # subset
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import accounts  # noqa: E402

SOURCES = {
    "agy": lambda: accounts.AGY_TOKEN,
    "codex": lambda: accounts.CODEX_AUTH,
    "grok": lambda: accounts.GROK_AUTH,
    "claude": lambda: Path.home() / ".claude" / ".credentials.json",
}


def shape(o, depth=0):
    if isinstance(o, dict):
        return {k: (shape(v, depth + 1) if depth < 2 else "...") for k, v in o.items()}
    if isinstance(o, list):
        return f"list[{len(o)}]"
    return type(o).__name__ + (f"({len(o)})" if isinstance(o, str) else "")


def main(which):
    snap = accounts.snapshot()
    for prov in which:
        pv = snap["providers"][prov]
        cur = pv["current"]
        print(f"== {prov}")
        print(f"   account : {cur.get('email')}  plan={cur.get('plan')}  ok={cur.get('ok')}  via {cur.get('source')}")
        src = SOURCES[prov]()
        try:
            print("   raw shape:", json.dumps(shape(json.loads(src.read_text())), ensure_ascii=False)[:400])
        except Exception as e:
            print("   raw shape: n/a", type(e).__name__)
        print(f"   per-process account evidence: {pv['account_evidence']}")
        for p in pv["processes"]:
            print(f"   pid {p['pid']:>6} {p['owner']:<13} acct={p['account']} stale={p['stale']} "
                  f"predates_change={p['predates_change']} age={p['age_sec']}s tty={p['tty']}")
        if not pv["processes"]:
            print("   (no running processes)")


if __name__ == "__main__":
    main(sys.argv[1:] or list(accounts.PROVIDERS))
