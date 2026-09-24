"""workspace_status.experts_api: the team tab reads and edits each expert's brain list and the PD's
(EXPERTS_STATUS_v1, docs/plans/multi-agent-worktree-delegation.md §11).
Run: python3 -m unittest tests.test_experts_api  (from services/chatbot)
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import workspace_status as W  # noqa: E402


class ExpertsApiTest(unittest.TestCase):
    def setUp(self):
        import characters
        self.C = characters
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.root / "data" / "workspace"
        self.cid = characters.new_id()
        characters.save(self.cid, characters.new_card("S", "staff", display={"title": "막내"},
                                                      brains={"work": [{"provider": "agy", "model": "gemini-3.1-pro-high"}]}),
                        self.ws)
        (self.root / "protected_paths.json").write_text(json.dumps({"protect": ["data/workspace/AGENTS.md"]}),
                                                        encoding="utf-8")
        self.saved = (W.ROOT, W.WORKSPACE)
        W.ROOT, W.WORKSPACE = self.root, self.ws

    def tearDown(self):
        W.ROOT, W.WORKSPACE = self.saved

    def put(self, who, chain):
        return W.experts_api("PUT", "/api/experts/%s/brain" % who, {"chain": chain})

    def test_lists_every_character_alike_with_its_roles_and_brains(self):
        code, body = W.experts_api("GET", "/api/experts", None)
        self.assertEqual(code, 200)
        self.assertEqual([(e["id"], e["roles"], e["title"]) for e in body["experts"]], [(self.cid, ["staff"], "막내")])
        self.assertEqual(body["experts"][0]["chain"][0]["model"], "gemini-3.1-pro-high")
        self.assertIn("agy", body["providers"])

    def put_team(self, body):
        return W.experts_api("PUT", "/api/experts/team", body)

    def test_arranging_the_team(self):
        (self.ws / "roles" / "pd").mkdir(parents=True)
        (self.ws / "roles" / "pd" / "role.md").write_text("---\ntitle: PD\ntools: delegate\n---\nx\n", encoding="utf-8")
        other = self.C.new_id()
        self.C.save(other, self.C.new_card("O"), self.ws)
        code, body = self.put_team({"default": other, "members": {other: ["pd"], self.cid: []}})
        self.assertEqual(code, 200, body)
        self.assertEqual(self.C.default_character(self.ws), other)
        self.assertEqual((self.C.by_role("pd", self.ws), self.C.roles_of(self.cid, self.ws)), (other, []))
        rows = W.experts_api("GET", "/api/experts", None)[1]
        self.assertEqual([(e["id"], e["default"], e["roles"]) for e in rows["experts"]],
                         [(other, True, ["pd"]), (self.cid, False, [])])
        self.assertEqual(rows["roles"], [{"role": "pd", "title": "PD", "tools": ["delegate"], "skills": []}])
        for bad in ({"default": self.C.new_id(), "members": {}}, {"default": other, "members": {other: ["nope"]}},
                    {"default": other, "members": {self.C.new_id(): ["pd"]}}, {"default": other, "members": []}):
            self.assertEqual(self.put_team(bad)[0], 400, bad)

    def test_saving_a_brain_list(self):
        code, body = self.put(self.cid, [{"provider": "agy", "model": "gemini-3.8-flash-high", "timeout": 45},
                                         {"provider": "codex", "model": ""}])
        self.assertEqual(code, 200, body)
        card = self.C.load(self.cid, self.ws)
        self.assertEqual(self.C.brains(card), [{"provider": "agy", "model": "gemini-3.8-flash-high", "timeout": 45},
                                               {"provider": "codex", "model": ""}])
        self.assertEqual(card["data"]["name"], "S")                       # the rest of the card is untouched
        self.assertEqual(self.put("pd", [{"provider": "agy"}])[0], 404)   # no pd-brain.json any more (CARD_ONLY_v1)

    def test_bad_lists_and_unknown_characters_are_refused(self):
        for chain in ([], [{"provider": "nope"}], [{"provider": "agy", "model": "a b"}],
                      [{"provider": "agy", "timeout": 99999}], [{"provider": "agy"}] * 7, "agy"):
            self.assertEqual(self.put(self.cid, chain)[0], 400, chain)
        self.assertEqual(self.put(self.C.new_id(), [{"provider": "agy"}])[0], 404)
        self.assertEqual(self.put("staff", [{"provider": "agy"}])[0], 404)        # ids, not roles
        self.assertEqual(W.experts_api("PUT", "/api/experts/../brain", {"chain": []})[0], 404)

    def test_a_protected_or_unreadable_registry_makes_it_read_only(self):
        (self.root / "protected_paths.json").write_text(json.dumps({"protect": ["data/workspace/characters/"]}))
        self.assertEqual(self.put(self.cid, [{"provider": "agy"}])[0], 403)
        (self.root / "protected_paths.json").unlink()
        self.assertEqual(self.put(self.cid, [{"provider": "agy"}])[0], 403)


if __name__ == "__main__":
    unittest.main()
