"""HTTP API guards (docs/plans/recursive-self-evolution.md §3 0-3 and the /api/rules half of 0-4):
same-origin defibrillate, CORS limited to this machine, protected rule files read-only, loopback default bind.

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
from http.server import ThreadingHTTPServer
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import server  # noqa: E402


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.scheduled = []
        self._orig = {k: getattr(server, k) for k in ("_schedule_host_defibrillate", "_rule_path", "ROOT")}
        server._schedule_host_defibrillate = lambda: self.scheduled.append(1)
        self.root = Path(tempfile.mkdtemp()).resolve()
        shutil.copy(str(CODE / "protected_paths.json"), str(self.root / "protected_paths.json"))
        self.ws = self.root / "data" / "workspace"
        self.ws.mkdir(parents=True)
        server.ROOT = self.root
        server._rule_path = lambda name: (self.ws / name) if name in ("AGENTS.md", "PERSONA.md", "PROJECT.md", "SELF-MODIFY.md") else None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
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


class RulesPutTest(ServerCase):
    def put(self, name, content="NEW"):
        return self.req("PUT", "/api/rules/" + name, {"content": content})

    def test_protected_rule_files_are_read_only(self):
        for name in ("AGENTS.md", "SELF-MODIFY.md"):
            (self.ws / name).write_text("ORIGINAL", encoding="utf-8")
            resp, raw = self.put(name)
            self.assertEqual(resp.status, 403, name)
            self.assertIn("read-only", json.loads(raw)["error"])
            self.assertEqual((self.ws / name).read_text(encoding="utf-8"), "ORIGINAL")
            self.assertEqual([p.name for p in self.ws.iterdir() if ".bak" in p.name], [], "no backup for a refused write")

    def test_other_rule_files_stay_editable(self):
        for name in ("PERSONA.md", "PROJECT.md"):
            (self.ws / name).write_text("ORIGINAL", encoding="utf-8")
            resp, _ = self.put(name)
            self.assertEqual(resp.status, 200, name)
            self.assertEqual((self.ws / name).read_text(encoding="utf-8"), "NEW")

    def test_unknown_file_is_still_404_and_reads_still_work(self):
        self.assertEqual(self.put("nope.md")[0].status, 404)
        (self.ws / "AGENTS.md").write_text("ORIGINAL", encoding="utf-8")
        resp, raw = self.req("GET", "/api/rules/AGENTS.md")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(raw)["content"], "ORIGINAL")

    def test_missing_registry_makes_every_rule_file_read_only(self):
        (self.root / "protected_paths.json").unlink()
        (self.ws / "PERSONA.md").write_text("ORIGINAL", encoding="utf-8")
        self.assertEqual(self.put("PERSONA.md")[0].status, 403)
        self.assertEqual((self.ws / "PERSONA.md").read_text(encoding="utf-8"), "ORIGINAL")


class DefaultBindTest(unittest.TestCase):
    def test_bare_start_is_loopback_only_and_ctl_opts_the_lan_in(self):
        tmp = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if k != "AGY_CHAT_HOST"}
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
        self.assertIn("export AGY_CHAT_HOST=0.0.0.0", ctl)


if __name__ == "__main__":
    unittest.main()
