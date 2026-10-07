"""NAME_CHANGE_v1: a character renamed by hand is carried by the engine -- every card's text, visual sheet and lorebook
in one pass (a swap must not undo itself), a note for the brains, and older talk shown with today's names while the
record keeps what was said. Talk after the change is left alone.
Run: engine/run-tests.sh test_character_names
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import character_names as N  # noqa: E402
import characters as C  # noqa: E402

T = 1790000000.0


class Rename(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve() / "workspace"
        self.a, self.b, self.c = sorted(C.new_id() for _ in range(3))
        for cid, name, sample in ((self.a, "리리", "{{user}}: 리리야, 서버 봤어?"),
                                  (self.b, "코코", "{{user}}: 코코는 몇 살이야?"),
                                  (self.c, "노노", "노노는 리리와 코코를 챙긴다.")):
            card = C.new_card(name)
            card["data"]["mes_example"] = sample
            C.save(cid, card, self.ws)
        (C.card_path(self.b, self.ws).parent / "visual.md").write_text(
            "# 코코 visual lock sheet\n- Distinct from 노노 and 리리 (bunny ears)\n", encoding="utf-8")
        C.lorebook_path(self.a, self.ws).write_text(json.dumps({"entries": [{"keys": ["리리"], "content": "리리의 방"}]},
                                                               ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.ws.parent, ignore_errors=True)

    def rename(self, cid, name):
        card = C.load(cid, self.ws)
        card["data"]["name"] = name
        C.save(cid, card, self.ws)

    def test_first_sight_only_remembers(self):
        self.assertEqual(N.reconcile(self.ws, now=T), [])
        self.assertEqual(C.ext(C.load(self.a, self.ws))["known_name"], "리리")
        self.assertEqual(N.reconcile(self.ws, now=T), [], "nothing changed")

    def test_a_swap_is_carried_everywhere_in_one_pass(self):
        N.reconcile(self.ws, now=T - 100)
        self.rename(self.a, "코코")
        self.rename(self.b, "리리")
        got = N.reconcile(self.ws, now=T)
        self.assertEqual(sorted((g["old"], g["new"]) for g in got), [("리리", "코코"), ("코코", "리리")])
        a, b, c = (C.load(x, self.ws)["data"] for x in (self.a, self.b, self.c))
        self.assertEqual(a["mes_example"], "{{user}}: 코코야, 서버 봤어?")
        self.assertEqual(b["mes_example"], "{{user}}: 리리는 몇 살이야?")
        self.assertEqual(c["mes_example"], "노노는 코코와 리리를 챙긴다.", "a swap does not undo itself")
        self.assertEqual((a["name"], b["name"]), ("코코", "리리"))
        sheet = (C.card_path(self.b, self.ws).parent / "visual.md").read_text(encoding="utf-8")
        self.assertEqual(sheet, "# 리리 visual lock sheet\n- Distinct from 노노 and 코코 (bunny ears)\n")
        lore = json.loads(C.lorebook_path(self.a, self.ws).read_text(encoding="utf-8"))
        self.assertEqual(lore["entries"][0], {"keys": ["코코"], "content": "코코의 방"})
        self.assertEqual(C.ext(C.load(self.a, self.ws))["renames"], [{"old": "리리", "new": "코코", "at": T}])
        self.assertEqual(N.reconcile(self.ws, now=T + 5), [], "carried once")
        note = N.note(self.ws)
        self.assertIn("코코 was called 리리", note)
        self.assertIn("리리 was called 코코", note)

    def test_older_talk_shows_todays_names_newer_talk_is_left(self):
        N.reconcile(self.ws, now=T - 100)
        self.rename(self.a, "코코")
        self.rename(self.b, "리리")
        N.reconcile(self.ws, now=T)
        self.assertEqual(N.as_of("리리가 코코에게 커피를", T - 10, self.ws), "코코가 리리에게 커피를")
        self.assertEqual(N.as_of("리리가 코코에게 커피를", T + 10, self.ws), "리리가 코코에게 커피를")
        self.assertEqual(N.as_of("초코코아", T - 10, self.ws), "초코코아", "inside a word: left alone")
        self.assertEqual(N.as_of("hi", None, self.ws), "hi")

    def test_a_second_rename_maps_from_the_name_it_had_then(self):
        N.reconcile(self.ws, now=T - 100)
        self.rename(self.c, "나나")
        N.reconcile(self.ws, now=T)
        self.rename(self.c, "니니")
        N.reconcile(self.ws, now=T + 100)
        self.assertEqual(N.as_of("노노 왔어", T - 10, self.ws), "니니 왔어")
        self.assertEqual(N.as_of("나나 왔어", T + 10, self.ws), "니니 왔어")
        self.assertEqual(N.as_of("니니 왔어", T + 200, self.ws), "니니 왔어")


class Shown(unittest.TestCase):
    def test_the_record_is_kept_what_is_shown_is_a_copy(self):
        import route_sessions as RS
        h = {"role": "assistant", "text": "리리야", "ts": 1.0}
        from unittest import mock
        with mock.patch.object(N, "as_of", return_value="코코야"):
            shown = RS._named_now(h)
        self.assertEqual(shown["text"], "코코야")
        self.assertEqual(h["text"], "리리야", "the session's own record keeps what was said")


if __name__ == "__main__":
    unittest.main()
