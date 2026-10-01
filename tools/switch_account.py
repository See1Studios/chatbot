#!/usr/bin/env python3
"""switch-account: list the saved agy logins, or swap to one in a second (providers/accounts.py profiles).

  python3 tools/switch_account.py                    # saved logins, numbered, the active one marked *
  python3 tools/switch_account.py 2                  # switch to login number 2
  python3 tools/switch_account.py user@example.com   # switch to that login

The active login is saved before every list and switch, so a fresh OAuth login joins the list by itself.
This process cannot stop the chatbot server's sessions: the server's auto-recycle restarts its idle ones
still on the old login within half a minute; processes started elsewhere (SSH) must be stopped by hand.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers import accounts  # noqa: E402


def show(profiles: list) -> None:
    if not profiles:
        print("no saved logins yet: log in once, then run this again")
    for p in profiles:
        saved = time.strftime("%Y-%m-%d %H:%M", time.localtime(p["saved_at"]))
        print("%s %2d  %s  (saved %s)" % ("*" if p["active"] else " ", p["index"], p["email"], saved))
    print("active: %s" % (accounts.current_email("agy") or "none"))


def switch(target: str) -> int:
    r = accounts.switch_profile(target)
    if not r["ok"]:
        print("error: %s" % r["error"], file=sys.stderr)
        show(accounts.list_profiles())
        return 1
    print("switched: %s -> %s" % (r["email_before"] or "none", r["email"]))
    if r["stale_pids"]:
        print("still on the old login: pids %s -- the server restarts its idle ones within ~30s; stop others by hand"
              % ", ".join(map(str, r["stale_pids"])))
    else:
        print("no running agy process holds the old login")
    print("active: %s" % r["email"])
    return 0


def main(argv: list) -> int:
    if argv:
        return switch(argv[0])   # switch_profile saves the active login itself
    if accounts.current_email("agy"):
        accounts.save_profile()
    show(accounts.list_profiles())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
