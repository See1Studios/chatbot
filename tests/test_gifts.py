"""Gifts in private mode (composer-plus-menu plus/F, gifts.py; private-mode §3 first step): the engine judges a gift
against the character's gift_prefs, affection is kept beside the card in state.json (never in the shareable card),
the same gift twice is worth less, three gifts a day, only a private session can give, and the character is told
the verdict once, on the next message. The page reads the same note as a chip.
Run: python3 -m unittest tests.test_gifts  (from services/chatbot)
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import gifts as G  # noqa: E402

NOON = time.mktime((2026, 9, 28, 12, 0, 0, 0, 0, -1))


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        shutil.copy(ROOT / "data" / "workspace" / "gifts.json", self.ws / "gifts.json")
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("여우", description="d", gift_prefs={"loves": ["flower"], "likes": ["sweet"],
                                                                         "dislikes": ["game"]}), self.ws)
        G._pending.clear()

    def tearDown(self):
        G._pending.clear()
        shutil.rmtree(self.ws, ignore_errors=True)

    def give(self, gid, at=NOON):
        return G.give(self.cid, gid, ws=self.ws, now=at)


class Judge(Base):
    def test_the_character_s_likes_decide_not_the_model(self):
        prefs = G.prefs_of(C.load(self.cid, self.ws))
        gift = lambda gid: next(g for g in G.catalog(self.ws) if g["id"] == gid)  # noqa: E731
        self.assertEqual(G.judge(gift("rose-bouquet"), prefs), "loves")
        self.assertEqual(G.judge(gift("strawberry-cake"), prefs), "likes")
        self.assertEqual(G.judge(gift("new-game"), prefs), "dislikes")
        self.assertEqual(G.judge(gift("warm-latte"), prefs), "neutral")
        self.assertEqual(G.judge({"tags": ["flower", "game"]}, prefs), "loves", "a loved tag wins over a disliked one")
        self.assertEqual(G.judge(gift("rose-bouquet"), G.prefs_of({})), "neutral", "no prefs: neutral")

    def test_levels_follow_private_mode_3_1(self):
        self.assertEqual([G.level_of(p)["level"] for p in (0, 19, 20, 49, 50, 79, 80, 99, 100)],
                         [1, 1, 2, 2, 3, 3, 4, 4, 5])


class Give(Base):
    def test_affection_is_kept_beside_the_card_not_in_it(self):
        card_before = C.card_path(self.cid, self.ws).read_bytes()
        r = self.give("rose-bouquet")
        self.assertEqual((r["verdict"], r["delta"], r["points"], r["level"]), ("loves", 5, 5, 1))
        st = json.loads(G.state_path(self.cid, self.ws).read_text(encoding="utf-8"))
        self.assertEqual(st["affection"]["points"], 5)
        self.assertEqual(st["gifts"][-1]["id"], "rose-bouquet")
        self.assertEqual(C.card_path(self.cid, self.ws).read_bytes(), card_before, "the card is shareable; untouched")

    def test_the_same_gift_again_is_worth_less_and_a_disliked_one_costs(self):
        self.assertEqual(self.give("rose-bouquet")["delta"], 5)
        self.assertEqual(self.give("rose-bouquet", NOON + 60)["delta"], 2)
        self.assertEqual(self.give("new-game", NOON + 120)["delta"], -2)

    def test_three_a_day_then_tomorrow(self):
        for i in range(3):
            self.give("warm-latte" if i % 2 else "dango", NOON + i)
        with self.assertRaises(G.GiftError):
            self.give("dango", NOON + 10)
        self.assertEqual(self.give("dango", NOON + 86400)["left_today"], 2)

    def test_points_stay_between_zero_and_the_max(self):
        self.assertEqual(self.give("new-game")["points"], 0)
        st = G.read_state(self.cid, self.ws)
        st["affection"]["points"] = 99
        G.write_state(self.cid, st, self.ws)
        self.assertEqual((self.give("rose-bouquet", NOON + 1)["points"], G.level_of(100)["title"]), (100, "완전한 유대"))

    def test_an_unknown_gift_is_refused(self):
        with self.assertRaises(G.GiftError):
            self.give("diamond-car")


class Routes(Base):
    def session(self, private=True):
        return types.SimpleNamespace(is_private=private, character=self.cid)

    def post(self, sess, gift="rose-bouquet"):
        real_give = G.give
        with mock.patch.object(G, "_session", return_value=sess), \
                mock.patch.object(G, "give", side_effect=lambda cid, gid: real_give(cid, gid, ws=self.ws, now=NOON)):
            return G.handle_post("/api/sessions/s1/gift", {"gift": gift})

    def test_only_a_private_session_can_give(self):
        self.assertEqual(self.post(self.session(private=False))[0], 400)
        self.assertEqual(G.take_pending("s1", "안녕"), "안녕")

    def test_the_character_is_told_once_on_the_next_message(self):
        code, body = self.post(self.session())
        self.assertEqual((code, body["result"]["verdict"]), (200, "loves"))
        text = G.take_pending("s1", "(🌹 장미 꽃다발을 건넨다)")
        self.assertTrue(text.startswith("(🌹 장미 꽃다발을 건넨다)\n\n[Gift - host note: the user gave you 🌹 장미 꽃다발"))
        self.assertIn("You love this.", text)
        self.assertIn("never mention points", text)
        self.assertEqual(G.take_pending("s1", "다음"), "다음")

    def test_other_paths_are_not_ours(self):
        self.assertIsNone(G.handle_post("/api/sessions/s1/message", {}))
        self.assertIsNone(G.handle_get("/api/sessions/s1/history"))

    def test_the_message_route_appends_the_note(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("text = gifts.take_pending(sid, chat_upload.take_pending(sid, text))", src)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PageReadsTheNote(Base):
    def test_the_note_is_a_chip_and_the_action_stays_an_action(self):
        r = self.give("rose-bouquet")
        text = "(🌹 장미 꽃다발을 건넨다)\n\n" + G.host_note(r)
        src = (ROOT / "static" / "app-gift.js").read_text(encoding="utf-8")
        a, b = src.index("const GIFT_NOTE"), src.index("function renderGiftChip")
        js = src[a:b] + "\nconsole.log(JSON.stringify([splitGiftNote(%s), splitGiftNote('그냥 말')]));" % json.dumps(text, ensure_ascii=False)
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        got = json.loads(out.stdout)
        self.assertEqual(got[0], {"text": "(🌹 장미 꽃다발을 건넨다)", "gift": {"icon": "🌹", "name": "장미 꽃다발"}})
        self.assertEqual(got[1], {"text": "그냥 말", "gift": None})


if __name__ == "__main__":
    unittest.main()
