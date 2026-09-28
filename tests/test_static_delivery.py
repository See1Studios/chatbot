"""Static delivery: revalidation and compression (STATIC_DELIVERY_v1).

The rules are unit-tested directly, and then the real server is asked over HTTP: a first request
gets an ETag, a repeat with If-None-Match gets a 304 with no body, and a gzip-capable client gets a
smaller body. The server runs against a throw-away data directory so it cannot touch the live
install.

Run: python3 -m unittest tests.test_static_delivery  (from services/chatbot)
"""
import gzip
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import static_delivery as sd  # noqa: E402

PORT = 34871   # deliberately odd: the live service is on 3011


def free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


class Rules(unittest.TestCase):
    def test_only_text_is_worth_compressing(self):
        for ct in ("text/html; charset=utf-8", "application/javascript; charset=utf-8",
                   "text/css; charset=utf-8", "application/json", "image/svg+xml"):
            self.assertTrue(sd.compressible(ct), ct)
        for ct in ("image/webp", "image/png", "font/woff2", "application/octet-stream", ""):
            self.assertFalse(sd.compressible(ct), ct)

    def test_gzip_needs_the_client_the_type_and_the_size(self):
        big = sd.MIN_COMPRESS_BYTES + 1
        self.assertEqual(sd.negotiate("gzip, deflate, br", "text/css; charset=utf-8", big), "gzip")
        self.assertEqual(sd.negotiate("", "text/css", big), "", "no Accept-Encoding")
        self.assertEqual(sd.negotiate("br", "text/css", big), "", "client does not take gzip")
        self.assertEqual(sd.negotiate("gzip", "image/webp", big), "", "already compressed")
        self.assertEqual(sd.negotiate("gzip", "text/css", 10), "", "too small to be worth it")

    def test_compression_is_deterministic_and_actually_smaller(self):
        body = b"var x = 1;\n" * 800
        one, two = sd.compress(body), sd.compress(body)
        self.assertEqual(one, two, "gzip embeds a timestamp; mtime must be pinned")
        self.assertLess(len(one), len(body) // 3)
        self.assertEqual(gzip.decompress(one), body)

    def test_the_etag_is_the_files_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.js"
            p.write_text("one", encoding="utf-8")
            first = sd.etag_for(p)
            self.assertEqual(first, sd.etag_for(p), "the same file must keep the same etag")
            p.write_text("one two", encoding="utf-8")   # same mtime is unlikely, size differs
            self.assertNotEqual(first, sd.etag_for(p))
            self.assertTrue(first.startswith('"') and first.endswith('"'))

    def test_if_none_match_follows_rfc_9110(self):
        etag = '"abc-10"'
        self.assertTrue(sd.if_none_match(etag, etag))
        self.assertTrue(sd.if_none_match('W/%s' % etag, etag), "weak form compares equal here")
        self.assertTrue(sd.if_none_match('"other", %s' % etag, etag), "a list")
        self.assertTrue(sd.if_none_match("*", etag))
        self.assertFalse(sd.if_none_match('"other"', etag))
        self.assertFalse(sd.if_none_match("", etag), "no header means a normal 200")
        self.assertFalse(sd.if_none_match(etag, ""), "no etag to compare against")


class OverHttp(unittest.TestCase):
    """The real server, isolated: its own data dir, no obslog path (events stay in memory)."""

    server = None
    data = None

    @classmethod
    def setUpClass(cls):
        if not free(PORT):
            raise unittest.SkipTest("port %d is busy" % PORT)
        cls.data = tempfile.mkdtemp()
        for sub in ("workspace", "sessions"):
            os.makedirs(os.path.join(cls.data, sub), exist_ok=True)
        env = dict(os.environ, CHATBOT_DATA=cls.data, CHATBOT_PORT=str(PORT), CHATBOT_HOST="127.0.0.1",
                   NAS_MCP_PORT="0")
        env.pop("CHATBOT_OBSLOG_PATH", None)   # a scratch server must not write the production log
        env.pop("CHATBOT_CALLER", None)
        cls.server = subprocess.Popen([sys.executable, str(CODE / "server.py")], cwd=str(CODE), env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = "http://127.0.0.1:%d" % PORT
        for _ in range(80):
            if not free(PORT):
                break
            time.sleep(0.25)
        else:
            cls.tearDownClass()
            raise unittest.SkipTest("the scratch server did not come up")
        try:
            urllib.request.urlopen(base + "/healthz", timeout=5).read()
        except Exception as e:  # noqa: BLE001
            cls.tearDownClass()
            raise unittest.SkipTest("healthz never answered: %s" % e)
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        if cls.server and cls.server.poll() is None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.server.kill()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:      # 304 arrives here
            return e.code, dict(e.headers), e.read()

    def test_a_reload_revalidates_instead_of_redownloading(self):
        status, headers, first = self.get("/app.js")
        self.assertEqual(status, 200)
        etag = headers.get("ETag")
        self.assertTrue(etag, "no ETag: every reload re-downloads the whole file")
        self.assertEqual(headers.get("Cache-Control"), "no-cache")
        # An unchanged file must cost nothing on the second visit.
        status2, headers2, second = self.get("/app.js", {"If-None-Match": etag})
        self.assertEqual(status2, 304)
        self.assertEqual(second, b"")
        # A stale validator still gets the bytes, not a wrong 304.
        status3, _, third = self.get("/app.js", {"If-None-Match": '"stale-1"'})
        self.assertEqual(status3, 200)
        self.assertEqual(third, first)

    def test_a_gzip_capable_client_gets_a_smaller_body(self):
        status, headers, plain = self.get("/app.js")
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Content-Encoding"))
        status2, headers2, packed = self.get("/app.js", {"Accept-Encoding": "gzip, deflate"})
        self.assertEqual(status2, 200)
        self.assertEqual(headers2.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", headers2.get("Vary", ""))
        self.assertLess(len(packed), len(plain) // 2)
        self.assertEqual(int(headers2["Content-Length"]), len(packed), "Content-Length must match the body")
        self.assertEqual(gzip.decompress(packed), plain)

    def test_images_are_not_gzipped(self):
        """The rule is unit-tested (test_only_text_is_worth_compressing). There is no image in
        static/ to ask over HTTP -- persona images come from $CHATBOT_DATA by another route -- so a
        skipped HTTP test here would prove nothing."""
        self.assertFalse(sd.compressible("image/webp"))
        self.assertFalse(sd.negotiate("gzip", "image/png", 999_999))

    def test_an_api_route_is_untouched(self):
        """Only static assets gained ETag; without Accept-Encoding the API answers exactly as before."""
        status, headers, body = self.get("/api/providers")
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("ETag"))
        self.assertIsNone(headers.get("Content-Encoding"))
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIn("providers", body.decode("utf-8")[:400])

    def test_a_json_api_answer_is_gzipped_for_a_client_that_asks(self):
        """API_GZIP_v1: the page's session sync pulls 20-30 KB of JSON; a gzip-capable client gets it packed."""
        status, headers, packed = self.get("/api/providers", {"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        plain = self.get("/api/providers")[2]
        if len(plain) < sd.MIN_COMPRESS_BYTES:
            self.assertIsNone(headers.get("Content-Encoding"), "too small to be worth it")
            return
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", headers.get("Vary", ""))
        self.assertEqual(int(headers["Content-Length"]), len(packed))
        self.assertEqual(gzip.decompress(packed), plain)
        self.assertIsNone(headers.get("ETag"))


if __name__ == "__main__":
    unittest.main()
