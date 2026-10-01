"""inbox/A: one record per dialog, numbered within it (Telegram's message box). A dm between two characters has one id
from either end; a room's record is the same shape as before; only members write; a reply points at a message of the
same dialog. Run: python3 -m unittest tests.test_dialog_log  (from services/chatbot)
"""
import json
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
import characters as C  # noqa: E402
import dialog_log as D  # noqa: E402
import room_chat as RC  # noqa: E402


class Dialogs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.a, self.b, self.c = sorted(C.new_id() for _ in range(3))
        for cid, name in ((self.a, "Boss"), (self.b, "Kit"), (self.c, "Ari")):
            C.save(cid, C.new_card(name), self.ws)
        self.patches = [mock.patch.object(RC, "_dir", lambda: self.tmp / "rooms"),
                        mock.patch.object(D, "_dir", lambda: self.tmp / "dialogs"),
                        mock.patch.object(C, "_default_ws", return_value=self.ws)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_dm_has_one_id_from_either_end(self):
        self.assertEqual(D.dm_id(self.a, self.b), D.dm_id(self.b, self.a))
        self.assertEqual(D.members(D.dm_id(self.b, self.a)), [self.a, self.b])
        for bad in ((self.a, self.a), (self.a, "user"), ("x", self.b)):
            with self.assertRaises(ValueError):
                D.dm_id(*bad)
        self.assertEqual(D.members("dm:%s:%s" % (self.b, self.a)), [])   # unsorted: not a dialog id
        self.assertEqual(D.members("nonsense"), [])

    def test_messages_are_numbered_within_their_dialog(self):
        ab, ac = D.dm_id(self.a, self.b), D.dm_id(self.a, self.c)
        self.assertEqual(D.append(ab, self.a, "hi")["n"], 1)
        self.assertEqual(D.append(ab, self.b, "hey")["n"], 2)
        self.assertEqual(D.append(ac, self.c, "yo")["n"], 1)
        self.assertEqual([m["text"] for m in D.history(ab)], ["hi", "hey"])
        self.assertEqual([m["n"] for m in D.history(ab, after=1)], [2])
        self.assertTrue(D.path(ab).name.startswith("dm_") and ":" not in D.path(ab).name)

    def test_only_members_write(self):
        ab = D.dm_id(self.a, self.b)
        for who in (self.c, "user"):
            with self.assertRaises(ValueError):
                D.append(ab, who, "let me in")
        self.assertEqual(D.history(ab), [])

    def test_a_reply_points_at_a_message_of_the_same_dialog(self):
        ab, ac = D.dm_id(self.a, self.b), D.dm_id(self.a, self.c)
        D.append(ac, self.a, "elsewhere")
        first = D.append(ab, self.a, "question")
        self.assertEqual(D.append(ab, self.b, "answer", reply_to=first["n"])["reply_to"], first["n"])
        with self.assertRaises(ValueError):
            D.append(ab, self.b, "to nothing", reply_to=9)
        self.assertNotIn("reply_to", D.history(ab)[0])

    def test_a_room_record_keeps_its_file_and_shape(self):
        r = RC.create("Team", [self.a, self.b])
        legacy = {"n": 1, "ts": 1.0, "who": "user", "text": "old line", "mentions": []}
        RC._log_path(r["id"]).parent.mkdir(parents=True, exist_ok=True)
        RC._log_path(r["id"]).write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        self.assertEqual(D.path(r["id"]), RC._log_path(r["id"]))
        self.assertEqual(RC.messages(r["id"]), [legacy])
        m = D.append(r["id"], self.b, "@Boss hi", mentions=[self.a])
        self.assertEqual((m["n"], m["mentions"]), (2, [self.a]))
        self.assertEqual(set(m), {"n", "ts", "who", "text", "mentions"})
        self.assertEqual(D.members(r["id"]), [self.a, self.b, "user"])
        with self.assertRaises(ValueError):
            D.append(r["id"], self.c, "not in this room")


if __name__ == "__main__":
    unittest.main()
