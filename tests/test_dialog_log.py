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
os.environ.setdefault("CHATBOT_DIALOGS_DIR", tempfile.mkdtemp())  # nor the live dialogs
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

    def test_a_message_is_said_or_done(self):
        ab = D.dm_id(self.a, self.b)
        said = D.append(ab, self.a, "morning")
        done = D.append(ab, self.a, "waves", kind="action")
        self.assertNotIn("kind", said, "words keep the old shape")
        self.assertEqual(done["kind"], "action")
        with self.assertRaises(ValueError):
            D.append(ab, self.a, "x", kind="memo")
        self.assertEqual([D.line(m) for m in D.history(ab)], ["Boss: morning", "Boss does: waves"])

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


    # ---------------------------------------------------------------------------------------- inbox/B
    def events(self):
        import events
        return [e for e in events._read_all() if e["type"] == "msg.new"]

    def test_each_message_is_announced_to_the_other_characters_without_its_text(self):
        ab = D.dm_id(self.a, self.b)
        D.append(ab, self.a, "secret words")
        r = RC.create("Team", [self.a, self.b, self.c])
        D.append(r["id"], "user", "hello all", mentions=[self.b])
        got = self.events()
        self.assertEqual([(e["to"], e["payload"]) for e in got],
                         [([self.b], {"conversation": ab, "n": 1, "from": self.a}),
                          (sorted([self.a, self.b, self.c]), {"conversation": r["id"], "n": 1, "from": "user"})])
        self.assertNotIn("secret", json.dumps(got))

    def test_unread_counts_others_messages_and_mentions_after_the_read_position(self):
        r = RC.create("Team", [self.a, self.b])
        D.append(r["id"], "user", "@Kit look", mentions=[self.b])
        D.append(r["id"], self.a, "me too")
        D.append(r["id"], self.b, "on it")
        self.assertEqual(D.unread(self.b, r["id"]), (2, 1), "its own line is not unread")
        D.saw(self.b, "s1", r["id"], 2)
        self.assertEqual(D.unread(self.b, r["id"]), (0, 0))

    def test_a_new_session_starts_from_the_characters_read_and_a_handover_goes_back_to_it(self):
        ab = D.dm_id(self.a, self.b)
        for t in ("one", "two", "three"):
            D.append(ab, self.a, t)
        D.saw(self.b, "s-room", ab, 1)
        self.assertEqual(D.seen("s-new", self.b, ab), 1, "a new brain starts where the character read")
        self.assertEqual(D.unread(self.b, ab, "s-new"), (2, 0))
        D.saw(self.b, "s-work", ab, 3)
        D.saw(self.b, "s-work", ab, 2)
        self.assertEqual(D.seen("s-work", self.b, ab), 3, "never back")
        D.saw(self.b, "", ab, 3)
        self.assertEqual(D.seen("s-room", self.b, ab), 1, "the room brain did not see what the work brain saw")
        D.forget("s-room")
        self.assertEqual(D.seen("s-room", self.b, ab), 3)

    def test_a_rooms_read_starts_where_the_member_last_spoke(self):
        r = RC.create("Team", [self.a, self.b])
        for t in ("x", "y", "z"):
            D.append(r["id"], "user", t)
        r = RC.room(r["id"])
        r["seen"][self.b] = 2
        RC._write_json(RC._room_path(r["id"]), r)
        self.assertEqual(D.read(self.b, r["id"]), 2)
        self.assertEqual(D.unread(self.b, r["id"]), (1, 0))

    def test_dialogs_of_a_character(self):
        ab, bc = D.dm_id(self.a, self.b), D.dm_id(self.b, self.c)
        D.append(ab, self.a, "hi")
        D.append(bc, self.c, "hi")
        r = RC.create("Team", [self.a, self.c])
        self.assertEqual(sorted(D.dialogs_of(self.a)), sorted([ab, r["id"]]))
        self.assertEqual(sorted(D.dialogs_of(self.b)), sorted([ab, bc]))


if __name__ == "__main__":
    unittest.main()
