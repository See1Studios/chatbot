"""The rule that sweeps a block still being written stays inside its bubble (FLOW_SWEEP_INSIDE_v1,
static/chat-log.css): from the block's left edge to its right edge, never past either.
Run: python3 -m unittest tests.test_flow_sweep  (from services/chatbot)
"""
import re
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

CSS = (REPO / "static" / "chat-log.css").read_text(encoding="utf-8")


class FlowSweep(unittest.TestCase):
    def test_the_sweep_starts_and_ends_inside_the_block(self):
        rule = re.search(r"\.md-block\.open::after\{([^}]*)\}", CSS).group(1)
        width = float(re.search(r"width:([\d.]+)%", rule).group(1))
        frames = re.search(r"@keyframes flow-sweep\{(.*?)\}\}", CSS, re.S).group(1)
        moves = [float(x) for x in re.findall(r"translateX\((-?[\d.]+)%?\)", frames)]
        self.assertGreaterEqual(min(moves), 0, "no start left of the block")
        self.assertLessEqual(width * (1 + max(moves) / 100), 100.5, "no end right of the block")
        self.assertGreaterEqual(width * (1 + max(moves) / 100), 99, "it still crosses the whole block")


if __name__ == "__main__":
    unittest.main()
