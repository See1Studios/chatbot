"""#895: the probe after a repair waits 15 s and tries once more. The first turn after a start spawns its agent and took
8-9 s under load, so an 8 s probe called four sound repairs failed on 2026-10-09 -- an error incident each.
Run: engine/run-tests.sh test_ctl_probe
"""
import unittest

from tests._paths import ENGINE  # noqa: E402


class RepairProbe(unittest.TestCase):
    def test_the_repair_probe_waits_15_s_and_tries_once_more(self):
        src = (ENGINE / "chatbot-ctl.sh").read_text(encoding="utf-8")
        self.assertIn("REPAIR_PROBE_SEC=15", src)
        self.assertIn('if probe_message "$REPAIR_PROBE_SEC" || { echo "probe once more"; probe_message "$REPAIR_PROBE_SEC"; }; then', src)
        self.assertNotIn("if probe_message 8; then", src)


if __name__ == "__main__":
    unittest.main()
