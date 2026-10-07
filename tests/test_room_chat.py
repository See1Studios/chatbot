"""Group rooms, first step: work rooms (room_chat.py, plan evt/E, decision E4). Who answers (SillyTavern activation:
natural / list / manual, @mentions first), at most MAX_REPLIES answers per user message with at most MAX_CHAIN from
characters calling each other, each member hearing only what was said since it last spoke, from its own hidden
"room" session that never becomes its one-to-one chat.
Run: engine/run-tests.sh test_room_chat
"""
import json
import os
import random
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
os.environ.setdefault("CHATBOT_EVENTS_DIR", tempfile.mkdtemp())   # never the live mailbox
os.environ.setdefault("CHATBOT_DIALOGS_DIR", tempfile.mkdtemp())  # nor the live dialogs
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


    def test_a_mention_after_a_letter_that_grows_when_lowered(self):
        # review of #526: "İ".lower() is two code points, so positions from the text did not hold in its lower case
        names = {self.b: "Kit", self.c: "Ari"}
        self.assertEqual(RC.mentions("İİİ @Ari 안녕 @kit", [self.b, self.c], names), [self.c, self.b])   # l10n-ok
    def test_mentions_take_names_with_spaces_longest_first(self):
        names = {self.a: "Yae", self.b: "Yae Miko", self.c: "Ari"}
        members = [self.a, self.b, self.c]
        self.assertEqual(RC.mentions("hi @yae miko, and @Ari", members, names), [self.b, self.c])
        self.assertEqual(RC.mentions("@Yae Mikoto? no, @Yae!", members, names), [self.a], "a name ends at a word end")
        self.assertEqual(RC.mentions("@%s by id" % self.c, members, names), [self.c])

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
        self.assertEqual((RC.MAX_REPLIES, RC.MAX_CHAIN), (6, 4), "room for back-and-forth (ticket #526)")
        r = RC.create("desk", [self.a, self.b, self.c], strategy="manual")
        self.seats = {self.b: FakeSeat("s-b", ["@Ari your turn", "and done"]),
                      self.c: FakeSeat("s-c", ["@Kit back to you"] * 3)}
        self.talk(r["id"], "@Kit hi")
        said = [(m["who"], m["text"]) for m in RC.messages(r["id"])]
        self.assertEqual([w for w, _ in said], ["user", self.b, self.c, self.b])
        r = RC.create("ping", [self.a, self.b, self.c], strategy="manual")
        self.seats = {self.b: FakeSeat("s-b2", ["@Ari go"] * 9), self.c: FakeSeat("s-c2", ["@Kit go"] * 9)}
        self.talk(r["id"], "@Kit hi")
        who = [m["who"] for m in RC.messages(r["id"])][1:]
        self.assertEqual(who, [self.b, self.c] * 2 + [self.b], "the first answer, then MAX_CHAIN called ones")
        r = RC.create("all", [self.a, self.b, self.c], strategy="list")
        loud = "@Boss @Kit @Ari"
        self.seats = {x: FakeSeat("s-%s" % x, [loud] * 9) for x in (self.a, self.b, self.c)}
        self.talk(r["id"], "hi")
        self.assertEqual(len(RC.messages(r["id"])) - 1, RC.MAX_REPLIES, "never more than MAX_REPLIES answers")

    def test_the_member_answering_is_known_while_it_answers(self):
        # the page shows that member typing (static/app-rooms.js roomTyping)
        r = RC.create("desk", [self.a, self.b], strategy="manual")
        seen = []

        class Seat(FakeSeat):
            def send(seat, text):
                seen.append(RC._speaking.get(r["id"]))
                return FakeSeat.send(seat, text)

        self.seats = {self.b: Seat("s-b", ["ok"])}
        self.talk(r["id"], "@Kit hi")
        self.assertEqual(seen, [self.b])
        self.assertEqual(RC.api("GET", "/api/rooms/%s/after/0" % r["id"], None)[1]["speaking"], "")   # done

    def test_each_member_hears_only_what_was_said_since_it_last_spoke(self):
        r = RC.create("desk", [self.a, self.b], strategy="manual")
        self.seats = {self.b: FakeSeat("s-b", ["first", "second"])}
        self.talk(r["id"], "@Kit one")
        self.talk(r["id"], "@Kit two")
        second = self.seats[self.b].prompts[1]
        self.assertIn("@Kit two", second)
        self.assertNotIn("@Kit one", second, "already heard")
        self.assertIn("Do not use tools", second)
        self.assertIn("keep the back-and-forth going", second, "members react to each other")
        self.assertIn("@mention them by name", second, "and hand the word on when the talk turns")

    def test_a_member_who_speaks_has_read_the_room(self):
        import dialog_log
        r = RC.create("desk", [self.a, self.b], strategy="manual")
        self.seats = {self.b: FakeSeat("s-b", ["first"])}
        self.talk(r["id"], "@Kit one")
        self.assertEqual(dialog_log.unread(self.b, r["id"]), (0, 0))
        self.assertEqual(dialog_log.read(self.b, r["id"]), 2)
        self.assertEqual(dialog_log.seen("s-b", self.b, r["id"]), 2)
        self.assertEqual(dialog_log.unread(self.a, r["id"]), (2, 0), "the other member has not")

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
        self.assertIsNone(RC.rooms()[0]["last"])                       # nothing said yet
        RC._append(rid, self.b, "y" * 200, [])
        last = RC.rooms()[0]["last"]                                   # the talk list's line (ux/S1)
        self.assertEqual((last["who"], len(last["text"])), (self.b, 80))
        self.assertGreater(last["at"], 0)
        self.assertEqual(RC.api("GET", "/api/rooms/%s/after/0" % rid, None)[1]["names"][self.b], "Kit")
        self.assertEqual(RC.api("GET", "/api/rooms/%s/after/0" % rid, None)[1]["speaking"], "")   # nobody is answering
        self.assertEqual(RC.api("GET", "/api/rooms/room_000000000000", None)[0], 404)
        self.assertEqual(RC.api("POST", "/api/rooms/%s/say" % rid, {"text": ""})[0], 400)
        self.assertIsNone(RC.api("GET", "/api/sessions", None))

    def test_deleted_characters_are_filtered_on_room_load(self):
        r = RC.create("desk", [self.a, self.b, self.c], strategy="manual")
        rid = r["id"]
        # Seed dummy seat and seen for c
        r_data = json.loads(RC._room_path(rid).read_text(encoding="utf-8"))
        r_data["seats"][self.c] = "sess_dummy"
        r_data["seen"][self.c] = 5
        RC._write_json(RC._room_path(rid), r_data)

        # Remove character card for c
        card_file = C.card_path(self.c)
        if card_file.is_file():
            card_file.unlink()

        # Loading room should filter c and heal the file
        loaded = RC.room(rid)
        self.assertNotIn(self.c, loaded["members"])
        self.assertEqual(loaded["members"], [self.a, self.b])
        self.assertNotIn(self.c, loaded.get("seats", {}))
        self.assertNotIn(self.c, loaded.get("seen", {}))

        # Check persisted file on disk is healed
        disk_data = json.loads(RC._room_path(rid).read_text(encoding="utf-8"))
        self.assertNotIn(self.c, disk_data["members"])
        self.assertNotIn(self.c, disk_data.get("seats", {}))
        self.assertNotIn(self.c, disk_data.get("seen", {}))

    def test_deleted_character_speaker_and_room_names(self):
        import dialog_log
        r = RC.create("desk", [self.a, self.b, self.c], strategy="manual")
        rid = r["id"]
        # Append a message from c (e.g. before c was deleted)
        RC._append(rid, self.c, "legacy talk", [])
        # Delete c's card
        card_file = C.card_path(self.c)
        if card_file.is_file():
            card_file.unlink()

        # dialog_log.speaker should return (unknown)
        self.assertEqual(dialog_log.speaker(self.c), "(unknown)")

        # GET /api/rooms/<rid> should include c in names as (unknown)
        code, body = RC.api("GET", f"/api/rooms/{rid}", None)
        self.assertEqual(code, 200)
        self.assertEqual(body["names"].get(self.c), "(unknown)")
        self.assertEqual(body["names"].get(self.a), "Boss")

    def test_room_update_and_members_management(self):
        r = RC.create("desk", [self.a, self.b], strategy="manual")
        rid = r["id"]

        # Strategy and name update via PATCH
        code, body = RC.api("PATCH", f"/api/rooms/{rid}", {"strategy": "natural", "name": "new desk"})
        self.assertEqual(code, 200)
        self.assertEqual(body["room"]["strategy"], "natural")
        self.assertEqual(body["room"]["name"], "new desk")

        # Invite c via POST /members
        code, body = RC.api("POST", f"/api/rooms/{rid}/members", {"add": self.c})
        self.assertEqual(code, 200)
        self.assertEqual(body["room"]["members"], [self.a, self.b, self.c])

        # Kick b via POST /members
        code, body = RC.api("POST", f"/api/rooms/{rid}/members", {"remove": self.b})
        self.assertEqual(code, 200)
        self.assertEqual(body["room"]["members"], [self.a, self.c])

        # Cannot reduce below 2 members
        code, body = RC.api("POST", f"/api/rooms/{rid}/members", {"remove": self.c})
        self.assertEqual(code, 400)
        self.assertIn("at least two characters", body["error"])


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
            self.assertNotIn(seat.sid, [x["id"] for x in reg.list()], "the sessions tab does not list room seats")
            self.assertIn(work.sid, [x["id"] for x in reg.list()])
        finally:
            S.SESSIONS = saved
            shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
