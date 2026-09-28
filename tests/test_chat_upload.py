"""Files attached to a message (composer-plus-menu plus/C, chat_upload.py): saved in the session's own uploads/
folder, pending until the next message of that session, which carries their list; names are cleaned, secret-looking
names and oversize files refused, and a ✕ before sending takes one back. The page reads the same list as cards, so
the format is checked against its parser too.
Run: python3 -m unittest tests.test_chat_upload  (from services/chatbot)
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import chat_upload as U  # noqa: E402

SID = "20260928-180000-abc123"


def up(name, data=b"hello", ctype="text/plain", sid=SID, length=None):
    headers = {"Content-Length": str(len(data) if length is None else length), "X-File-Name": name, "Content-Type": ctype}
    return U.handle("/api/sessions/%s/upload" % sid, headers, io.BytesIO(data))


class Upload(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / SID).mkdir()
        self.patch = mock.patch.object(U, "_sessions_dir", return_value=self.tmp)
        self.patch.start()
        U._pending.clear()

    def tearDown(self):
        self.patch.stop()
        U._pending.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_other_paths_are_not_ours(self):
        for p in ("/api/sessions/%s/message" % SID, "/api/characters/import", "/api/sessions/x/uploads"):
            self.assertIsNone(U.handle(p, {}, io.BytesIO(b"")), p)

    def test_a_file_waits_in_the_session_folder_and_rides_the_next_message(self):
        code, body = up("%EB%B3%B4%EA%B3%A0%EC%84%9C.md", b"# report")          # 보고서.md, URI-encoded
        self.assertEqual(code, 200, body)
        f = body["file"]
        self.assertEqual(Path(f["path"]).parent, self.tmp / SID / "uploads")
        self.assertTrue(f["name"].endswith("-보고서.md"))
        self.assertEqual(Path(f["path"]).read_bytes(), b"# report")
        text = U.take_pending(SID, "이거 요약해줘")
        self.assertTrue(text.startswith("이거 요약해줘\n\n[Attached files"))
        self.assertIn("- %s (text/plain, 1 KB)" % f["path"], text)
        self.assertEqual(U.take_pending(SID, "다음 말"), "다음 말", "sent once, then gone")

    def test_a_name_is_only_a_name(self):
        code, body = up("../../etc/notes.txt")
        self.assertEqual(code, 200)
        self.assertEqual(Path(body["file"]["path"]).parent, self.tmp / SID / "uploads")
        self.assertTrue(body["file"]["name"].endswith("-notes.txt"))
        self.assertEqual(U.safe_name('a<b>:c"d|e?.txt'), "a_b__c_d_e_.txt")
        self.assertEqual(U.safe_name(""), "file")

    def test_secrets_oversize_and_bad_sessions_are_refused(self):
        for name in (".env", ".env.local", "id_rsa", "prod-api_key.txt", "server.pem", "../x/.netrc", "passwd.txt"):
            self.assertEqual(up(name)[0], 400, name)
        self.assertEqual(up("big.bin", b"x", length=U.MAX_BYTES + 1)[0], 413)
        self.assertEqual(up("a.txt", sid="..")[0], 400)
        self.assertEqual(up("a.txt", sid="no-such-session")[0], 404)
        self.assertEqual(up("empty.txt", b"")[0], 400)
        self.assertFalse((self.tmp / SID / "uploads").exists() and any((self.tmp / SID / "uploads").iterdir()))

    def test_one_file_waits_for_one_message(self):
        self.assertEqual(U.MAX_PENDING, 1, "the page replaces an attached file; the server holds one")
        self.assertEqual(up("f.txt")[0], 200)
        self.assertEqual(up("one-more.txt")[0], 400)

    def test_the_x_takes_one_back_and_deletes_it(self):
        f = up("a.txt")[1]["file"]
        body = json.dumps({"name": f["name"]}).encode()
        code, res = U.handle("/api/sessions/%s/upload/remove" % SID, {"Content-Length": str(len(body))}, io.BytesIO(body))
        self.assertEqual((code, res["removed"]), (200, True))
        self.assertFalse(Path(f["path"]).exists())
        self.assertNotIn(f["path"], U.take_pending(SID, "x"))

    def test_the_message_route_takes_the_pending_list_before_sending(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        take = src.index("chat_upload.take_pending(sid, text)")
        self.assertLess(take, src.index("rotated = sess.send(text", take))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PageReadsTheSameList(unittest.TestCase):
    def test_the_page_turns_the_list_into_cards_and_leaves_other_text_alone(self):
        src = (ROOT / "static" / "app-attach.js").read_text(encoding="utf-8")
        a, b = src.index("const ATTACH_HEAD"), src.index("function renderAttachmentCards")
        items = [{"path": "/d/sessions/s/uploads/20260928-181500-보고서 최종.pdf", "mime": "application/pdf", "size_human": "1.2 MB"},
                 {"path": "/d/sessions/s/uploads/20260928-181500-2-shot.png", "mime": "image/png", "size_human": "88 KB"}]
        texts = ["요약해줘\n\n" + U.attachment_block(items), U.attachment_block(items[:1]),
                 "그냥 글", "[Attached files - read them with your file tools]\n아무 말"]
        js = src[a:b] + "\nconsole.log(JSON.stringify(%s.map(t => { const r = splitAttachmentBlock(t); "\
             "return [r.text, r.files.map(f => [attachDisplayName(f.path), f.mime, f.size])]; })));" % json.dumps(texts, ensure_ascii=False)
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        got = json.loads(out.stdout)
        self.assertEqual(got[0], ["요약해줘", [["보고서 최종.pdf", "application/pdf", "1.2 MB"], ["shot.png", "image/png", "88 KB"]]])
        self.assertEqual(got[1], ["", [["보고서 최종.pdf", "application/pdf", "1.2 MB"]]])
        self.assertEqual(got[2], ["그냥 글", []])
        self.assertEqual(got[3][1], [], "a header without our list is not taken apart")


if __name__ == "__main__":
    unittest.main()
