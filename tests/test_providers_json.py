"""data/providers.json is the SSOT for HTTP OpenAI-dialect adapters.
Run: python3 -m unittest tests.test_providers_json  (from services/chatbot)
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from adapters import (
    AGENT_ADAPTERS,
    PROVIDERS_JSON,
    get_adapter,
    is_openrouter_free_model,
    load_openai_dialect_adapters,
)


class ProvidersJson(unittest.TestCase):
    def test_live_file_registers_omniroute_and_openrouter(self) -> None:
        raw = json.loads(PROVIDERS_JSON.read_text(encoding="utf-8"))
        specs = raw["providers"]
        self.assertEqual(specs["openrouter"]["free_only"], True)
        self.assertEqual(get_adapter("omniroute").base_url, specs["omniroute"]["base_url"].rstrip("/"))
        self.assertEqual(get_adapter("openrouter").base_url, specs["openrouter"]["base_url"].rstrip("/"))
        self.assertEqual(get_adapter("openrouter").default_model, specs["openrouter"]["default_model"])
        self.assertEqual(get_adapter("openrouter").api_key_env, specs["openrouter"]["api_key_env"])
        self.assertTrue(get_adapter("openrouter").free_only)
        self.assertFalse(get_adapter("omniroute").free_only)
        self.assertEqual(get_adapter("openrouter").meta["name"], "OpenRouter")
        self.assertEqual(get_adapter("omniroute").meta["theme"], "cyan")

    def test_missing_file_is_empty(self) -> None:
        self.assertEqual(load_openai_dialect_adapters(Path("/no/such/providers.json")), {})

    def test_cli_ids_cannot_be_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "providers.json"
            p.write_text(json.dumps({
                "providers": {
                    "agy": {
                        "type": "openai_dialect",
                        "base_url": "http://example.invalid/v1",
                        "api_key_env": "NOPE",
                        "default_model": "x",
                    }
                }
            }), encoding="utf-8")
            self.assertEqual(load_openai_dialect_adapters(p), {})
            self.assertEqual(AGENT_ADAPTERS["agy"].id, "agy")
            self.assertNotEqual(getattr(AGENT_ADAPTERS["agy"], "transport_kind", ""), "http")

    def test_free_only_drops_paid_default_and_curated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "providers.json"
            p.write_text(json.dumps({
                "providers": {
                    "openrouter": {
                        "type": "openai_dialect",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key_env": "OPENROUTER_API_KEY",
                        "free_only": True,
                        "default_model": "deepseek/deepseek-chat",
                        "curated_models": ["deepseek/deepseek-chat", "qwen/qwen3.8-27b:free"],
                    }
                }
            }), encoding="utf-8")
            loaded = load_openai_dialect_adapters(p)
            a = loaded["openrouter"]
            self.assertTrue(is_openrouter_free_model(a.default_model))
            self.assertEqual(a._curated_models, ["qwen/qwen3.8-27b:free"])
            self.assertEqual(a.coerce_openrouter_model("anthropic/claude-sonnet-5"), a.default_model)

    def test_unknown_type_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "providers.json"
            p.write_text(json.dumps({
                "providers": {
                    "bedrock": {"type": "anthropic_dialect", "base_url": "http://x", "api_key_env": "K"}
                }
            }), encoding="utf-8")
            self.assertEqual(load_openai_dialect_adapters(p), {})


if __name__ == "__main__":
    unittest.main()
