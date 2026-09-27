"""A failed /models fetch is remembered for a minute (providers/adapter_openai.py::_get_models_meta), so an unreachable
endpoint does not cost its 10 s timeout on every /api/providers call (30 s seen live on 2026-09-27).
Run: python3 -m unittest tests.test_models_meta_cache  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import adapter_openai  # noqa: E402
from providers.adapters import AGENT_ADAPTERS  # noqa: E402


class ModelsMetaCache(unittest.TestCase):
    def setUp(self):
        self.a = next(a for a in AGENT_ADAPTERS.values() if hasattr(a, "_get_models_meta"))
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


if __name__ == "__main__":
    unittest.main()
