"""An attached image reaches an image-capable HTTP model as an image (composer-plus-menu plus/E). The message keeps its
text list of paths (chat_upload.attachment_block); the OpenAI-dialect adapter adds an image part for the images in
that list when the live catalog says the model takes image input, only on this turn's message, and only for files
inside a session's uploads/ folder. Anything else is left to the file tools.
Run: python3 -m unittest tests.test_attach_images  (from services/chatbot)
"""
import base64
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import chat_upload as U  # noqa: E402
from providers.adapter_openai import OpenAIDialectAdapter  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.up = self.tmp / "s1" / "uploads"
        self.up.mkdir(parents=True)
        (self.up / "20260928-190000-cat.png").write_bytes(PNG)
        (self.up / "20260928-190000-notes.md").write_text("# notes")
        self.outside = self.tmp / "elsewhere.png"
        self.outside.write_bytes(PNG)
        self.patch = mock.patch.object(U, "_sessions_dir", return_value=self.tmp)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def item(self, path, mime):
        return {"path": str(path), "mime": mime, "size_human": "1 KB"}

    def message(self, *items):
        return "이 그림 뭐야?\n\n" + U.attachment_block(list(items))


class WhichImages(Base):
    def test_the_list_parses_back(self):
        items = [self.item(self.up / "20260928-190000-cat.png", "image/png"), self.item(self.up / "a b (1).md", "text/markdown")]
        self.assertEqual(U.parse_block(self.message(*items)), [{"path": x["path"], "mime": x["mime"]} for x in items])
        self.assertEqual(U.parse_block("그냥 글"), [])
        old = "[Attached files - read them with your file tools]\n- /x/uploads/a.png (image/png, 1 KB)"
        self.assertEqual(U.parse_block(old), [{"path": "/x/uploads/a.png", "mime": "image/png"}], "older messages still read")

    def test_only_our_uploaded_images(self):
        text = self.message(self.item(self.up / "20260928-190000-cat.png", "image/png"),
                            self.item(self.up / "20260928-190000-notes.md", "text/markdown"),
                            self.item(self.outside, "image/png"),
                            self.item(self.up / "missing.png", "image/png"))
        self.assertEqual(U.attached_images(text), [("image/png", PNG)])

    def test_an_oversize_image_is_left_to_the_file_tools(self):
        with mock.patch.object(U, "IMAGE_MAX_BYTES", 10):
            self.assertEqual(U.attached_images(self.message(self.item(self.up / "20260928-190000-cat.png", "image/png"))), [])


