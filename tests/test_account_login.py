"""Unit tests for account_login (mocked CLI / no real login)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chatbot-login-test-")
os.environ["HOME"] = _TMP
os.environ["AGY_CHAT_ROOT"] = str(Path(_TMP) / "chatbot")
os.environ["AGY_CHAT_DATA"] = str(Path(_TMP) / "chatbot" / "data")
os.environ["AGY_BIN"] = "/bin/echo"
os.environ["AGY_CLAUDE_BIN"] = "/bin/echo"
os.environ["AGY_GROK_BIN"] = "/bin/echo"
os.environ["AGY_CODEX_BIN"] = "/bin/echo"
os.environ["CHATBOT_LOGIN_BOOTSTRAP_SEC"] = "0.2"
os.environ["CHATBOT_LOGIN_TIMEOUT_SEC"] = "30"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import account_login  # noqa: E402
import accounts  # noqa: E402


class AccountLoginTest(unittest.TestCase):
    def tearDown(self):
        account_login.idle_all()

    def test_start_unknown_provider(self):
        r = account_login.start("nope")
        self.assertFalse(r.get("ok"))
        self.assertIn("unknown provider", r.get("error", ""))

    def test_status_idle(self):
        r = account_login.status("agy")
        self.assertTrue(r.get("ok"))
        self.assertEqual(r.get("state"), "idle")

    def test_status_unknown_provider(self):
        r = account_login.status("nope")
        self.assertFalse(r.get("ok"))
        self.assertEqual(r.get("state"), "idle")

    def test_cancel_idle(self):
        r = account_login.cancel("claude")
        self.assertTrue(r.get("ok"))
        self.assertIn(r.get("state"), ("idle", "cancelled"))

    def test_modes(self):
        self.assertEqual(account_login.MODE_BY_PROVIDER["agy"], "oauth_paste")
        self.assertEqual(account_login.MODE_BY_PROVIDER["claude"], "oauth_callback")
        self.assertEqual(account_login.MODE_BY_PROVIDER["grok"], "device_code")
        self.assertEqual(account_login.MODE_BY_PROVIDER["codex"], "device_code")

    def test_parse_device_output(self):
        sess = account_login._Session(
            login_id="x", provider="grok", mode="device_code", message_ko=""
        )
        sess.output = (
            "Visit https://accounts.x.ai/device and enter code ABCD-EFGH\n"
        )
        account_login._parse_output(sess)
        self.assertEqual(sess.user_code, "ABCD-EFGH")
        self.assertIn("accounts.x.ai", sess.verification_uri or sess.authorize_url or "")

    def test_parse_agy_url(self):
        sess = account_login._Session(
            login_id="x", provider="agy", mode="oauth_paste", message_ko=""
        )
        sess.output = "Open https://accounts.google.com/o/oauth2/auth?client=1 to continue\n"
        account_login._parse_output(sess)
        self.assertIn("accounts.google.com", sess.authorize_url or "")

    def test_parse_claude_port(self):
        sess = account_login._Session(
            login_id="x", provider="claude", mode="oauth_callback",
            message_ko=account_login._MESSAGE_KO["claude"],
        )
        sess.output = (
            "Browser: https://claude.ai/oauth/authorize?x=1\n"
            "Callback at http://127.0.0.1:54321/callback\n"
        )
        account_login._parse_output(sess)
        self.assertIn("claude.ai/oauth", sess.authorize_url or "")
        self.assertEqual(sess.callback_port, 54321)
        self.assertIn("54321", sess.message_ko)

    @mock.patch.object(account_login, "_spawn")
    def test_start_returns_pending_shell(self, spawn):
        def fake_spawn(sess):
            sess.authorize_url = "https://example.test/auth"
            sess.state = "pending"
        spawn.side_effect = fake_spawn
        r = account_login.start("codex")
        self.assertTrue(r.get("ok"))
        self.assertEqual(r.get("mode"), "device_code")
        self.assertEqual(r.get("state"), "pending")
        self.assertEqual(r.get("authorize_url"), "https://example.test/auth")
        r2 = account_login.start("codex")
        self.assertEqual(r2.get("state"), "pending")
        self.assertNotEqual(r.get("login_id"), r2.get("login_id"))


if __name__ == "__main__":
    unittest.main()
