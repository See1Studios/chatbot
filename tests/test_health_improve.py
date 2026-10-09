"""improvement-layers il/D2: improvement signals read from the daily rollups -- each a defined ratio with a minimum
sample, decided by the engine -- and they become incidents like the log digest's findings.
Run: engine/run-tests.sh test_health_improve
"""
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
from health import improve as M  # noqa: E402
from health import incidents as I  # noqa: E402


def day(n, turns=0, loops=0, heavy=0, spoke=0, injected=0, calls=None):
    return {"day": "2026-10-%02d" % n,
            "by_evt": {"turn.end": turns, "turn.loop_notice": loops},
            "messages": {"react_turn": spoke, "react_skip": {"session_heavy": heavy}},
            "memory": {"injected_chars": {"own_memory": {"n": injected}}, "calls": calls or {}}}


class Signals(unittest.TestCase):
    def codes(self, days):
        return [f["code"] for f in M.findings(days)]

    def test_loops_count_when_the_rate_doubled_and_is_not_tiny(self):
        base = [day(n, turns=100, loops=3) for n in range(1, 8)]
        self.assertEqual(self.codes(base + [day(n, turns=100, loops=10) for n in (8, 9, 10)]), ["turn_loops"])
        self.assertEqual(self.codes(base + [day(n, turns=100, loops=5) for n in (8, 9, 10)]), [], "not twice")
        low = [day(n, turns=100, loops=1) for n in range(1, 8)]
        self.assertEqual(self.codes(low + [day(n, turns=100, loops=4) for n in (8, 9, 10)]), [], "4% is not much")

    def test_a_quiet_stretch_proves_nothing(self):
        base = [day(n, turns=100, loops=1) for n in range(1, 8)]
        self.assertEqual(self.codes(base + [day(n, turns=10, loops=5) for n in (8, 9, 10)]), [], "30 turns")
        self.assertEqual(self.codes([day(n, turns=100, loops=20) for n in (8, 9, 10)]), [], "no base to compare")

    def test_heavy_skips_count_when_they_reach_what_was_spoken(self):
        self.assertEqual(self.codes([day(n, heavy=5, spoke=4) for n in range(1, 8)]), ["react_heavy_skips"])
        self.assertEqual(self.codes([day(n, heavy=5, spoke=6) for n in range(1, 8)]), [])
        self.assertEqual(self.codes([day(n, heavy=2, spoke=0) for n in range(1, 8)]), [], "14 skips")

    def test_memory_unused_looks_only_at_days_it_was_injected(self):
        old = [day(n, calls={"search": 3}) for n in range(1, 5)]          # before injection was measured
        self.assertEqual(self.codes(old + [day(n, injected=8) for n in (5, 6, 7)]), ["memory_unused"])
        self.assertEqual(self.codes([day(n, injected=8, calls={"search": 1} if n == 7 else {}) for n in (5, 6, 7)]), [])
        self.assertEqual(self.codes([day(n, injected=5) for n in (5, 6, 7)]), [], "15 injections")

    def test_a_signal_is_an_incident_like_a_log_finding(self):
        path = Path(tempfile.mkdtemp()) / "dev" / "incidents.json"
        sig = M.findings([day(n, heavy=5, spoke=1) for n in range(1, 8)])
        got = I.tick(path, 1_800_000_000.0, digest={"findings": []}, improvements=sig)
        self.assertEqual([(c["change"], c["incident"]["code"]) for c in got], [("open", "react_heavy_skips")])
        self.assertEqual(I.tick(path, 1_800_003_600.0, digest={"findings": []}, improvements=sig), [], "same key")


if __name__ == "__main__":
    unittest.main()
