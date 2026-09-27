"""Ratchets: counts that may only go down (localization l10n/B, direction-alignment align/E). Per file, the number of
lines matching a pattern must not exceed ratchet_baseline.json; when it drops, lower the baseline in the same change:
  python3 tests/test_ratchets.py --update     (lowers only; refuses while any file is above its baseline)
A line that is Korean or names the host on purpose (a prompt example, a Korean regex) ends with `l10n-ok`.

- l10n: hardcoded Korean (Hangul) in engine and page code -> moves to i18n catalogs (docs/plans/localization.md).
- host_identity: the dev install's host and persona (DiskStation, /volume1, Sphere, 실장님, 냥) in engine code, outside
  the NAS host plugin -> neutral strings or environment plugins (docs/plans/direction-alignment.md D3, D4).
Run: python3 -m unittest tests.test_ratchets  (from services/chatbot)
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "ratchet_baseline.json"
PRAGMA = "l10n-ok"
RATCHETS = {
    "l10n": (re.compile(r"[가-힣]"), ()),
    "host_identity": (re.compile(r"DiskStation|diskstation|/volume1|Sphere|실장님|냥"), ("nas_mcp_host.py",)),  # l10n-ok
}


def files():
    code = list(ROOT.glob("*.py")) + list(ROOT.glob("providers/*.py")) + list(ROOT.glob("tools/*.py"))
    page = [p for p in ROOT.glob("static/*") if p.suffix in (".js", ".html", ".css")]
    return sorted(code + page)


def counts(name):
    rx, skip = RATCHETS[name]
    out = {}
    for p in files():
        if p.name in skip:
            continue
        n = sum(1 for line in p.read_text(encoding="utf-8", errors="ignore").splitlines()
                if rx.search(line) and PRAGMA not in line)
        if n:
            out[p.relative_to(ROOT).as_posix()] = n
    return out


def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


class Ratchets(unittest.TestCase):
    def check(self, name):
        base = baseline()[name]
        now = counts(name)
        for f, n in sorted(now.items()):
            self.assertLessEqual(n, base.get(f, 0), "%s: %s has %d lines, baseline %d. Do not add more (see this file's "
                                 "docstring); mark an intended line `%s`" % (name, f, n, base.get(f, 0), PRAGMA))
        stale = {f: (b, now.get(f, 0)) for f, b in base.items() if now.get(f, 0) < b}
        self.assertFalse(stale, "%s went down %s: run python3 tests/test_ratchets.py --update" % (name, stale))

    def test_hardcoded_korean_does_not_grow(self):
        self.check("l10n")

    def test_host_and_persona_identity_does_not_grow(self):
        self.check("host_identity")


def update():
    base = baseline()
    for name in RATCHETS:
        now = counts(name)
        up = {f: (base[name].get(f, 0), n) for f, n in now.items() if n > base[name].get(f, 0)}
        if up:
            print("refused: %s grew %s -- remove the lines instead" % (name, up))
            return 1
        base[name] = now
    BASELINE.write_text(json.dumps(base, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("baseline lowered: " + ", ".join("%s %d" % (k, sum(v.values())) for k, v in base.items()))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--update"]:
        sys.exit(update())
    unittest.main()
