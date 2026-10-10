import json
import tempfile
import unittest
from pathlib import Path

import host_config


class ConfigStoreTest(unittest.TestCase):
    def test_read_empty_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self.assertEqual(host_config.read_config(d), {})
            self.assertIsNone(host_config.get_config_section("team", root=d))

    def test_legacy_fallback_when_absent_in_config(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            legacy = d / "team.json"
            legacy.write_text(json.dumps({"default": "char_1", "members": {}}), encoding="utf-8")
            res = host_config.get_config_section("team", legacy_path=legacy, root=d)
            self.assertEqual(res, {"default": "char_1", "members": {}})

    def test_config_json_overrides_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            legacy = d / "team.json"
            legacy.write_text(json.dumps({"default": "old"}), encoding="utf-8")
            host_config.set_config_section("team", {"default": "new"}, root=d)
            res = host_config.get_config_section("team", legacy_path=legacy, root=d)
            self.assertEqual(res, {"default": "new"})
            # Check version is 1
            cfg = host_config.read_config(d)
            self.assertEqual(cfg.get("version"), 1)
            self.assertEqual(cfg.get("team"), {"default": "new"})

    def test_multiple_sections_merge_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            host_config.set_config_section("team", {"default": "char_a"}, root=d)
            host_config.set_config_section("events", {"auto": ["work.phase"]}, root=d)
            host_config.set_config_section("items", {"items": []}, root=d)
            cfg = host_config.read_config(d)
            self.assertIn("team", cfg)
            self.assertIn("events", cfg)
            self.assertIn("items", cfg)
            self.assertEqual(cfg["team"]["default"], "char_a")


if __name__ == "__main__":
    unittest.main()
