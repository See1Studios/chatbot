"""TEST_NODE_v1 (#859): the node the page tests get has a full Intl, as browsers do. A DSM update (2026-10-09) put
a node first on PATH whose Intl is English-only and whose Intl.Segmenter crashes; engine/run-tests.sh picks a node
that passes its probe. This fails when no node on the host does -- install one with full ICU.
Run: engine/run-tests.sh test_run_tests_node
"""
import shutil
import subprocess
import unittest

from tests._paths import REPO  # noqa: E402


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestNode(unittest.TestCase):
    def node(self, js):
        return subprocess.run([shutil.which("node"), "-e", js], capture_output=True, text=True, timeout=20)

    def test_korean_dates(self):
        out = self.node("console.log(new Intl.RelativeTimeFormat('ko',{numeric:'auto'}).format(-1,'day'))")
        self.assertEqual(out.stdout.strip(), "어제", "this node's Intl is not full ICU: %s" % shutil.which("node"))

    def test_grapheme_segmenting(self):
        out = self.node("console.log(Array.from(new Intl.Segmenter(undefined,{granularity:'grapheme'})"
                        ".segment('a\\u{1F44D}\\u{1F3FD}')).length)")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "2"), "Intl.Segmenter failed: %s" % shutil.which("node"))

    def test_the_runner_picks_it(self):
        self.assertIn("TEST_NODE_v1", (REPO / "engine" / "run-tests.sh").read_text(encoding="utf-8"))
