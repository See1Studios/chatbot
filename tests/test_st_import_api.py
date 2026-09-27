"""Tests for SillyTavern PNG character card import API (POST /api/characters/import).

Run: python3 -m unittest tests.test_st_import_api
"""
import http.client
import json
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import host_config  # noqa: E402
import server  # noqa: E402
from tools.st_import import create_st_png_bytes  # noqa: E402


def make_multipart_body(fields: dict, files: dict, boundary: str = "----TestBoundary12345") -> tuple:
    """Build a multipart/form-data payload with the given fields and files."""
    lines = []
    for k, v in fields.items():
        lines.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    for k, (filename, content, content_type) in files.items():
        header = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{k}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        lines.append(header + content + b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(lines)
    content_type_hdr = f"multipart/form-data; boundary={boundary}"
    return content_type_hdr, body


class StImportApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "data" / "workspace"
        self.ws.mkdir(parents=True)
        shutil.copy(str(ROOT / "protected_paths.json"), str(self.tmp / "protected_paths.json"))

        self.orig_host_ws = host_config.WORKSPACE
        self.orig_server_ws = getattr(server, "WORKSPACE", None)
        self.orig_server_root = getattr(server, "ROOT", None)

        host_config.WORKSPACE = self.ws
        server.WORKSPACE = self.ws
        server.ROOT = self.tmp

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        host_config.WORKSPACE = self.orig_host_ws
        if self.orig_server_ws is not None:
            server.WORKSPACE = self.orig_server_ws
        if self.orig_server_root is not None:
            server.ROOT = self.orig_server_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        h.setdefault("Origin", f"http://{self.host}")
        conn.request(method, path, body=body, headers=h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp, raw

    def test_import_v2_card_multipart_success(self):
        card = {
            "name": "Aria",
            "description": "Network analyst",
            "creator": "Tester",
            "first_mes": "Hello there.",
        }
        png_bytes = create_st_png_bytes(card)
        ct, body = make_multipart_body(
            {"extra_field": "sample"},
            {"file": ("aria.png", png_bytes, "image/png")},
        )
        resp, raw = self.req("POST", "/api/characters/import", body=body, headers={"Content-Type": ct})
        self.assertEqual(resp.status, 200)

        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("ok"))
        char_info = data.get("character")
        self.assertIsNotNone(char_info)
        self.assertEqual(char_info.get("name"), "Aria")
        cid = char_info.get("id")
        self.assertTrue(cid.startswith("char_"))

        char_dir = self.ws / "characters" / cid
        self.assertTrue((char_dir / "card.json").is_file())
        self.assertTrue((char_dir / "avatar_master.png").is_file())
        self.assertTrue((char_dir / "avatar.webp").is_file())
        self.assertTrue((char_dir / "visual.md").is_file())

        saved_card = json.loads((char_dir / "card.json").read_text(encoding="utf-8"))
        self.assertEqual(saved_card["data"]["name"], "Aria")

        # Verify GET /api/characters lists this character
        resp_list, raw_list = self.req("GET", "/api/characters")
        self.assertEqual(resp_list.status, 200)
        listing = json.loads(raw_list.decode("utf-8")).get("characters", [])
        self.assertTrue(any(c["id"] == cid and c["name"] == "Aria" for c in listing))

    def test_import_v3_card_multipart_success(self):
        card = {
            "spec": "chara_card_v3",
            "spec_version": "3.0",
            "data": {
                "name": "Elena",
                "description": "Operations coordinator",
                "creator": "Studio Lead",
                "first_mes": "Ready for orders.",
            },
        }
        png_bytes = create_st_png_bytes(card)
        ct, body = make_multipart_body(
            {},
            {"card": ("elena.png", png_bytes, "image/png")},
        )
        resp, raw = self.req("POST", "/api/characters/import", body=body, headers={"Content-Type": ct})
        self.assertEqual(resp.status, 200)

        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data.get("success"))
        char_info = data.get("character")
        self.assertEqual(char_info.get("name"), "Elena")
        cid = char_info.get("id")

        char_dir = self.ws / "characters" / cid
        self.assertTrue((char_dir / "card.json").is_file())

    def test_import_raw_png_bytes_success(self):
        card = {
            "name": "Nova",
            "description": "Exploration unit",
        }
        png_bytes = create_st_png_bytes(card)
        resp, raw = self.req(
            "POST",
            "/api/characters/import",
            body=png_bytes,
            headers={"Content-Type": "image/png"},
        )
        self.assertEqual(resp.status, 200)
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertEqual(data["character"]["name"], "Nova")

    def test_import_non_png_file_fails(self):
        ct, body = make_multipart_body(
            {},
            {"file": ("document.txt", b"plain text content not a png", "text/plain")},
        )
        resp, raw = self.req("POST", "/api/characters/import", body=body, headers={"Content-Type": ct})
        self.assertEqual(resp.status, 400)
        data = json.loads(raw.decode("utf-8"))
        self.assertFalse(data.get("success"))
        self.assertIn("error", data)

    def test_import_png_without_chara_chunk_fails(self):
        # 1x1 empty PNG without SillyTavern chara chunk
        import struct
        import zlib
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
        raw_pixels = b"\x00\xff\xff\xff"
        idat_content = zlib.compress(raw_pixels)
        idat = struct.pack(">I", len(idat_content)) + b"IDAT" + idat_content + struct.pack(">I", zlib.crc32(b"IDAT" + idat_content))
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
        plain_png = sig + ihdr + idat + iend

        ct, body = make_multipart_body(
            {},
            {"file": ("plain.png", plain_png, "image/png")},
        )
        resp, raw = self.req("POST", "/api/characters/import", body=body, headers={"Content-Type": ct})
        self.assertEqual(resp.status, 400)
        data = json.loads(raw.decode("utf-8"))
        self.assertFalse(data.get("success"))
        self.assertIn("chara", data.get("error", "").lower())

    def test_import_empty_body_fails(self):
        resp, raw = self.req(
            "POST",
            "/api/characters/import",
            body=b"",
            headers={"Content-Type": "image/png"},
        )
        self.assertEqual(resp.status, 400)
        data = json.loads(raw.decode("utf-8"))
        self.assertFalse(data.get("success"))

    def test_import_requires_same_origin(self):
        card = {"name": "Blocked"}
        png_bytes = create_st_png_bytes(card)
        ct, body = make_multipart_body({}, {"file": ("card.png", png_bytes, "image/png")})
        # Explicitly request with foreign origin and no Sec-Fetch-Site
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "POST",
            "/api/characters/import",
            body=body,
            headers={"Content-Type": ct, "Origin": "http://evil.com"},
        )
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        self.assertEqual(resp.status, 403)
        data = json.loads(raw.decode("utf-8"))
        self.assertFalse(data.get("ok"))


if __name__ == "__main__":
    unittest.main()
