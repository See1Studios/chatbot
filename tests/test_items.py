"""Items in private mode (composer-plus-menu plus/F, items.py; private-mode §3 first step). "Item", not "gift"
(operator, 2026-09-28): an item is given or used. The engine judges it against the character's item_prefs; giving
moves affection (kept beside the card in state.json, never in the shareable card), the same gift twice is worth less,
three gifts a day; using tells the character the verdict and moves nothing. Only a private session can give or use,
the character is told once on the next message, the page reads the note as a chip, a picture falls back to the
engine placeholder, and the picker is a coverflow.
Run: python3 -m unittest tests.test_items  (from services/chatbot)
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
import items as I  # noqa: E402

NOON = time.mktime((2026, 9, 28, 12, 0, 0, 0, 0, -1))


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        shutil.copy(ROOT / "data" / "workspace" / "items.json", self.ws / "items.json")
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("여우", description="d", item_prefs={"loves": ["flower"], "likes": ["sweet"],
                                                                         "dislikes": ["game", "grooming"]}), self.ws)
        I._pending.clear()

    def tearDown(self):
        I._pending.clear()
        shutil.rmtree(self.ws, ignore_errors=True)

    def act(self, iid, action="give", at=NOON):
        return I.act(self.cid, iid, action, ws=self.ws, now=at)


class Catalog(Base):
    def test_items_say_what_can_be_done_with_them(self):
        by = {x["id"]: x for x in I.catalog(self.ws)}
        self.assertEqual(by["rose-bouquet"]["actions"], ["give"])
        self.assertEqual(by["comb"]["actions"], ["use"])
        self.assertEqual(set(by["blanket"]["actions"]), {"give", "use"})
        self.assertTrue(by["comb"]["use"], "a usable item says what using it does")
        self.assertFalse(by["comb"]["has_image"], "no picture yet: the placeholder")

    def test_a_picture_falls_back_to_the_placeholder(self):
        self.assertEqual(I.image_file("comb", self.ws), (I.PLACEHOLDER, True))
        (self.ws / "items").mkdir()
        (self.ws / "items" / "comb.webp").write_bytes(b"x")
        self.assertEqual(I.image_file("comb", self.ws), (self.ws / "items" / "comb.webp", False))
        self.assertEqual(I.image_file("../card", self.ws), (I.PLACEHOLDER, True))
        self.assertTrue(I.PLACEHOLDER.is_file())
        import character_art
        code, body, ctype, _ = character_art.handle("/api/items/comb/image", {})
        self.assertEqual((code, ctype), (200, "image/webp"))

    def test_the_default_list_is_the_template_s(self):
        self.assertEqual((ROOT / "data" / "workspace" / "items.json").read_bytes(),
                         (ROOT / "templates" / "workspace" / "items.json").read_bytes())


class Judge(Base):
    def test_the_character_s_likes_decide_not_the_model(self):
        prefs = I.prefs_of(C.load(self.cid, self.ws))
        item = lambda iid: next(x for x in I.catalog(self.ws) if x["id"] == iid)  # noqa: E731
        self.assertEqual(I.judge(item("rose-bouquet"), prefs), "loves")
        self.assertEqual(I.judge(item("strawberry-cake"), prefs), "likes")
        self.assertEqual(I.judge(item("new-game"), prefs), "dislikes")
        self.assertEqual(I.judge(item("warm-latte"), prefs), "neutral")
        self.assertEqual(I.judge({"tags": ["flower", "game"]}, prefs), "loves", "a loved tag wins over a disliked one")

    def test_older_gift_prefs_are_still_read(self):
        old = C.new_card("구", description="d", gift_prefs={"loves": ["book"]})
        self.assertEqual(I.prefs_of(old)["loves"], ["book"])

    def test_levels_follow_private_mode_3_1(self):
        self.assertEqual([I.level_of(p)["level"] for p in (0, 19, 20, 49, 50, 79, 80, 99, 100)],
                         [1, 1, 2, 2, 3, 3, 4, 4, 5])


class GiveAndUse(Base):
    def test_giving_moves_affection_beside_the_card_not_in_it(self):
        card_before = C.card_path(self.cid, self.ws).read_bytes()
        r = self.act("rose-bouquet")
        self.assertEqual((r["verdict"], r["delta"], r["points"], r["level"]), ("loves", 5, 5, 1))
        st = json.loads(I.state_path(self.cid, self.ws).read_text(encoding="utf-8"))
        self.assertEqual((st["affection"]["points"], st["given"][-1]["id"]), (5, "rose-bouquet"))
        self.assertEqual(C.card_path(self.cid, self.ws).read_bytes(), card_before)

    def test_using_tells_the_verdict_and_moves_nothing(self):
        r = self.act("comb", "use")
        self.assertEqual((r["verdict"], r["delta"], r["points"]), ("dislikes", 0, 0))
        for i in range(10):                                     # no daily limit on using
            self.act("umbrella", "use", NOON + i)
        self.assertEqual(self.act("rose-bouquet")["left_today"], 2, "uses do not spend gifts")

    def test_an_item_does_only_what_it_can(self):
        with self.assertRaises(I.ItemError):
            self.act("comb", "give")
        with self.assertRaises(I.ItemError):
            self.act("rose-bouquet", "use")
        with self.assertRaises(I.ItemError):
            self.act("diamond-car")

    def test_the_same_gift_again_is_worth_less_and_three_a_day(self):
        self.assertEqual(self.act("rose-bouquet")["delta"], 5)
        self.assertEqual(self.act("rose-bouquet", at=NOON + 60)["delta"], 2)
        self.assertEqual(self.act("new-game", at=NOON + 120)["delta"], -2)
        with self.assertRaises(I.ItemError):
            self.act("dango", at=NOON + 180)
        self.assertEqual(self.act("dango", at=NOON + 86400)["left_today"], 2)

    def test_gifts_written_before_the_rename_still_count(self):
        I.state_path(self.cid, self.ws).write_text(json.dumps(
            {"affection": {"points": 7}, "gifts": [{"id": "dango", "ts": NOON - 10, "verdict": "neutral", "delta": 1}]}))
        r = self.act("dango")
        self.assertEqual((r["before"], r["left_today"]), (7, 1), "yesterday-format record read and counted")


class Routes(Base):
    def post(self, sess, item="rose-bouquet", action="give"):
        real = I.act
        with mock.patch.object(I, "_session", return_value=sess), \
                mock.patch.object(I, "act", side_effect=lambda cid, iid, a: real(cid, iid, a, ws=self.ws, now=NOON)):
            return I.handle_post("/api/sessions/s1/item", {"item": item, "action": action})

    def test_only_a_private_session_can_give_or_use(self):
        self.assertEqual(self.post(types.SimpleNamespace(is_private=False, character=self.cid))[0], 400)
        self.assertEqual(I.take_pending("s1", "안녕"), "안녕")

    def test_the_character_is_told_once_on_the_next_message(self):
        code, body = self.post(types.SimpleNamespace(is_private=True, character=self.cid))
        self.assertEqual((code, body["result"]["verdict"]), (200, "loves"))
        text = I.take_pending("s1", "(🌹 장미 꽃다발을(를) 건넨다)")
        self.assertIn("[Item - host note: the user gave you 🌹 장미 꽃다발", text)
        self.assertIn("You love this.", text)
        self.assertEqual(I.take_pending("s1", "다음"), "다음")
        self.post(types.SimpleNamespace(is_private=True, character=self.cid), "comb", "use")
        self.assertIn("the user uses 🪮 빗", I.take_pending("s1", "(빗으로 머리를 천천히 빗겨준다)"))

    def test_the_server_wires_the_routes(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("text = items.take_pending(sid, chat_upload.take_pending(sid, text))", src)
        self.assertIsNone(I.handle_post("/api/sessions/s1/message", {}))
        self.assertIsNone(I.handle_get("/api/sessions/s1/history"))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Page(Base):
    def run_js(self, body):
        src = (ROOT / "static" / "app-item.js").read_text(encoding="utf-8")
        head = src[src.index("const ITEM_NOTE"):src.index("function renderItemChip")]
        flow = src[src.index("const FLOW_GAP"):src.index("function closeItemPicker")]  # constants, flowStyle, wheelEase, flingTarget
        out = subprocess.run(["node", "-e", head + flow + "\n" + body], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        return json.loads(out.stdout)

    def test_notes_are_chips_for_items_and_for_gifts_written_before(self):
        given = "(🌹 장미 꽃다발을(를) 건넨다)\n\n" + I.host_note(self.act("rose-bouquet"))
        used = "(빗으로 머리를 천천히 빗겨준다)\n\n" + I.host_note(self.act("comb", "use"))
        old = ("(🍡 경단을(를) 건넨다)\n\n[Gift - host note: the user gave you 🍡 경단 (sweet, traditional). You like "
               "this. Affection 1 -> 4 (Lv.1 어색한 동료). React in character to receiving it; never mention points or levels.]")
        got = self.run_js("console.log(JSON.stringify(%s.map(splitItemNote)));" % json.dumps([given, used, old, "그냥"], ensure_ascii=False))
        self.assertEqual(got[0], {"text": "(🌹 장미 꽃다발을(를) 건넨다)", "item": {"icon": "🌹", "name": "장미 꽃다발"}})
        self.assertEqual(got[1]["item"], {"icon": "🪮", "name": "빗"})
        self.assertEqual(got[2]["item"], {"icon": "🍡", "name": "경단"})
        self.assertEqual(got[3], {"text": "그냥", "item": None})

    def test_the_coverflow_is_the_old_mac_one(self):
        got = self.run_js("console.log(JSON.stringify([-7,-2,-1,0,1,2,6].map(d => flowStyle(d, false)).concat([flowStyle(1, true), flowStyle(0.5, false)])));")
        far, l2, l1, mid, r1, r2, r6, reduced, half = got
        self.assertTrue(far["hidden"])
        self.assertIn("translateX(0%) rotateY(0deg) scale(1)", mid["transform"], "the middle faces the reader")
        self.assertIn("rotateY(70deg)", l1["transform"])
        self.assertIn("rotateY(-70deg)", r1["transform"])
        self.assertIn("rotateY(-70deg)", r2["transform"], "a stack keeps the same turn")
        self.assertIn("translateX(80%)", r1["transform"], "a clear gap from the middle")
        self.assertIn("translateX(104%)", r2["transform"], "then packed close (operator: a little wider, 2026-09-28)")
        self.assertFalse(r6["hidden"])
        self.assertGreater(mid["z"], r1["z"])
        self.assertGreater(r1["z"], r2["z"])
        self.assertTrue(mid["shade"] > r1["shade"] > r2["shade"], "further back is darker")
        self.assertIn("rotateY(0deg)", reduced["transform"], "reduced motion: no turning")
        self.assertIn("rotateY(-35deg)", half["transform"], "the card crossing the gap turns as it comes")

    def test_one_wheel_notch_is_drawn_in_steps_not_one_jump(self):
        # 2026-09-28: a notch moved the flow straight to its end and the frames between never showed
        got = self.run_js("let p = 0, frames = []; while (p !== 1 && frames.length < 60) { p = wheelEase(p, 1); frames.push(p); }"
                          " console.log(JSON.stringify(frames));")
        self.assertGreater(len(got), 5, "several frames between one item and the next")
        self.assertTrue(all(b > a for a, b in zip(got, got[1:])), "always forward")
        self.assertEqual(got[-1], 1, "and it lands exactly on the item")

    def test_a_flick_glides_further_than_a_let_go(self):
        got = self.run_js("console.log(JSON.stringify([flingTarget(2.3, 0, 19), flingTarget(2.3, 0.004, 19), "
                          "flingTarget(2.3, 0.03, 19), flingTarget(2.3, -0.05, 19), flingTarget(17.8, 0.05, 19)]));")
        self.assertEqual(got, [2, 3, 11, 0, 18], "rest, one on, a long glide, clamped at both ends")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheItemIsDrawnOnce(Base):
    def test_the_server_ack_adopts_the_bubble_already_drawn(self):
        ack = "(🎮 같이 할 게임을(를) 건넨다)\n\n" + I.host_note(self.act("new-game"))
        item_js = (ROOT / "static" / "app-item.js").read_text(encoding="utf-8")
        msg_js = (ROOT / "static" / "app-messages.js").read_text(encoding="utf-8")
        g = item_js[item_js.index("const ITEM_NOTE"):item_js.index("function renderItemChip")]
        m = msg_js[msg_js.index("function bubbleOwnText"):msg_js.index("function inFlightAssistant")]
        harness = g + "\n" + m + r"""
const text = (v) => ({ nodeType: 3, nodeValue: v });
const bubble = { childNodes: [text('✦ 🎮 같이 할 게임을(를) 건넨다'), { nodeType: 1, textContent: '🎮 같이 할 게임' }],
                 dataset: {}, classList: { contains: (c) => c === 'action' } };
const logEl = { querySelectorAll: () => [bubble] };
console.log(JSON.stringify({ adopted: adoptBareUserBubble(ACK, 123.5), ts: bubble.dataset.ts }));
""".replace("ACK", json.dumps(ack, ensure_ascii=False))
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertEqual(json.loads(out.stdout), {"adopted": True, "ts": "123.5"})


if __name__ == "__main__":
    unittest.main()
