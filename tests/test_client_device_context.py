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
from adapters import get_adapter
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

        app_js = (CODE / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('getClientContext', app_js)
        self.assertIn('chatbot.geoEnabled', app_js)
        self.assertIn('client_context', app_js)

        chat_css = (CODE / "static" / "chat.css").read_text(encoding="utf-8")
        self.assertIn('.geo-trigger-btn', chat_css)


if __name__ == "__main__":
    unittest.main()
