#!/usr/bin/env python3
"""Token accounting audit over data/sessions/*/meta.json.

Two meters, never mixed:
  occupancy  = last turn's input_tokens (prompt size of that request)
  billed     = sum of each turn's total_tokens (in+out this request)

Do not compute input - cache_read. cache_read is often a CLI lifetime
counter larger than this turn's input.

Usage:
  python3 tools/token_audit.py
  python3 tools/token_audit.py --sid 20260918-104829-d6bc10
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

SESSIONS = Path(__file__).resolve().parents[2] / "sessions"


def _turns(hist: list) -> list:
    out = []
    for h in hist or []:
        if h.get("role") != "assistant":
            continue
        u = h.get("usage")
        if not isinstance(u, dict):
            continue
        inp = int(u.get("input_tokens") or 0)
        outp = int(u.get("output_tokens") or 0)
        tot = int(u.get("total_tokens") or 0) or (inp + outp)
        cache = int(u.get("cache_read_tokens") or 0)
        if tot or inp:
            out.append({"in": inp, "out": outp, "total": tot, "cache": cache})
    return out


def _med(xs: list) -> int:
    if not xs:
        return 0
    return int(statistics.median(xs))


def audit_one(meta: dict, turns: list) -> dict:
    billed = sum(t["total"] for t in turns)
    occupancy = turns[-1]["in"] if turns and turns[-1]["in"] else (turns[-1]["total"] if turns else 0)
    first_in = turns[0]["in"] if turns else 0
    later_in = [t["in"] for t in turns[1:] if t["in"]]
    return {
        "id": meta.get("id") or "",
        "provider": meta.get("provider") or "legacy",
        "n": len(turns),
        "first_in": first_in,
        "later_med_in": _med(later_in),
        "occupancy": occupancy,
        "billed": billed,
        "sum_over_occ": round(billed / occupancy, 2) if occupancy else 0,
        "turns": turns,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid", default="", help="one session id")
    args = ap.parse_args()

    rows = []
    paths = [SESSIONS / args.sid / "meta.json"] if args.sid else sorted(SESSIONS.glob("*/meta.json"))
    for p in paths:
        if not p.exists():
            print("missing", p)
            return 1
        d = json.loads(p.read_text(encoding="utf-8"))
        ts = _turns(d.get("history") or [])
        if not ts:
            continue
        rows.append(audit_one(d, ts))

    by = defaultdict(list)
    for r in rows:
        by[r["provider"]].append(r)

    print("session-start occupancy ≈ first_in. every-turn occupancy ≈ later_med_in.")
    print("billed = sum of per-request total_tokens. cache_read is NOT subtracted.\n")
    print(f"{'provider':12} {'sess':>4} {'first_in':>9} {'first_max':>9} {'later_in':>9} {'occ_now':>9} {'billed':>10}")
    for prov, rs in sorted(by.items()):
        firsts = [r["first_in"] for r in rs]
        print(
            f"{prov:12} {len(rs):4} {_med(firsts):9} {max(firsts):9} "
            f"{_med([r['later_med_in'] for r in rs if r['later_med_in']]):9} "
            f"{_med([r['occupancy'] for r in rs]):9} {_med([r['billed'] for r in rs]):10}"
        )

    if args.sid:
        r = rows[0]
        print(f"\n{r['id']} provider={r['provider']} n={r['n']} occupancy={r['occupancy']} billed={r['billed']}")
        for i, t in enumerate(r["turns"], 1):
            print(f"  t{i:02} in={t['in']:7} out={t['out']:6} total={t['total']:7} cache={t['cache']}")
        return 0

    print("\nbiggest occupancy (top 8)")
    for r in sorted(rows, key=lambda x: -x["occupancy"])[:8]:
        print(f"  {r['id']} {r['provider']:10} occ={r['occupancy']:8} billed={r['billed']:9} n={r['n']} first={r['first_in']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
