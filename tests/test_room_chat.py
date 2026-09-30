"""Group rooms, first step: work rooms (room_chat.py, plan evt/E, decision E4). Who answers (SillyTavern activation:
natural / list / manual, @mentions first), at most MAX_REPLIES answers per user message with at most MAX_CHAIN from
characters calling each other, each member hearing only what was said since it last spoke, from its own hidden
"room" session that never becomes its one-to-one chat.
Run: python3 -m unittest tests.test_room_chat  (from services/chatbot)
"""
import os
import random
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CHATBOT_EVENTS_DIR", tempfile.mkdtemp())   # never the live mailbox
import characters as C  # noqa: E402
import room_chat as RC  # noqa: E402


class FakeSeat:
    """A member's session: answers each prompt with a scripted line."""
    def __init__(self, sid, lines):
        self.sid, self.lines, self.prompts, self.history, self.busy, self.mode = sid, list(lines), [], [], False, "room"

    def send(self, text):
        self.prompts.append(text)
        self.history.append({"role": "user", "text": text})
        self.history.append({"role": "assistant", "text": self.lines.pop(0) if self.lines else ""})
        return None


class Rooms(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.a, self.b, self.c = sorted(C.new_id() for _ in range(3))
        for cid, name in ((self.a, "Boss"), (self.b, "Kit"), (self.c, "Ari")):
            C.save(cid, C.new_card(name), self.ws)
        C.save_team({"default": self.a, "members": {self.a: [], self.b: [], self.c: []}}, self.ws)
        self.patches = [mock.patch.object(RC, "_dir", lambda: self.tmp / "rooms"),
                        mock.patch.object(C, "_default_ws", return_value=self.ws),
                        mock.patch.object(RC, "REPLY_TIMEOUT", 2)]
        for p in self.patches:
            p.start()
        self.seats = {}
        self.seat_patch = mock.patch.object(RC, "_seat", lambda r, cid: self.seats[cid])
        self.seat_patch.start()

    def tearDown(self):
        self.seat_patch.stop()
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def talk(self, rid, text):
        msg = RC.say(rid, text)
        for t in threading.enumerate():
            if t.name == "room-" + rid:
                t.join(10)
        return msg

    def test_a_room_needs_two_real_characters_and_a_known_strategy(self):
        with self.assertRaises(ValueError):
            RC.create("x", [self.a])
        with self.assertRaises(ValueError):
            RC.create("x", [self.a, "char_nope"])
        with self.assertRaises(ValueError):
            RC.create("x", [self.a, self.b], strategy="loud")
        r = RC.create("", [self.a, self.b, self.b])
        self.assertEqual((r["members"], r["mode"]), ([self.a, self.b], "work"))
        self.assertEqual([x["id"] for x in RC.rooms()], [r["id"]])

    def test_mentions_are_members_by_name_in_order(self):
        names = {self.b: "Kit", self.c: "Ari"}
        self.assertEqual(RC.mentions("@ari then @Kit, @ari again and @nobody", [self.b, self.c], names), [self.c, self.b])

    def test_who_answers(self):
        r = {"members": [self.a, self.b, self.c], "strategy": "natural"}
        self.assertEqual(RC.pick(r, [self.c], rng=random.Random(1), talk={self.a: 0, self.b: 0})[0], self.c,
                         "the mentioned one first")
        only = RC.pick(r, [], last=self.a, rng=random.Random(2), talk={self.a: 0, self.b: 0, self.c: 0})
        self.assertEqual(len(only), 1, "nobody keen: one at random, never silence")
        self.assertNotIn(self.a, only, "not the one who just spoke")
        self.assertEqual(RC.pick(dict(r, strategy="manual"), []), [])
        self.assertEqual(RC.pick(dict(r, strategy="list"), [self.c], last=self.a), [self.c, self.b])

    def test_answers_are_capped_and_mentions_chain_within_the_limit(self):
        r = RC.create("desk", [self.a, self.b, self.c], strategy="manual")
        self.seats = {self.b: FakeSeat("s-b", ["@Ari your turn", "and done"]),
                      self.c: FakeSeat("s-c", ["@Kit back to you"] * 3)}
        self.talk(r["id"], "@Kit hi")
        said = [(m["who"], m["text"]) for m in RC.messages(r["id"])]
        self.assertEqual([w for w, _ in said], ["user", self.b, self.c, self.b][:1 + RC.MAX_REPLIES])
        self.assertLessEqual(len(said) - 1, RC.MAX_REPLIES)

    def test_each_member_hears_only_what_was_said_since_it_last_spoke(self):
        r = RC.create("desk", [self.a, self.b], strategy="manual")
        self.seats = {self.b: FakeSeat("s-b", ["first", "second"])}
        self.talk(r["id"], "@Kit one")
        self.talk(r["id"], "@Kit two")
        second = self.seats[self.b].prompts[1]
        self.assertIn("@Kit two", second)
        self.assertNotIn("@Kit one", second, "already heard")
        self.assertIn("Do not use tools", second)

    def test_a_busy_room_refuses_a_second_message(self):
        r = RC.create("desk", [self.a, self.b], strategy="manual")
        RC._busy[r["id"]] = True
        with self.assertRaises(RuntimeError):
            RC.say(r["id"], "hi")
        RC._busy.pop(r["id"], None)

    def test_routes(self):
        code, body = RC.api("POST", "/api/rooms", {"name": "desk", "members": [self.a, self.b]})
        rid = body["room"]["id"]
        self.assertEqual(code, 200)
        self.assertEqual(RC.api("GET", "/api/rooms", None)[1]["rooms"][0]["id"], rid)
        self.assertEqual(RC.api("GET", "/api/rooms/%s/after/0" % rid, None)[1]["names"][self.b], "Kit")
        self.assertEqual(RC.api("GET", "/api/rooms/room_000000000000", None)[0], 404)
        self.assertEqual(RC.api("POST", "/api/rooms/%s/say" % rid, {"text": ""})[0], 400)
        self.assertIsNone(RC.api("GET", "/api/sessions", None))


class RoomSeats(unittest.TestCase):
    """A member's room session is its own: mode "room" survives a reload and is never the character's active chat."""

    def test_room_mode_is_kept_and_never_active(self):
        import session as S
        tmp = Path(tempfile.mkdtemp())
        saved = S.SESSIONS
        S.SESSIONS = tmp / "sessions"                # never the live sessions folder
        try:
            reg = S.Registry()
            work = reg.create(character="", mode="work")
            seat = reg.create(character="", mode="room")
            self.assertEqual(seat.mode, "room")
            self.assertFalse(seat.is_private)
            self.assertEqual(S.AgentSession(seat.sid).mode, "room", "reloaded from its meta")
            self.assertEqual(reg.get_active("").sid, work.sid, "the newest session is a room seat, still not active")
            self.assertTrue((tmp / "sessions" / seat.sid).is_dir())
        finally:
            S.SESSIONS = saved
            shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
