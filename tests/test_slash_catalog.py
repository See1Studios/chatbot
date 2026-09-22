"""Slash popular pins are enabled workspace skills, not a hardcoded k-skill list.
Run: python3 -m unittest tests.test_slash_catalog  (from services/chatbot)
"""
import shutil
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(CODE))
import workspace_status as W  # noqa: E402


BANNED = (
    "korea-weather", "geeknews-search", "kopis-performance-search",
    "naver-news-search", "naver-shopping-search", "delivery-tracking",
    "daangn-used-goods-search", "lotto-results", "korean-stock-search",
    "express-bus-booking",
)


def _write_skill(root: Path, name: str, desc: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: %s\ndescription: %s\n---\n" % (name, desc), encoding="utf-8")


class PopularFromWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orig = W.WS_SKILLS_DIR
        W.WS_SKILLS_DIR = self.tmp

    def tearDown(self):
        W.WS_SKILLS_DIR = self.orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enabled_skills_are_the_pin_list_and_disabled_are_not(self):
        _write_skill(self.tmp, "nas-sphere", "Operate Sphere")
        _write_skill(self.tmp, "_korea-weather", "날씨")
        _write_skill(self.tmp, "anime-layer-animator", "A " + ("long " * 40) + "description")
        pops = W._popular_slash_skills()
        names = [p["skill"] for p in pops]
        self.assertEqual(names, ["anime-layer-animator", "nas-sphere"])
        self.assertTrue(all(p["template"] == "/skill %s " % p["skill"] for p in pops))
        self.assertLessEqual(len(pops[0]["desc"]), 80)
        self.assertTrue(pops[0]["desc"].endswith("…"))

    def test_empty_workspace_means_no_pins(self):
        self.assertEqual(W._popular_slash_skills(), [])


class StaticFallback(unittest.TestCase):
    def test_slash_js_does_not_hardcode_the_retired_k_skill_pins(self):
        text = (CODE / "static" / "slash.js").read_text(encoding="utf-8")
        for name in BANNED:
            self.assertNotIn(name, text, name)
        self.assertIn("if (Array.isArray(data.popular))", text)

    def test_server_does_not_hardcode_the_retired_k_skill_pins(self):
        text = (CODE / "server.py").read_text(encoding="utf-8")
        for name in BANNED:
            self.assertNotIn(name, text, name)
        self.assertIn("_popular_slash_skills", text)


class LiveWorkspace(unittest.TestCase):
    def test_this_deployment_pins_only_enabled_workspace_skills(self):
        enabled = {s["name"] for s in W._get_workspace_skills() if s.get("enabled")}
        pins = {p["skill"] for p in W._popular_slash_skills()}
        self.assertEqual(pins, enabled)
        self.assertTrue(pins.isdisjoint(BANNED))


if __name__ == "__main__":
    unittest.main()
