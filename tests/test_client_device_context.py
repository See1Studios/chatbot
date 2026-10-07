"""Tests for client device context binding (ticket #1).

Verifies that browser-side context (GPS lat/lon, timezone, device type) is:
1. Accepted by POST /api/sessions/<sid>/message and passed to session.send
2. Formatted concisely into prompt metadata without token bloat
3. Injected cleanly before user turn message
4. Present in static UI assets (button, CSS, getClientContext)
"""
import json
import unittest
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))

import session as S
from providers.adapters import get_adapter
from tests.test_conversation_sync import Base


class TestClientDeviceContext(Base):
    def test_format_client_context_helper(self):
        self.assertEqual(S.format_client_context(None), "")
        self.assertEqual(S.format_client_context({}), "")
        
        ctx_full = {
            "lat": 37.566532,
            "lon": 126.978012,
            "timezone": "Asia/Seoul",
            "is_mobile": False,
        }
        self.assertEqual(
            S.format_client_context(ctx_full),
            "[Client: location 37.5665, 126.9780, Asia/Seoul, desktop]"
        )

        ctx_mobile = {
            "lat": 35.1796,
            "lon": 129.0756,
            "timezone": "Asia/Seoul",
            "is_mobile": True,
        }
        self.assertEqual(
            S.format_client_context(ctx_mobile),
            "[Client: location 35.1796, 129.0756, Asia/Seoul, mobile]"
        )

        ctx_no_coords = {
            "timezone": "America/New_York",
            "is_mobile": False,
        }
        self.assertEqual(
            S.format_client_context(ctx_no_coords),
            "[Client: America/New_York, desktop]"
        )

    def test_format_battery(self):
        ctx = {"battery": 45, "charging": True}
        result = S.format_client_context(ctx)
        self.assertIn("battery 45% charging", result)

        ctx2 = {"battery": 80, "charging": False}
        result2 = S.format_client_context(ctx2)
        self.assertIn("battery 80%", result2)
        self.assertNotIn("charging", result2)

        # Battery without charging key
        ctx3 = {"battery": 20}
        result3 = S.format_client_context(ctx3)
        self.assertIn("battery 20%", result3)
        self.assertNotIn("charging", result3)

    def test_format_network_type(self):
        ctx = {"net_type": "wifi"}
        result = S.format_client_context(ctx)
        self.assertIn("network:wifi", result)

        ctx2 = {"net_type": "cellular"}
        result2 = S.format_client_context(ctx2)
        self.assertIn("network:cellular", result2)

    def test_format_online_fallback(self):
        # When net_type is absent, fall back to online boolean
        ctx = {"online": True}
        result = S.format_client_context(ctx)
        self.assertIn("online", result)

        ctx2 = {"online": False}
        result2 = S.format_client_context(ctx2)
        self.assertIn("offline", result2)

    def test_format_accuracy(self):
        ctx = {"lat": 37.5665, "lon": 126.9780, "accuracy": 25}
        result = S.format_client_context(ctx)
        self.assertIn("±25m", result)

        # Zero accuracy is omitted
        ctx2 = {"lat": 37.5665, "lon": 126.9780, "accuracy": 0}
        result2 = S.format_client_context(ctx2)
        self.assertNotIn("±", result2)

        # No accuracy key — no crash, no ±
        ctx3 = {"lat": 37.5665, "lon": 126.9780}
        result3 = S.format_client_context(ctx3)
        self.assertNotIn("±", result3)

    def test_format_visibility(self):
        ctx = {"visibility": "hidden"}
        result = S.format_client_context(ctx)
        self.assertIn("in the background", result)

        ctx2 = {"focused": False}
        result2 = S.format_client_context(ctx2)
        self.assertIn("tab not focused", result2)

        # visible + focused — neither tag appears
        ctx3 = {"visibility": "visible", "focused": True, "is_mobile": True}
        result3 = S.format_client_context(ctx3)
        self.assertNotIn("in the background", result3)
        self.assertNotIn("tab not focused", result3)

    def test_format_combined_sensors(self):
        ctx = {
            "lat": 37.5665, "lon": 126.9780, "accuracy": 50,
            "timezone": "Asia/Seoul", "is_mobile": True,
            "battery": 72, "charging": False,
            "net_type": "wifi",
            "focused": False,
        }
        result = S.format_client_context(ctx)
        self.assertEqual(
            result,
            "[Client: location 37.5665, 126.9780 ±50m, Asia/Seoul, "
            "mobile, battery 72%, network:wifi, tab not focused]"
        )

    def test_send_injects_client_context(self):
        s = self.make()
        s.adapter = get_adapter("grok")
        ctx = {"lat": 37.5665, "lon": 126.9780, "timezone": "Asia/Seoul", "is_mobile": False}
        s.send("지금 주변 맛집 알려줘", client_context=ctx)
        self.assertTrue(any("[Client: location 37.5665, 126.9780, Asia/Seoul, desktop]" in p for p in self.sent))
        self.assertTrue(any("지금 주변 맛집 알려줘" in p for p in self.sent))

    def test_ui_assets_contain_geo_elements(self):
        index_html = (CODE / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="geoBtn"', index_html)
        self.assertIn('class="geo-trigger-btn"', index_html)

        from tests.page_source import app_source
        app_js = app_source()   # app.js and its app-*.js parts (APP_SPLIT_v1)
        self.assertIn('getClientContext', app_js)
        self.assertIn('chatbot.geoEnabled', app_js)
        self.assertIn('client_context', app_js)

        from tests.page_source import css_source
        chat_css = css_source()
        self.assertIn('.geo-trigger-btn', chat_css)

    def test_ui_assets_contain_sensor_apis(self):
        device_js = (CODE / "static" / "app-device.js").read_text(encoding="utf-8")
        self.assertIn('visibilitychange', device_js)
        self.assertIn('focus', device_js)
        self.assertIn('Number.isFinite', device_js)

        from tests.page_source import app_source
        app_js = app_source()
        self.assertIn('getBattery', app_js)
        self.assertIn('navigator.connection', app_js)
        self.assertIn('visibilityState', app_js)
        self.assertIn('visibilitychange', app_js)
        self.assertIn('Number.isFinite', app_js)

    def test_format_resumed_seconds(self):
        ctx = {"resumed": 30}
        result = S.format_client_context(ctx)
        self.assertIn("back after 30s", result)

    def test_format_resumed_true(self):
        ctx = {"resumed": True}
        result = S.format_client_context(ctx)
        self.assertIn("back", result)
        self.assertNotIn("back after", result)

    def test_format_resumed_absent(self):
        ctx = {"is_mobile": True}
        result = S.format_client_context(ctx)
        self.assertNotIn("back", result)

    def test_format_resumed_bad_type(self):
        ctx = {"resumed": "not a number"}
        result = S.format_client_context(ctx)
        self.assertNotIn("back", result)
        self.assertTrue(result == "" or result.startswith("["))

    def test_format_visibility_unexpected_type(self):
        ctx = {"visibility": 42}
        result = S.format_client_context(ctx)
        self.assertNotIn("in the background", result)
        # should not crash, just skip
        self.assertTrue(result == "" or result.startswith("["))

        ctx2 = {"visibility": None}
        result2 = S.format_client_context(ctx2)
        self.assertNotIn("in the background", result2)

    def test_format_battery_invalid_and_clamping(self):
        # nan, inf, -inf, True, False, string should not crash and should be omitted
        for bad in (float("nan"), float("inf"), float("-inf"), True, False, "80", None, [], {}):
            res = S.format_client_context({"battery": bad})
            self.assertNotIn("battery ", res)
        # Clamping between 0 and 100
        self.assertIn("battery 100%", S.format_client_context({"battery": 150}))
        self.assertIn("battery 0%", S.format_client_context({"battery": -25}))
        self.assertIn("battery 50%", S.format_client_context({"battery": 50.4}))

    def test_format_accuracy_invalid(self):
        # nan, inf, -inf, True, False, string, <= 0 should omit ± tag without exception
        base = {"lat": 37.5665, "lon": 126.9780}
        for bad in (float("nan"), float("inf"), float("-inf"), True, False, "25", 0, -10, None):
            res = S.format_client_context({**base, "accuracy": bad})
            self.assertNotIn("±", res)
            self.assertIn("location 37.5665, 126.9780", res)

    def test_format_resumed_invalid(self):
        # nan, inf, -inf, string, <= 0 should omit return tag without exception
        for bad in (float("nan"), float("inf"), float("-inf"), "invalid", None, 0, -5):
            res = S.format_client_context({"resumed": bad})
            self.assertNotIn("back", res)

    def test_format_coords_invalid(self):
        # non-finite, bool, string in lat/lon should safely omit location
        for bad in (float("nan"), float("inf"), True, False, "37.5665"):
            res1 = S.format_client_context({"lat": bad, "lon": 126.9780})
            self.assertNotIn("location", res1)
            res2 = S.format_client_context({"lat": 37.5665, "lon": bad})
            self.assertNotIn("location", res2)


if __name__ == "__main__":
    unittest.main()
