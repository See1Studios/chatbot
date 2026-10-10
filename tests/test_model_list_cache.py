"""A page request never waits on a stale model list: the cached one comes back and one background refresh runs
(the team tab and the model picker took 4-7 s every five minutes while agy/grok listed their models)."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

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


    def test_a_warming_list_never_makes_a_request_wait(self):
        # #861: the server warms the lists at start; a request meanwhile gets the caller's fallback, not the CLI
        from providers.adapter_base import warm_model_list
        gate, cache = threading.Event(), {}
        warm_model_list(cache, lambda: (gate.wait(5), ["x"])[1])
        t0 = time.time()
        self.assertEqual(cached_model_list(cache, lambda: self.fail("fetched twice")), [])
        self.assertLess(time.time() - t0, 1.0)
        gate.set()
        for _ in range(50):
            if cache.get("models"):
                break
            time.sleep(0.05)
        self.assertEqual(cached_model_list(cache, lambda: self.fail("fetched")), ["x"])
        warm_model_list(cache, lambda: self.fail("warmed again"))

    def test_the_menu_does_not_wait_on_a_cold_cli(self):
        from providers.adapter_base import menu_model_list
        gate, calls = threading.Event(), []

        def slow():
            calls.append(1)
            gate.wait(5)
            return ["live"]

        cache = {"ts": 0.0, "models": []}
        t0 = time.monotonic()
        self.assertEqual(menu_model_list(cache, slow, ["fallback"]), ["fallback"])
        self.assertLess(time.monotonic() - t0, 0.5)
        for _ in range(50):
            if calls:
                break
            time.sleep(0.02)
        t0 = time.monotonic()
        self.assertEqual(menu_model_list(cache, slow, ["fallback"]), ["fallback"])
        self.assertLess(time.monotonic() - t0, 0.5)
        self.assertEqual(len(calls), 1)
        gate.set()
        for _ in range(50):
            if cache.get("models") == ["live"] and not cache.get("refreshing"):
                break
            time.sleep(0.02)
        self.assertEqual(menu_model_list(cache, lambda: self.fail("fetched"), ["fallback"]), ["live"])

    def test_a_failed_menu_fetch_is_not_retried_at_once(self):
        from providers.adapter_base import menu_model_list
        calls = []

        def boom():
            calls.append(1)
            raise OSError("down")

        cache = {"ts": 0.0, "models": []}
        self.assertEqual(menu_model_list(cache, boom, ["fb"]), ["fb"])
        for _ in range(50):
            if not cache.get("refreshing"):
                break
            time.sleep(0.02)
        self.assertEqual(menu_model_list(cache, boom, ["fb"]), ["fb"])
        self.assertEqual(calls, [1])

    def test_the_provider_menu_asks_each_adapter_once(self):
        import server

        class Adapter:
            meta = {}

            def available(self):
                return True

            def menu_models(self):
                self.calls = getattr(self, "calls", 0) + 1
                if self.calls > 1:
                    raise AssertionError("menu_models called twice")
                return ["m1", "m2"]

        adapter = Adapter()
        req = _Req()
        with mock.patch.object(server, "AGENT_ADAPTERS", {"x": adapter}):
            server._providers(req)
        body = req.json_body
        self.assertEqual(body["providers"][0]["models"], ["m1", "m2"])
        self.assertEqual(body["providers"][0]["default_model"], "m1")
        self.assertEqual(adapter.calls, 1)


class _Req:
    def json(self, obj, code=200):
        self.json_body = obj
        return self


if __name__ == "__main__":
    unittest.main()
