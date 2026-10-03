"""A page request never waits on a stale model list: the cached one comes back and one background refresh runs
(the team tab and the model picker took 4-7 s every five minutes while agy/grok listed their models)."""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from providers.adapter_base import cached_model_list


class ModelListCacheTest(unittest.TestCase):
    def test_first_call_fetches(self):
        cache = {"ts": 0.0, "models": []}
        self.assertEqual(cached_model_list(cache, lambda: ["a", "b"]), ["a", "b"])
        self.assertEqual(cache["models"], ["a", "b"])

    def test_fresh_cache_does_not_fetch(self):
        cache = {"ts": time.time(), "models": ["a"]}
        self.assertEqual(cached_model_list(cache, lambda: self.fail("fetched")), ["a"])

    def test_stale_cache_answers_now_and_refreshes_once_in_background(self):
        gate, calls = threading.Event(), []

        def slow():
            calls.append(1)
            gate.wait(5)
            return ["new"]
        cache = {"ts": 0.0, "models": ["old"]}
        t0 = time.time()
        self.assertEqual(cached_model_list(cache, slow), ["old"])
        self.assertEqual(cached_model_list(cache, slow), ["old"])
        self.assertLess(time.time() - t0, 1.0)
        gate.set()
        for _ in range(50):
            if cache["models"] == ["new"] and not cache.get("refreshing"):
                break
            time.sleep(0.02)
        self.assertEqual(cache["models"], ["new"])
        self.assertEqual(len(calls), 1)

    def test_failed_fetch_keeps_old_list(self):
        cache = {"ts": 0.0, "models": []}

        def boom():
            raise OSError("no cli")
        self.assertEqual(cached_model_list(cache, boom), [])
        cache["models"] = ["old"]
        cache["ts"] = 0.0
        cached_model_list(cache, boom)
        for _ in range(50):
            if not cache.get("refreshing"):
                break
            time.sleep(0.02)
        self.assertEqual(cache["models"], ["old"])


if __name__ == "__main__":
    unittest.main()
