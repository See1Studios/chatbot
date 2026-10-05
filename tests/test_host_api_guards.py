"""HTTP API guards (docs/plans/recursive-self-evolution.md §3 0-3 and 0-4):
same-origin defibrillate, CORS limited to this machine, the old /api/rules editor gone, loopback default bind.

The handler runs on an ephemeral port. Nothing here restarts anything: the defibrillate scheduler is
replaced by a recorder, and rule files live in a temp dir.
Run: python3 -m unittest tests.test_host_api_guards  (from services/chatbot)
"""
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from http.server import ThreadingHTTPServer
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import server  # noqa: E402
import platform_compat  # noqa: E402  (exclusive port on Windows, #409)


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.scheduled = []
        self._orig = {k: getattr(server, k) for k in ("_schedule_host_defibrillate", "ROOT")}
        server._schedule_host_defibrillate = lambda: self.scheduled.append(1)
        self.root = Path(tempfile.mkdtemp()).resolve()
        shutil.copy(str(CODE / "protected_paths.json"), str(self.root / "protected_paths.json"))
        self.ws = self.root / "data" / "workspace"
        self.ws.mkdir(parents=True)
        server.ROOT = self.root
        self.httpd = platform_compat.http_server(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.host = "127.0.0.1:%d" % self.port
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for k, v in self._orig.items():
            setattr(server, k, v)

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp, raw


class DefibrillateTest(ServerCase):
    def wait_scheduled(self):
        # the handler answers first and schedules afterwards
        for _ in range(100):
            if self.scheduled:
                break
            time.sleep(0.02)
        return self.scheduled

    def post(self, headers=None):
        return self.req("POST", "/api/host/defibrillate", {}, headers)

    def test_own_ui_may_trigger_it(self):
        resp, _ = self.post({"Origin": "http://" + self.host})
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.wait_scheduled(), [1])

    def test_fetch_metadata_same_origin_without_origin_header_is_accepted(self):
        resp, _ = self.post({"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.wait_scheduled(), [1])

    def test_plain_curl_is_refused(self):
        resp, raw = self.post()
        self.assertEqual(resp.status, 403)
        self.assertIn("same-origin", json.loads(raw)["error"])
        self.assertEqual(self.scheduled, [])

    def test_other_sites_and_other_ports_of_this_machine_are_refused(self):
        for origin in ("http://evil.example", "http://127.0.0.1", "http://127.0.0.1:1", "null",
                       "http://127.0.0.1:%d.evil.example" % self.port):
            resp, _ = self.post({"Origin": origin})
            self.assertEqual(resp.status, 403, origin)
        resp, _ = self.post({"Origin": "http://evil.example", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(resp.status, 403)
        resp, _ = self.post({"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(resp.status, 403)
        time.sleep(0.3)  # long enough for a wrongly accepted request to have scheduled
        self.assertEqual(self.scheduled, [])


class PatchTest(ServerCase):
    """PATCH is answered for the group-room panel (501 before), through the same same-origin gate as POST."""

    def patch(self, path, body, headers=None):
        return self.req("PATCH", path, body, headers)

    def test_a_room_is_renamed_from_the_own_page(self):
        import room_chat
        seen = []
        def update(rid, **kw):
            seen.append((rid, kw["name"]))
            return {"id": rid, "name": kw["name"]}
        with mock.patch.object(room_chat, "room", lambda rid: {"id": rid} if rid == "room_x" else None), \
                mock.patch.object(room_chat, "update", update):
            resp, raw = self.patch("/api/rooms/room_x", {"name": "desk"}, {"Origin": "http://" + self.host})
        self.assertEqual(resp.status, 200, raw)
        self.assertEqual(json.loads(raw)["room"]["name"], "desk")
        self.assertEqual(seen, [("room_x", "desk")])

    def test_other_origins_are_refused_before_anything_runs(self):
        for headers in ({}, {"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            resp, raw = self.patch("/api/rooms/room_x", {"name": "desk"}, headers)
            self.assertEqual(resp.status, 403, headers)
            self.assertIn("same-origin", json.loads(raw)["error"])

    def test_an_unknown_room_is_404_and_another_api_is_not_patchable(self):
        own = {"Origin": "http://" + self.host}
        resp, _ = self.patch("/api/rooms/room_nope", {"name": "x"}, own)
        self.assertEqual(resp.status, 404)
        resp, _ = self.patch("/api/sessions/s1", {"name": "x"}, own)
        self.assertEqual(resp.status, 404)

    def test_the_cors_preflight_lists_patch(self):
        resp, _ = self.req("OPTIONS", "/api/rooms/room_x", headers={"Origin": "http://" + self.host})
        self.assertIn("PATCH", resp.getheader("Access-Control-Allow-Methods") or "")


class AccountProfilesTest(ServerCase):
    """One-click agy login switch (PROFILE_SWITCH_v1): the list is readable, the switch is a same-origin POST."""

    def test_the_profile_list_carries_each_accounts_last_usage(self):
        import route_accounts
        prof = [{"index": 1, "email": "a@x.io", "active": True, "saved_at": 1.0, "source": "s"}]
        with mock.patch.object(route_accounts.accounts, "list_profiles", lambda p="agy": prof), \
                mock.patch.object(route_accounts.accounts, "usage_snapshots",
                                  lambda: {"a@x.io": {"rows": [], "checked_at": 5.0}}):
            resp, raw = self.req("GET", "/api/accounts/profiles")
        self.assertEqual(resp.status, 200, raw)
        self.assertEqual(json.loads(raw)["profiles"][0]["usage"]["checked_at"], 5.0)

    def test_switch_runs_for_the_own_page_only(self):
        import route_accounts
        calls = []
        def fake(target, provider="agy", owned=None, recycle=None):
            calls.append(target)
            return {"ok": True, "email": target}
        with mock.patch.object(route_accounts.accounts, "switch_profile", fake), \
                mock.patch.object(route_accounts, "owned_agent_procs", lambda: {}):
            resp, raw = self.req("POST", "/api/accounts/switch", {"target": "b@x.io"}, {"Origin": "http://" + self.host})
            self.assertEqual((resp.status, json.loads(raw)["email"]), (200, "b@x.io"))
            resp, _ = self.req("POST", "/api/accounts/switch", {"target": "c@x.io"}, {"Origin": "http://evil.example"})
            self.assertEqual(resp.status, 403)
            resp, _ = self.req("POST", "/api/accounts/switch", {}, {"Origin": "http://" + self.host})
            self.assertEqual(resp.status, 400)
        self.assertEqual(calls, ["b@x.io"])


class CorsTest(ServerCase):
    def acao(self, method="GET", origin=None, path="/healthz"):
        headers = {"Origin": origin} if origin else {}
        resp, _ = self.req(method, path, headers=headers)
        return resp

    def test_no_wildcard_ever(self):
        for origin in (None, "http://evil.example", "http://127.0.0.1:5000"):
            resp = self.acao(origin=origin)
            self.assertNotEqual(resp.getheader("Access-Control-Allow-Origin"), "*")

    def test_same_machine_page_such_as_the_hub_may_read(self):
        resp = self.acao(origin="http://127.0.0.1:5000")
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), "http://127.0.0.1:5000")
        self.assertEqual(resp.getheader("Vary"), "Origin")

    def test_other_sites_get_no_cors_headers(self):
        for origin in ("http://evil.example", "null"):
            resp = self.acao(origin=origin)
            self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"), origin)
            self.assertIsNone(resp.getheader("Access-Control-Allow-Methods"), origin)

    def test_requests_without_origin_are_unchanged(self):
        resp = self.acao()
        self.assertEqual(resp.status, 200)
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))

    def test_preflight_follows_the_same_rule(self):
        ok = self.acao(method="OPTIONS", origin="http://127.0.0.1:5000")
        self.assertEqual(ok.status, 204)
        self.assertEqual(ok.getheader("Access-Control-Allow-Origin"), "http://127.0.0.1:5000")
        self.assertIn("PUT", ok.getheader("Access-Control-Allow-Methods"))
        bad = self.acao(method="OPTIONS", origin="http://evil.example")
        self.assertEqual(bad.status, 204)
        self.assertIsNone(bad.getheader("Access-Control-Allow-Origin"))


class RulesRouteIsGoneTest(ServerCase):
    """ORPHANS_v1: the old /api/rules editor had no same-origin check and the page no longer used it; instruction
    files are read and edited through /api/instructions only."""

    def test_rules_route_answers_404(self):
        (self.ws / "PROJECT.md").write_text("ORIGINAL", encoding="utf-8")
        for method, body in (("GET", None), ("PUT", {"content": "NEW"})):
            resp, _ = self.req(method, "/api/rules/PROJECT.md", body)
            self.assertEqual(resp.status, 404, method)
        self.assertEqual((self.ws / "PROJECT.md").read_text(encoding="utf-8"), "ORIGINAL")


class DefaultBindTest(unittest.TestCase):
    def test_bare_start_is_loopback_only_and_ctl_opts_the_lan_in(self):
        tmp = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if k not in ("AGY_CHAT_HOST", "CHATBOT_HOST")}  # legacy name still honoured
        env.update(AGY_CHAT_ROOT=str(CODE), AGY_CHAT_DATA=tmp)
        out = subprocess.check_output([sys.executable, "-c", "import host_config; print(host_config.HOST)"],
                                      cwd=str(CODE), env=env).decode().strip()
        self.assertEqual(out, "127.0.0.1")
        env["AGY_CHAT_HOST"] = "0.0.0.0"
        out = subprocess.check_output([sys.executable, "-c", "import host_config; print(host_config.HOST)"],
                                      cwd=str(CODE), env=env).decode().strip()
        self.assertEqual(out, "0.0.0.0")
        # The production start path must keep opening the LAN explicitly, or the default flip closes it.
        ctl = (CODE / "chatbot-ctl.sh").read_text(encoding="utf-8")
        self.assertIn("export CHATBOT_HOST=0.0.0.0", ctl)


if __name__ == "__main__":
    unittest.main()
