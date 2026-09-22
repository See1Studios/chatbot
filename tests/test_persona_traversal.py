"""GET /persona/ must not follow .. out of the persona tree.
Run: python3 -m unittest tests.test_persona_traversal  (from services/chatbot)
"""
import http.client
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import server  # noqa: E402


class PersonaTraversal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        persona = self.tmp / "persona"
        persona.mkdir()
        (persona / "avatar.webp").write_bytes(b"RIFF....WEBP")
        web = self.tmp / "web" / "chat" / "persona"
        web.mkdir(parents=True)
        self._orig = {k: getattr(server, k) for k in ("DATA", "WEB_ROOT")}
        server.DATA = self.tmp
        server.WEB_ROOT = self.tmp / "web"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.02),
            daemon=True,
        ).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for k, v in self._orig.items():
            setattr(server, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path):
        # http.client keeps `..` in the request target; urllib would collapse it.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp, raw

    def test_dotdot_escape_is_404(self):
        resp, _ = self.get("/persona/../server.py")
        self.assertEqual(resp.status, 404)

    def test_existing_avatar_is_200(self):
        resp, body = self.get("/persona/avatar.webp")
        self.assertEqual(resp.status, 200)
        self.assertTrue(body)


if __name__ == "__main__":
    unittest.main()
