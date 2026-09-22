#!/usr/bin/env python3
"""Host-module smoke. No network, no spawn.

  python3 tests/smoke.py
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import AGENT_ADAPTERS, DEFAULT_PROVIDER, get_adapter, is_openrouter_free_model
from session import _billed_tokens, _current_context_tokens, _turn_billed
from tool_format import _format_tool_call


class Adapters(unittest.TestCase):
    def test_registered_providers(self) -> None:
        self.assertEqual(
            sorted(AGENT_ADAPTERS),
            ["agy", "claude", "codex", "grok", "omniroute", "openrouter"],
        )
        self.assertEqual(get_adapter("agy").id, "agy")
        self.assertEqual(get_adapter("omniroute").id, "omniroute")
        self.assertEqual(get_adapter("openrouter").id, "openrouter")
        self.assertEqual(get_adapter("nope").id, DEFAULT_PROVIDER)

    def test_openrouter_is_free_only(self) -> None:
        self.assertTrue(is_openrouter_free_model("openrouter/free"))
        self.assertTrue(is_openrouter_free_model("qwen/qwen3.8-27b:free"))
        self.assertFalse(is_openrouter_free_model("deepseek/deepseek-chat"))
        self.assertFalse(is_openrouter_free_model("openrouter/auto"))
        self.assertFalse(is_openrouter_free_model(""))
        a = get_adapter("openrouter")
        self.assertTrue(is_openrouter_free_model(a.default_model))
        for m in a._curated_models:
            self.assertTrue(is_openrouter_free_model(m), m)
        self.assertEqual(a.coerce_openrouter_model("deepseek/deepseek-chat"), a.default_model)
        self.assertEqual(a.coerce_openrouter_model("z-ai/glm-5.2:free"), "z-ai/glm-5.2:free")
        self.assertEqual(a.coerce_openrouter_model(""), a.default_model)

    def test_openrouter_known_models_drop_paid(self) -> None:
        a = get_adapter("openrouter")
        orig_curated = list(a._curated_models)
        orig_cache = dict(a._models_meta_cache)
        try:
            a._curated_models = ["deepseek/deepseek-chat", "qwen/qwen3.8-27b:free"]
            a._models_meta_cache = {
                "ts": 1e12,
                "data": {
                    "paid/model": {},
                    "bar:free": {},
                    "openrouter/free": {},
                },
            }
            models = a.known_models()
            self.assertNotIn("deepseek/deepseek-chat", models)
            self.assertNotIn("paid/model", models)
            self.assertIn("qwen/qwen3.8-27b:free", models)
            self.assertIn("bar:free", models)
            self.assertIn("openrouter/free", models)
        finally:
            a._curated_models = orig_curated
            a._models_meta_cache = orig_cache


class ToolFormat(unittest.TestCase):
    def test_run_command(self) -> None:
        s = _format_tool_call("run_command", {"command": "ls"})
        self.assertIn("ls", s)


class Tokens(unittest.TestCase):
    def test_occupancy_is_last_input_not_sum_or_cache(self) -> None:
        hist = [
            {"role": "assistant", "usage": {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050}},
            {"role": "user", "text": "x"},
            {
                "role": "assistant",
                "usage": {
                    "input_tokens": 2000,
                    "output_tokens": 10,
                    "total_tokens": 2010,
                    "cache_read_tokens": 9_000_000,
                },
            },
        ]
        self.assertEqual(_current_context_tokens(hist), 2000)
        self.assertEqual(_billed_tokens(hist), 3060)
        self.assertEqual(_turn_billed(hist[-1]["usage"]), 2010)

    def test_occupancy_skips_empty_usage(self) -> None:
        hist = [
            {"role": "assistant", "usage": {"input_tokens": 14000, "total_tokens": 14010}},
            {"role": "assistant", "usage": {}},
        ]
        self.assertEqual(_current_context_tokens(hist), 14000)


class Guard(unittest.TestCase):
    def test_rlock(self) -> None:
        r = subprocess.run(
            ["bash", str(ROOT / "chatbot-ctl.sh"), "guard"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("guard_rlock OK", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
