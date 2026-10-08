#!/usr/bin/env python3
"""CLOSE_ASYNC_v1 (#819): close a ticket whose delegated change landed but stayed open (`merged-ticket-open`).

`delegation.py` starts this in its own process with the operator's lease (merge_go) and answers the page at once.
`done` runs the guard tests (~50 s, minutes on a busy host); the page gave up after 12 s, so the operator pressed
again and again (#456, 2026-10-08). The run state says how it ended; a refusal stays on the card as its reason.

  python3 engine/tools/ticket_close.py --ticket N --token T
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional

import worktree_runner as wr


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Close a ticket whose delegated change already landed")
    p.add_argument("--ticket", type=int, required=True)
    p.add_argument("--token", required=True, help="Lease token from merge_go")
    p.add_argument("--json", action="store_true", help="Print the result as JSON")
    args = p.parse_args(argv)
    tid = args.ticket
    st = wr.read_state(tid)
    if st.get("phase") != "merging" or not st.get("closing") or not st.get("head"):
        print("Error: ticket #%d is not being closed after its merge (%s)" % (tid, wr.state_path(tid)), file=sys.stderr)
        return 2
    provider = st.get("provider", "")
    actor = wr.PROVIDERS[provider]["actor"] if provider in wr.PROVIDERS else (wr.worker_role() or "host")
    result: Dict = {"ticket": tid, "provider": provider, "merged": False, "head": st["head"]}
    wr.close_done(tid, args.token, actor, "merged %s earlier; closed on the operator's word" % st["head"][:7], result)
    return wr.record_and_report(wr.CHATBOT_REPO, tid, provider, st.get("title", ""), result, args.json)


if __name__ == "__main__":
    sys.exit(main())
