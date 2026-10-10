"""A failed /models fetch is remembered for a minute (providers/adapter_openai.py::_get_models_meta), so an unreachable
endpoint does not cost its 10 s timeout on every /api/providers call (30 s seen live on 2026-09-27).
Run: engine/run-tests.sh test_models_meta_cache
"""
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
from providers import adapter_openai  # noqa: E402
from providers.adapters import load_openai_dialect_adapters  # noqa: E402
from tests._paths import REPO  # noqa: E402

# uds/F: an install's providers.json is user data in ~/.pe; the adapters come from the shipped example
EXAMPLE = REPO / "templates" / "providers.example.json"


class ModelsMetaCache(unittest.TestCase):
    def setUp(self):
        self.a = next(a for a in load_openai_dialect_adapters(EXAMPLE).values() if hasattr(a, "_get_models_meta"))
        self.saved = dict(self.a._models_meta_cache)
        self.a._models_meta_cache.clear()
        self.a._models_meta_cache.update({"ts": 0.0, "data": {}})

    def tearDown(self):
        self.a._models_meta_cache.clear()
        self.a._models_meta_cache.update(self.saved)

    def test_a_failure_is_not_retried_within_a_minute(self):
        with mock.patch.object(adapter_openai, "urlopen", side_effect=OSError("timed out")) as op, \
                mock.patch.object(adapter_openai.time, "time", side_effect=[1000.0, 1030.0, 1061.0]):
            self.assertEqual(self.a._get_models_meta(), {})
            self.assertEqual(self.a._get_models_meta(), {})   # 30 s later: remembered, no second fetch
            self.assertEqual(op.call_count, 1)
            self.a._get_models_meta()                        # 61 s later: tries again
            self.assertEqual(op.call_count, 2)

    def test_the_menu_does_not_wait_on_a_cold_catalog(self):
        from providers.adapter_openai import OpenAIDialectAdapter
        gate = threading.Event()
        body = json.dumps({"data": [
            {"id": "stealth/space-bunny-alpha", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "z-ai/glm-5.2:free", "pricing": {"prompt": "0", "completion": "0"}},
        ]}).encode()

        class Resp:
            def read(self):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def slow_open(*args, **kwargs):
            gate.wait(5)
            return Resp()

        a = OpenAIDialectAdapter(
            id="or", base_url="http://x/v1", api_key_env="NONE", default_model="z-ai/glm-5.2:free",
            curated_models=["z-ai/glm-5.2:free", "stealth/space-bunny-alpha"], free_only=True)
        with mock.patch.object(adapter_openai, "urlopen", slow_open):
            t0 = time.monotonic()
            models = a.menu_models()
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertEqual(models, ["z-ai/glm-5.2:free"])
            self.assertNotIn("stealth/space-bunny-alpha", models)
            gate.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not a._models_meta_cache.get("data"):
                time.sleep(0.02)
        self.assertIn("stealth/space-bunny-alpha", a.known_models())
        self.assertIn("stealth/space-bunny-alpha", a.menu_models())


if __name__ == "__main__":
    unittest.main()
