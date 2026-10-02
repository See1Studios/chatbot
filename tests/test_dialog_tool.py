"""inbox/D: the `dialog` tool -- list, read, send -- speaks as the calling session's character only, refuses an unknown
caller and a private session, answers with reply_to, and has no memo kind.
Run: python3 -m unittest tests.test_dialog_tool  (from services/chatbot)
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CHATBOT_EVENTS_DIR", tempfile.mkdtemp())   # never the live mailbox
os.environ.setdefault("CHATBOT_DIALOGS_DIR", tempfile.mkdtemp())  # nor the live dialogs
os.environ.setdefault("CHATBOT_EDITION", "dev")
import characters as C  # noqa: E402
import dialog_log as D  # noqa: E402
import dialog_tool as T  # noqa: E402
import room_chat as RC  # noqa: E402


def envelope(ok, message, data):
    return {"success": ok, "message": message, "data": data}


class DialogTool(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.a, self.b, self.c = sorted(C.new_id() for _ in range(3))
        for cid, name in ((self.a, "Boss"), (self.b, "Kit"), (self.c, "Ari")):
            C.save(cid, C.new_card(name), self.ws)
        self.patches = [mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.tmp / "events")}),
                        mock.patch.object(RC, "_dir", lambda: self.tmp / "rooms"),
                        mock.patch.object(D, "_dir", lambda: self.tmp / "dialogs"),
                        mock.patch.object(C, "_default_ws", return_value=self.ws)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def as_(self, cid, sid, **args):
        return T.call(args, envelope, {"id": sid, "character": cid, "mode": "work", "private": False})

    def test_an_unknown_caller_or_a_private_session_is_refused(self):
        for who in ({}, {"id": "s1", "character": ""}, {"id": "s1", "character": self.a, "private": True}):
            out = T.call({"action": "send", "to": "Kit", "text": "hi"}, envelope, who)
            self.assertFalse(out["success"], who)
        self.assertEqual(D.dialogs_of(self.b), [])

    def test_send_by_name_opens_the_one_to_one_and_the_other_reads_it(self):
        out = self.as_(self.a, "s-a", action="send", to="kit", text="can you check the build?")
        self.assertTrue(out["success"], out)
        ab = D.dm_id(self.a, self.b)
        self.assertEqual(out["data"], {"dialog_id": ab, "n": 1})
        self.assertEqual(D.history(ab)[0]["who"], self.a, "the sender is the caller, never an argument")
        listed = self.as_(self.b, "s-b", action="list")["data"]["dialogs"]
        self.assertEqual(listed, [{"dialog_id": ab, "name": "Boss", "unread": 1, "mentions": 0}])
        got = self.as_(self.b, "s-b", action="read", dialog_id=ab)["data"]["messages"]
        self.assertEqual(got, [{"n": 1, "from": "Boss", "how": "message", "text": "can you check the build?"}])
        self.assertEqual(D.unread(self.b, ab, "s-b"), (0, 0), "read means read")
        out = self.as_(self.b, "s-b", action="send", dialog_id=ab, text="on it", reply_to="1")
        self.assertEqual(D.history(ab)[-1]["reply_to"], 1)
        self.assertEqual(D.unread(self.a, ab, "s-a"), (1, 0))

    def test_what_is_refused(self):
        ab = D.dm_id(self.a, self.b)
        self.as_(self.a, "s-a", action="send", dialog_id=ab, text="hi")
        for args in ({"action": "send", "dialog_id": ab, "text": "x", "reply_to": 9},
                     {"action": "send", "dialog_id": ab, "text": "  "},
                     {"action": "send", "to": "Boss", "text": "to myself"},
                     {"action": "send", "to": "Nobody", "text": "x"},
                     {"action": "memo", "dialog_id": ab, "text": "x"}):
            self.assertFalse(self.as_(self.a, "s-a", **args)["success"], args)
        self.assertFalse(self.as_(self.c, "s-c", action="read", dialog_id=ab)["success"], "not hers")
        for bad in ({"dialog": ab}, {"dialog_id": "dm:Boss:Kit"}, {}):    # the misses seen live (#554)
            msg = self.as_(self.b, "s-b", action="read", **bad)["message"]
            self.assertIn("dialog_id", msg)
            self.assertIn("action list", msg)
        self.assertEqual(len(D.history(ab)), 1)

    def test_an_action_is_taken_as_something_done(self):
        out = self.as_(self.a, "s-a", action="send", to="Kit", text="sets a coffee on Kit's desk", kind="action")
        self.assertTrue(out["success"], out)
        ab = D.dm_id(self.a, self.b)
        got = self.as_(self.b, "s-b", action="read", dialog_id=ab)["data"]["messages"]
        self.assertEqual(got, [{"n": 1, "from": "Boss", "how": "came by your desk", "text": "sets a coffee on Kit's desk", "kind": "action"}])
        self.assertFalse(self.as_(self.a, "s-a", action="send", to="Kit", text="x", kind="whisper")["success"])
        self.assertIn("kind", T.TOOL_DEFS[0]["inputSchema"]["properties"])
        self.assertIn("office", T.TOOL_DEFS[0]["description"], "coworkers in one office (D9)")

    def test_a_room_message_carries_its_mentions(self):
        r = RC.create("Desk", [self.a, self.b, self.c])
        self.as_(self.a, "s-a", action="send", dialog_id=r["id"], text="@Ari and @Kit, standup")
        self.assertEqual(D.history(r["id"])[0]["mentions"], [self.c, self.b])
        self.assertEqual(D.unread(self.c, r["id"]), (1, 1))

    def test_through_the_tool_server_the_sender_comes_from_the_connection(self):
        import mcp_server as mcp

        class Handler:
            client_address, headers = ("127.0.0.1", 40002), {}
        host = {"id": "s-a", "character": self.a, "mode": "work", "private": False}
        with mock.patch.object(mcp, "_host_get", return_value=host):
            out = mcp.mcp_caller.serving(Handler(), "dialog", lambda: mcp.call_tool(
                "dialog", {"action": "send", "to": "Kit", "text": "hello"}))
        self.assertTrue(out["success"], out)
        self.assertEqual(D.history(D.dm_id(self.a, self.b))[0]["who"], self.a)
        self.assertIn("dialog", [t["name"] for t in mcp.tool_defs()])
        self.assertFalse({"memo", "send_memo", "message.memo"} & {t["name"] for t in mcp.tool_defs()}, "no memo tool (D3)")


if __name__ == "__main__":
    unittest.main()
