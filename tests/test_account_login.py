"""Unit tests for account_login (mocked CLI / no real login)."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers import account_login  # noqa: E402
from providers import accounts  # noqa: E402

# Isolation without touching the environment (split/A): this module used to set HOME, the data folder and the CLI paths
# in os.environ at import, which fixed host_config for every module run after it in the same process (git lost its
# user, the code root moved). Now only what the login code reads is swapped, and only while this module runs: the
# credential paths under a temporary home, the login CLIs replaced by /bin/echo, short waits.
_TMP = Path(tempfile.mkdtemp(prefix="chatbot-login-test-"))
_AGY = _TMP / ".gemini" / "antigravity-cli"
_PATCHES = [mock.patch.object(accounts, k, v) for k, v in {
    "HOME": _TMP, "AGY_DIR": _AGY, "AGY_TOKEN": _AGY / "antigravity-oauth-token", "AGY_LOG_DIR": _AGY / "log",
    "AGY_PROFILES_DIR": _AGY / "tokens", "CODEX_AUTH": _TMP / ".codex" / "auth.json",
    "GROK_AUTH": _TMP / ".grok" / "auth.json", "STATE_FILE": _TMP / "chatbot" / "data" / "account_state.json",
}.items()] + [mock.patch.object(account_login, k, v) for k, v in {
    "AGY": "/bin/echo", "CLAUDE_BIN": "/bin/echo", "GROK_BIN": "/bin/echo", "CODEX_BIN": "/bin/echo",
    "BOOTSTRAP_WAIT_SEC": 0.2, "LOGIN_TIMEOUT_SEC": 30,
}.items()]


def setUpModule():
    for p in _PATCHES:
        p.start()


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()


class AccountLoginTest(unittest.TestCase):
    def tearDown(self):
        account_login.idle_all()

    def test_only_a_new_login_counts_as_success(self):
        # LOGIN_BASELINE_v1: switching accounts without logging out first used to "succeed" on the old login at once
        ch = account_login._changed
        A = {"ok": True, "email": "a@x", "fp": "1"}
        self.assertTrue(ch({"ok": False}, A), "logged out before: any login is new")
        self.assertTrue(ch(A, {"ok": True, "email": "b@x", "fp": "1"}))
        self.assertFalse(ch(A, dict(A)), "the login that was already there")
        self.assertTrue(ch(A, {"ok": True, "email": "a@x", "fp": "2"}), "same account, logged in again")
        self.assertIsNone(ch({"ok": True, "email": "a@x", "fp": None}, {"ok": True, "email": "a@x", "fp": None}))
        self.assertFalse(ch(A, {"ok": False}))

    def test_an_unknown_same_account_login_counts_only_once_the_cli_exits(self):
        sess = account_login._Session(login_id="x", provider="grok", mode="device_code",
                                      baseline={"ok": True, "email": "a@x", "fp": None})
        with mock.patch.object(accounts, "grok_account", return_value={"ok": True, "email": "a@x"}):
            self.assertFalse(account_login._account_ok("grok", sess))
            self.assertTrue(account_login._account_ok("grok", sess, exited=True))

    def test_a_code_that_logs_in_also_ends_the_login_cli(self):
        # the agy TUI never exits by itself; after complete() succeeded nobody ended it (pid left on a pty)
        proc = mock.Mock()
        proc.poll.return_value = None
        sess = account_login._Session(login_id="x", provider="agy", mode="oauth_paste",
                                      expires_at=time.time() + 30, proc=proc, master_fd=None)
        r, w = os.pipe()
        sess.master_fd = w
        account_login._sessions["agy"] = sess
        ended = []
        with mock.patch.object(account_login, "_account_ok", return_value=True), \
                mock.patch.object(account_login, "_kill_proc", side_effect=lambda s: ended.append(s)):
            out = account_login.complete("agy", "4/0Acode")
            self.assertEqual(out.get("state"), "succeeded")
            for _ in range(30):
                if ended:
                    break
                time.sleep(0.1)
        os.close(r)
        os.close(w)
        self.assertEqual(ended, [sess])
        account_login._sessions.pop("agy", None)

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
        self.assertEqual(account_login.MODE_BY_PROVIDER["claude"], "oauth_paste")
        self.assertEqual(account_login.MODE_BY_PROVIDER["grok"], "device_code")
        self.assertEqual(account_login.MODE_BY_PROVIDER["codex"], "device_code")

    def test_parse_device_output(self):
        sess = account_login._Session(
            login_id="x", provider="grok", mode="device_code"
        )
        sess.output = (
            "Visit https://accounts.x.ai/device and enter code ABCD-EFGH\n"
        )
        account_login._parse_output(sess)
        self.assertEqual(sess.user_code, "ABCD-EFGH")
        self.assertIn("accounts.x.ai", sess.verification_uri or sess.authorize_url or "")


    def test_parse_codex_ansi_device_output(self):
        """Codex CSI-colors the device URL and code; strip before regex."""
        sess = account_login._Session(
            login_id="x", provider="codex", mode="device_code"
        )
        esc = chr(27)
        sess.output = (
            "Follow these steps to sign in with ChatGPT using device code authorization:\n"
            f"1. Open this link\n   {esc}[94mhttps://auth.openai.com/codex/device{esc}[0m\n"
            f"2. Enter this one-time code\n   {esc}[94mABCD-EFGHI{esc}[0m\n"
        )
        account_login._parse_output(sess)
        self.assertEqual(sess.authorize_url, "https://auth.openai.com/codex/device")
        self.assertEqual(sess.verification_uri, "https://auth.openai.com/codex/device")
        self.assertEqual(sess.user_code, "ABCD-EFGHI")

    def test_parse_agy_url(self):
        sess = account_login._Session(
            login_id="x", provider="agy", mode="oauth_paste"
        )
        sess.output = "Open https://accounts.google.com/o/oauth2/auth?client=1 to continue\n"
        account_login._parse_output(sess)
        self.assertIn("accounts.google.com", sess.authorize_url or "")


    def test_parse_claude_bel_url(self):
        """Claude may emit URL + BEL + URL duplicate; keep first clean URL."""
        sess = account_login._Session(
            login_id="x", provider="claude", mode="oauth_paste"
        )
        u = "https://claude.com/cai/oauth/authorize?code=true&state=ABC"
        sess.output = "Open " + u + chr(7) + u + chr(27) + "\n"
        account_login._parse_output(sess)
        self.assertEqual(sess.authorize_url, u)

    def test_parse_claude_port(self):
        sess = account_login._Session(
            login_id="x", provider="claude", mode="oauth_callback",
        )
        sess.output = (
            "Browser: https://claude.ai/oauth/authorize?x=1\n"
            "Callback at http://127.0.0.1:54321/callback\n"
        )
        account_login._parse_output(sess)
        self.assertIn("claude.ai/oauth", sess.authorize_url or "")
        self.assertEqual(sess.callback_port, 54321)
        self.assertIn("54321", sess.public()["tip"])   # I18N_v1: the tip is its own field, by key

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
        # restart cancels previous
        r2 = account_login.start("codex")
        self.assertEqual(r2.get("state"), "pending")
        self.assertNotEqual(r.get("login_id"), r2.get("login_id"))


if __name__ == "__main__":
    unittest.main()
