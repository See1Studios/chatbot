"""inbox/C: before a work turn a session hears which dialogs it has not seen -- counts and mentions, never a body --
once per change; after a handover the new brain gets a short recap and starts again from the character's read. Room
seats and private sessions get no such line.
Run: python3 -m unittest tests.test_turn_notices  (from services/chatbot)
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CHATBOT_EVENTS_DIR", tempfile.mkdtemp())   # never the live mailbox
os.environ.setdefault("CHATBOT_DIALOGS_DIR", tempfile.mkdtemp())  # nor the live dialogs
import characters as C  # noqa: E402
import dialog_log as D  # noqa: E402
import room_chat as RC  # noqa: E402


class TurnNote(unittest.TestCase):
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
        self.ab = D.dm_id(self.a, self.b)
        self.room = RC.create("Desk", [self.a, self.b, self.c])["id"]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_dm_is_delivered_and_heard_a_room_is_counted_with_its_calls(self):
        D.append(self.ab, self.a, "the plan for today")
        D.append(self.ab, self.a, "sets a coffee on Kit's desk", kind="action")
        D.append(self.room, "user", "@Kit can you", mentions=[self.b])
        D.append(self.room, self.c, "sure")
        noted = {}
        line = D.turn_note(self.b, "s-kit", noted)
        self.assertIn("Boss (message): the plan for today", line, "addressed to it: given, not fetched (inbox/H)")
        self.assertIn("Boss (came by your desk): sets a coffee on Kit's desk", line)
        self.assertIn("Desk (meeting room): 2 new, 1 mention you", line)
        self.assertIn("the user (in the room): @Kit can you", line, "a room's call is given")
        self.assertNotIn("sure", line, "the rest of a room is only counted")
        self.assertEqual(D.unread(self.b, self.ab, "s-kit"), (0, 0), "delivered means heard")
        self.assertEqual(D.turn_note(self.b, "s-kit", noted), "", "nothing new: not said again")
        D.append(self.ab, self.a, "one more")
        again = D.turn_note(self.b, "s-kit", noted)
        self.assertIn("Boss (message): one more", again)
        self.assertNotIn("the plan for today", again, "only what is new")
        D.append(self.ab, self.b, "my own line")
        self.assertEqual(D.turn_note(self.b, "s-kit", noted), "", "its own line is not news")

    def test_a_long_backlog_gives_the_last_ones_and_counts_the_rest(self):
        for k in range(8):
            D.append(self.ab, self.a, "note %d" % k)
        line = D.turn_note(self.b, "s-kit", {})
        self.assertIn("(3 earlier from Boss not shown [%s])" % self.ab, line)
        self.assertIn("note 7", line)
        self.assertNotIn("note 2", line)

    def test_a_handover_recaps_and_starts_again_from_the_characters_read(self):
        for t in ("first", "second", "third"):
            D.append(self.ab, self.a, t)
        D.saw(self.b, "s-kit", self.ab, 3)            # this brain read it all ...
        D.saw(self.b, "", self.ab, 3)
        noted = {}
        self.assertEqual(D.turn_note(self.b, "s-kit", noted), "")
        line = D.turn_note(self.b, "s-kit", noted, handed_over=True)   # ... then lost it
        self.assertIn("[Office messages", line)
        self.assertIn("#3 Boss (message): third", line)
        self.assertIn("#2 Boss (message): second", line)
        self.assertNotIn("first", line, "only the last messages")
        self.assertNotIn("[Office]", line, "the character had read them")

    def test_a_recap_shows_an_action_as_something_done(self):
        D.append(self.ab, self.a, "hands Kit a coffee", kind="action")
        D.append(self.ab, self.a, "long night?")
        line = D.turn_note(self.b, "s-kit", {}, handed_over=True)
        self.assertIn("#1 Boss (came by your desk): hands Kit a coffee", line)
        self.assertIn("#2 Boss (message): long night?", line)
        self.assertNotIn("DM", line, "an action is not sent by DM (#558)")

    def test_the_server_hook_adds_the_line_for_work_sessions_only(self):
        import server
        D.append(self.ab, self.a, "ping")
        work = SimpleNamespace(sid="s-work", character=self.b)
        seat = SimpleNamespace(sid="s-seat", character=self.b, mode="room")
        private = SimpleNamespace(sid="s-priv", character=self.b, is_private=True, mode="private")
        note = server._turn_notices(work)
        self.assertIn("[Office]", note)
        self.assertIn("Boss (message): ping", note)
        self.assertNotIn("[Office]", server._turn_notices(seat))
        self.assertNotIn("[Office]", server._turn_notices(private))
        work._handed_over = True
        self.assertIn("[Office messages", server._turn_notices(work))
        self.assertFalse(hasattr(work, "_handed_over"), "a handover is recapped once")


if __name__ == "__main__":
    unittest.main()
