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
            "[클라이언트 환경: 위치 37.5665, 126.9780, Asia/Seoul, 데스크톱]"
        )

        ctx_mobile = {
            "lat": 35.1796,
            "lon": 129.0756,
            "timezone": "Asia/Seoul",
            "is_mobile": True,
        }
        self.assertEqual(
            S.format_client_context(ctx_mobile),
            "[클라이언트 환경: 위치 35.1796, 129.0756, Asia/Seoul, 모바일]"
        )

        ctx_no_coords = {
            "timezone": "America/New_York",
            "is_mobile": False,
        }
        self.assertEqual(
            S.format_client_context(ctx_no_coords),
            "[클라이언트 환경: America/New_York, 데스크톱]"
        )

    def test_format_battery(self):
        ctx = {"battery": 45, "charging": True}
        result = S.format_client_context(ctx)
        self.assertIn("배터리45%충전중", result)

        ctx2 = {"battery": 80, "charging": False}
        result2 = S.format_client_context(ctx2)
        self.assertIn("배터리80%", result2)
        self.assertNotIn("충전중", result2)

        # Battery without charging key
        ctx3 = {"battery": 20}
        result3 = S.format_client_context(ctx3)
        self.assertIn("배터리20%", result3)
        self.assertNotIn("충전중", result3)

    def test_format_network_type(self):
        ctx = {"net_type": "wifi"}
        result = S.format_client_context(ctx)
        self.assertIn("네트워크:wifi", result)

        ctx2 = {"net_type": "cellular"}
        result2 = S.format_client_context(ctx2)
        self.assertIn("네트워크:cellular", result2)

    def test_format_online_fallback(self):
        # When net_type is absent, fall back to online boolean
        ctx = {"online": True}
        result = S.format_client_context(ctx)
        self.assertIn("온라인", result)

        ctx2 = {"online": False}
        result2 = S.format_client_context(ctx2)
        self.assertIn("오프라인", result2)

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
        self.assertIn("백그라운드", result)

        ctx2 = {"focused": False}
        result2 = S.format_client_context(ctx2)
        self.assertIn("비활성탭", result2)

        # visible + focused — neither tag appears
        ctx3 = {"visibility": "visible", "focused": True, "is_mobile": True}
        result3 = S.format_client_context(ctx3)
        self.assertNotIn("백그라운드", result3)
        self.assertNotIn("비활성탭", result3)

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
            "[클라이언트 환경: 위치 37.5665, 126.9780 ±50m, Asia/Seoul, "
            "모바일, 배터리72%, 네트워크:wifi, 비활성탭]"
        )

    def test_send_injects_client_context(self):
        s = self.make()
        s.adapter = get_adapter("grok")
        ctx = {"lat": 37.5665, "lon": 126.9780, "timezone": "Asia/Seoul", "is_mobile": False}
        s.send("지금 주변 맛집 알려줘", client_context=ctx)
        self.assertTrue(any("[클라이언트 환경: 위치 37.5665, 126.9780, Asia/Seoul, 데스크톱]" in p for p in self.sent))
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
        from tests.page_source import app_source
        app_js = app_source()
        self.assertIn('getBattery', app_js)
        self.assertIn('navigator.connection', app_js)
        self.assertIn('visibilityState', app_js)


if __name__ == "__main__":
    unittest.main()
