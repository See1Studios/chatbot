"""Unit tests for user profile and avatar routes in route_files.py.
Run: engine/run-tests.sh test_route_user
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests._paths import ENGINE, REPO
ROOT = REPO
sys.path.insert(0, str(ENGINE))

import route_files
import route_table as RT


class FakeHandler:
    def __init__(self, headers=None, rfile=None):
        self.headers = headers or {}
        self.rfile = rfile or io.BytesIO()
        self.sent = []

    def _send(self, code, body, content_type, **kw):
        self.sent.append((code, body, content_type, kw))


class TestRouteUser(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orig_ws = route_files.WORKSPACE
        route_files.WORKSPACE = self.tmp

    def tearDown(self):
        route_files.WORKSPACE = self.orig_ws

    def test_get_user_without_files(self):
        h = FakeHandler()
        req = RT.Req(h, "/api/user")
        route_files.user_info(req)
        self.assertEqual(len(h.sent), 1)
        code, raw, ct, _ = h.sent[0]
        self.assertEqual(code, 200)
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["user_md"], "")
        self.assertFalse(data["has_avatar"])
        self.assertEqual(data["avatar_url"], "")

    def test_put_user_and_get_user(self):
        h = FakeHandler()
        req = RT.Req(h, "/api/user", body={"user_md": "# Profile\nCall: Coach"})
        route_files.user_save(req)
        self.assertEqual(len(h.sent), 1)
        code, raw, _, _ = h.sent[0]
        self.assertEqual(code, 200)
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data["ok"])

        # Check file was written
        md_file = self.tmp / "USER.md"
        self.assertTrue(md_file.is_file())
        self.assertEqual(md_file.read_text(encoding="utf-8"), "# Profile\nCall: Coach")

        # Now GET /api/user
        h2 = FakeHandler()
        req2 = RT.Req(h2, "/api/user")
        route_files.user_info(req2)
        code2, raw2, _, _ = h2.sent[0]
        self.assertEqual(code2, 200)
        data2 = json.loads(raw2.decode("utf-8"))
        self.assertEqual(data2["user_md"], "# Profile\nCall: Coach")

    def test_avatar_lifecycle(self):
        # 1. GET avatar when missing -> 404
        h = FakeHandler()
        req = RT.Req(h, "/api/user/avatar")
        route_files.user_avatar_get(req)
        self.assertEqual(h.sent[0][0], 404)

        # 2. Upload avatar
        test_img = Image.new("RGBA", (100, 200), color=(255, 0, 0, 255))
        buf = io.BytesIO()
        test_img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        h_upload = FakeHandler(headers={"Content-Length": str(len(raw_bytes))}, rfile=io.BytesIO(raw_bytes))
        req_upload = RT.Req(h_upload, "/api/user/avatar")
        route_files.user_avatar_upload(req_upload)
        self.assertEqual(h_upload.sent[0][0], 200)
        upload_resp = json.loads(h_upload.sent[0][1].decode("utf-8"))
        self.assertTrue(upload_resp["ok"])
        self.assertTrue(upload_resp["has_avatar"])
        self.assertTrue(upload_resp["avatar_url"].startswith("/api/user/avatar"))

        # Verify saved file is 512x512 WebP
        av_path = self.tmp / "user_avatar.webp"
        self.assertTrue(av_path.is_file())
        with Image.open(av_path) as saved_img:
            self.assertEqual(saved_img.size, (512, 512))
            self.assertEqual(saved_img.format, "WEBP")

        # 3. GET avatar -> 200
        h_get = FakeHandler()
        req_get = RT.Req(h_get, "/api/user/avatar")
        route_files.user_avatar_get(req_get)
        self.assertEqual(h_get.sent[0][0], 200)
        self.assertEqual(h_get.sent[0][2], "image/webp")

        # 4. DELETE avatar -> 200
        h_del = FakeHandler()
        req_del = RT.Req(h_del, "/api/user/avatar")
        route_files.user_avatar_delete(req_del)
        self.assertEqual(h_del.sent[0][0], 200)
        del_resp = json.loads(h_del.sent[0][1].decode("utf-8"))
        self.assertTrue(del_resp["ok"])
        self.assertFalse(del_resp["has_avatar"])
        self.assertFalse(av_path.exists())

    def test_upload_invalid_image(self):
        bad_bytes = b"not an image at all"
        h = FakeHandler(headers={"Content-Length": str(len(bad_bytes))}, rfile=io.BytesIO(bad_bytes))
        req = RT.Req(h, "/api/user/avatar")
        route_files.user_avatar_upload(req)
        self.assertEqual(h.sent[0][0], 400)
        resp = json.loads(h.sent[0][1].decode("utf-8"))
        self.assertFalse(resp["ok"])


if __name__ == "__main__":
    unittest.main()
