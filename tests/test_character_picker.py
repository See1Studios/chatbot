"""The avatar picks the character: each character has its own sessions and keeps the brain last used with it; a
character other than the chatbot works from its own card and memory and does not delegate (CHARACTER_PICKER_v1).
Run: python3 -m unittest tests.test_character_picker  (from services/chatbot)
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import characters as C  # noqa: E402
import delegation  # noqa: E402
import host_config  # noqa: E402
import instructions as I  # noqa: E402
import mcp_core  # noqa: E402
import server  # noqa: E402
import session as S  # noqa: E402


def env(ok, msg, data):
    return {"ok": ok, "message": msg, "data": data}


class Picker(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        (self.ws / "memory").mkdir(parents=True)
        (self.ws / "AGENTS.md").write_text("charter", encoding="utf-8")
        (self.ws / "memory" / "MEMORY.md").write_text("# Memory\n- pd fact\n", encoding="utf-8")
        self.pd = C.new_id()
        C.save(self.pd, C.new_card("P", "pd", description="pd persona"), self.ws)
        self.lulu = C.new_id()
        C.save(self.lulu, C.new_card("L", "staff", description="lulu persona", display={"title": "막내"},
                                     work={"instructions": "lulu works carefully"},
                                     brains={"work": [{"provider": "agy", "model": "gemini-3.8-flash-low"}]}), self.ws)
        C.memory_path(self.lulu, self.ws).write_text("# Memory\n- [2026-09-24] lulu fact\n", encoding="utf-8")
        self.saved = (S.SESSIONS, S.WORKSPACE, I.WORKSPACE, I.MEMORY_FILE, host_config.WORKSPACE)
        S.SESSIONS = self.tmp / "sessions"
        S.SESSIONS.mkdir()
        S.WORKSPACE = I.WORKSPACE = host_config.WORKSPACE = self.ws
        I.MEMORY_FILE = self.ws / "memory" / "MEMORY.md"
        self.reg = S.Registry()

    def tearDown(self):
        S.SESSIONS, S.WORKSPACE, I.WORKSPACE, I.MEMORY_FILE, host_config.WORKSPACE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_character_gets_its_own_session_on_its_first_brain_and_keeps_the_last_one(self):
        work = self.reg.get_active(self.lulu)
        self.assertEqual((work.character, work.mode, work.provider, work.model),
                         (self.lulu, "work", "agy", "gemini-3.8-flash-low"))
        work.provider, work.model = "codex", "gpt-x"                      # the user switched its brain
        work.history.append({"role": "user", "text": "hi", "ts": 1})
        work.save_meta()
        again = S.Registry()
        self.assertEqual(again.get_active(self.lulu).sid, work.sid)
        self.assertEqual(again.get_active(self.lulu).provider, "codex")
        self.assertNotEqual(again.get_active().sid, work.sid)             # the default character's is its own
        self.assertEqual(again.get_active().character, self.pd)          # sessions always name their character
        priv = again.get_private(self.lulu)
        self.assertEqual((priv.character, priv.provider, priv.model), (self.lulu, "codex", "gpt-x"))

    def test_the_picker_lists_the_default_first_and_every_character_by_id(self):
        rows = server._character_list()
        self.assertEqual([(r["id"], r["session_character"], r["title"], r["default"]) for r in rows],
                         [(self.pd, self.pd, "P", True), (self.lulu, self.lulu, "막내", False)])
        self.assertEqual([server._session_character(x) for x in (self.pd, "", self.lulu, "pd", C.new_id(), "../x")],
                         [self.pd, self.pd, self.lulu, None, None, None])

    def test_avatars_follow_the_provider_then_the_character(self):
        self.assertIsNone(server._character_avatar(self.lulu, "agy"))
        base = C.card_path(self.lulu, self.ws).parent
        (base / "avatar.webp").write_bytes(b"x")
        self.assertEqual(server._character_avatar(self.lulu, "agy").name, "avatar.webp")
        (base / "avatar").mkdir()
        (base / "avatar" / "agy.webp").write_bytes(b"y")
        self.assertEqual(server._character_avatar(self.lulu, "agy"), base / "avatar" / "agy.webp")
        self.assertEqual(server._character_avatar(self.lulu, "../../x").name, "avatar.webp")
        self.assertIsNone(server._character_avatar("../" + self.lulu, "agy"))
        self.assertIsNone(server._character_avatar(self.lulu, "agy", "stage"))          # backgrounds are their own
        (base / "stage").mkdir()
        (base / "stage" / "agy.webp").write_bytes(b"z")
        self.assertEqual(server._character_avatar(self.lulu, "agy", "stage"), base / "stage" / "agy.webp")
        self.assertIsNone(server._character_avatar(self.lulu, "agy", "card.json"))

    def test_a_character_s_work_bundle_is_its_own(self):
        text = I.build_instruction_bundle(character=self.lulu)["text"]
        for want in ("charter", "lulu persona", "lulu works carefully", "lulu fact", "pd fact"):
            self.assertIn(want, text)
        self.assertNotIn("pd persona", text)            # the house memory ("pd fact") is everyone's
        self.assertNotIn(I.NO_ROLE_NOTE, text)            # 루루 holds staff
        pd = I.build_instruction_bundle()["text"]
        self.assertIn("pd fact", pd)
        self.assertNotIn("lulu fact", pd)

    def test_only_the_pd_delegates_and_the_work_memory_is_the_pd_s(self):
        res = delegation.tool_call("delegate", {"action": "plan"}, "chat-agent", server.re.compile("x^"), env,
                                   staff=True)
        self.assertFalse(res["ok"])
        self.assertIn("grants delegate", res["message"])
        res = mcp_core.call("memory", {"action": "add", "text": "x"}, self.tmp, server.re.compile("x^"), staff=True)
        self.assertEqual((res["success"], res["message"]), (False, mcp_core.STAFF_MEMORY_CLOSED))
        res = mcp_core.call("memory", {"action": "show"}, self.tmp, server.re.compile("x^"), staff=True)
        self.assertNotEqual(res["message"], mcp_core.STAFF_MEMORY_CLOSED)   # everyone reads the house memory


class PageUrls(unittest.TestCase):
    def test_every_api_url_built_outside_api_carries_the_base_path(self):
        import re
        src = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
        for m in re.finditer(r"(\S+)\s*\+?\s*'/api/", src):
            line = src[src.rfind("\n", 0, m.start()) + 1:src.find("\n", m.end())]
            if "api(" in line or line.strip().startswith("//"):
                continue                                   # api() adds the base path itself
            self.assertIn("BASE_PATH", line, line.strip())


if __name__ == "__main__":
    unittest.main()