class AdapterSendsThem(Base):
    def adapter(self, capable):
        a = OpenAIDialectAdapter(id="or", base_url="http://x/v1", api_key_env="NONE", default_model="m")
        a._get_models_meta = lambda: {"m": {"architecture": {"input_modalities": ["text", "image"] if capable else ["text"]}}}
        return a

    def test_an_image_capable_model_gets_the_picture_on_this_turn_only(self):
        text = self.message(self.item(self.up / "20260928-190000-cat.png", "image/png"))
        msgs = [{"role": "user", "content": text}, {"role": "assistant", "content": "봤어"}, {"role": "user", "content": text}]
        out = self.adapter(True)._with_attached_images(list(msgs), types.SimpleNamespace(model="m"))
        self.assertEqual(out[0]["content"], text, "an earlier turn is not re-sent")
        parts = out[2]["content"]
        self.assertEqual(parts[0]["text"], text + OpenAIDialectAdapter.INLINE_IMAGE_NOTE, "paths stay; the model is told")
        self.assertEqual(parts[1]["image_url"]["url"], "data:image/png;base64," + base64.b64encode(PNG).decode())
        self.assertEqual(len(parts), 2, "sent once")

    def test_after_switching_model_a_recent_image_still_goes_along(self):
        # 2026-09-28: attached on a text-only model, then switched to Space Bunny and asked "can you see it?"
        text = self.message(self.item(self.up / "20260928-190000-cat.png", "image/png"))
        msgs = [{"role": "user", "content": text}, {"role": "assistant", "content": "못 봐요"},
                {"role": "user", "content": "이 이미지 보여?"}]
        out = self.adapter(True)._with_attached_images(list(msgs), types.SimpleNamespace(model="m"))
        self.assertEqual(out[0]["content"], text)
        self.assertEqual(out[2]["content"][0]["text"], "이 이미지 보여?" + OpenAIDialectAdapter.INLINE_IMAGE_NOTE)
        self.assertEqual(out[2]["content"][1]["type"], "image_url")

    def test_an_image_further_back_is_not_re_sent(self):
        text = self.message(self.item(self.up / "20260928-190000-cat.png", "image/png"))
        msgs = [{"role": "user", "content": text}]
        for n in range(OpenAIDialectAdapter.IMAGE_LOOKBACK):
            msgs += [{"role": "assistant", "content": "a"}, {"role": "user", "content": "말 %d" % n}]
        out = self.adapter(True)._with_attached_images(list(msgs), types.SimpleNamespace(model="m"))
        self.assertEqual(out, msgs, "past the lookback the picture is not sent every turn forever")

    def test_a_text_model_or_no_image_leaves_the_message_alone(self):
        text = self.message(self.item(self.up / "20260928-190000-cat.png", "image/png"))
        msgs = [{"role": "user", "content": text}]
        self.assertEqual(self.adapter(False)._with_attached_images(list(msgs), types.SimpleNamespace(model="m")), msgs)
        plain = [{"role": "user", "content": "안녕"}]
        self.assertEqual(self.adapter(True)._with_attached_images(list(plain), types.SimpleNamespace(model="m")), plain)

    def test_unknown_models_are_not_capable(self):
        a = self.adapter(True)
        self.assertFalse(a.supports_images("not-in-catalog"))
        a._get_models_meta = mock.Mock(side_effect=RuntimeError("down"))
        self.assertFalse(a.supports_images("m"))



class WhoCanSee(unittest.TestCase):
    def ask(self, adapter, model="m", query=None):
        sess = types.SimpleNamespace(adapter=adapter, model=model)
        import session
        with mock.patch.object(session.REG, "peek", return_value=sess):
            return U.handle_get("/api/sessions/s1/sees-images", query or {})

    def test_the_catalog_answers_for_http_models_and_cli_agents_look_themselves(self):
        a = OpenAIDialectAdapter(id="or", base_url="http://x/v1", api_key_env="NONE", default_model="m")
        a._get_models_meta = lambda: {"vision": {"architecture": {"input_modalities": ["text", "image"]}},
                                      "text-only": {"architecture": {"input_modalities": ["text"]}}}
        self.assertEqual(self.ask(a, "vision"), (200, {"ok": True, "sees": True}))
        self.assertEqual(self.ask(a, "text-only"), (200, {"ok": True, "sees": False}))
        self.assertEqual(self.ask(a, "text-only", {"model": ["vision"]})[1]["sees"], True, "the page's pick wins")
        cli = types.SimpleNamespace(id="claude")
        self.assertEqual(self.ask(cli)[1]["sees"], True)
        self.assertIsNone(U.handle_get("/api/sessions/s1/gifts", {}))

class CodexGetsThemAsFlags(Base):
    def test_this_turn_s_images_become_image_flags_before_the_stdin_marker(self):
        from providers.adapter_codex import CodexAdapter
        img = self.up / "20260928-190000-cat.png"
        text = self.message(self.item(img, "image/png"), self.item(self.up / "20260928-190000-notes.md", "text/markdown"),
                            self.item(self.outside, "image/png"))
        for conv in (None, "thread-1"):                          # the first turn and every resume
            args = CodexAdapter().build_args("gpt-x", "", conv, [], prompt=text)
            self.assertEqual([a for a in args if a.startswith("--image")], ["--image=%s" % img.resolve()])
            self.assertEqual(args[-1], "-", "the prompt still comes on stdin")
        self.assertFalse([a for a in CodexAdapter().build_args("gpt-x", "", None, [], prompt="안녕") if a.startswith("--image")])

if __name__ == "__main__":
    unittest.main()
