#!/usr/bin/env python3
"""Check character images against the format (CHARACTER_ART_v1, skill `character-art`).

  python3 tools/check_character_art.py            every character
  python3 tools/check_character_art.py <id>       one character

Exit 0 when every checked character is fine, 1 otherwise. Every character alike (TEAM_ROLES_v2).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import characters  # noqa: E402


def main(argv) -> int:
    try:
        from providers.adapters import AGENT_ADAPTERS
        providers = sorted(AGENT_ADAPTERS)
    except Exception:  # noqa: BLE001
        providers = []
    rows = [c for c in characters.listing() if not argv or c["id"] in argv]
    if argv and not rows:
        print("no such character: %s" % " ".join(argv))
        return 1
    bad = 0
    for c in rows:
        problems = characters.check_art(c["id"], providers)
        print("%s %s (%s)" % ("ok  " if not problems else "FIX ", c["name"] or c["id"], c["id"]))
        for p in problems:
            print("     - " + p)
        bad += bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
