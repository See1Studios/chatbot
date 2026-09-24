"""workspace_status.instructions_api: the status tab shows every instruction the agent reads, and edits only
what the protected-path registry leaves unprotected (STATUS_INSTRUCTIONS_v1).
Run: python3 -m unittest tests.test_instructions_api  (from services/chatbot)
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import workspace_status as W  # noqa: E402


class InstructionsApiTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.root / "data" / "workspace"
        (self.ws / "memory").mkdir(parents=True)
        for name, text in (("AGENTS.md", "charter"), ("PROJECT.md", "procedure"),
                           ("SELF-MODIFY.md", "boundary")):
            (self.ws / name).write_text(text, encoding="utf-8")
        import characters
        self.cid = characters.new_id()
        characters.save(self.cid, characters.new_card("S", "staff"), self.ws)
        (self.ws / "memory" / "MEMORY.md").write_text("# Memory\n- a fact\n", encoding="utf-8")
        (self.root / "protected_paths.json").write_text(json.dumps(
            {"protect": ["data/workspace/AGENTS.md", "data/workspace/SELF-MODIFY.md"]}), encoding="utf-8")
        self.saved = (W.ROOT, W.WORKSPACE)
        W.ROOT, W.WORKSPACE = self.root, self.ws

    def tearDown(self):
        W.ROOT, W.WORKSPACE = self.saved

    def items(self):
        code, body = W.instructions_api("GET", "/api/instructions", None)
        self.assertEqual(code, 200)
        return {x["id"]: x for x in body["items"]}

    def put(self, iid, content):
        return W.instructions_api("PUT", "/api/instructions/" + iid, {"content": content})

    def test_everything_is_listed_with_its_layer_and_whether_it_is_editable(self):
        items = self.items()
        self.assertEqual({k: (v["layer"], v["editable"]) for k, v in items.items() if v["kind"] == "file"}, {
            "AGENTS.md": ("always", False), "MEMORY.md": ("always", True),
            "PROJECT.md": ("on_demand", True), "SELF-MODIFY.md": ("on_demand", False),
            "characters/%s/card.json" % self.cid: ("on_demand", True)})
        self.assertIn("data/workspace/AGENTS.md", items["AGENTS.md"]["reason"])
        self.assertEqual(items["PROJECT.md"]["content"], "procedure")      # whole, not a preview
        for gen in ("skills-index", "status-badge"):
            self.assertEqual((items[gen]["kind"], items[gen]["editable"]), ("generated", False))
        layers = [x["layer"] for x in W.agent_instructions()]
        self.assertEqual(layers, sorted(layers, key=lambda l: l != "always"))   # every-turn layer first

    def test_only_unprotected_files_can_be_saved(self):
        self.assertEqual(self.put("AGENTS.md", "x")[0], 403)
        self.assertEqual(self.put("SELF-MODIFY.md", "x")[0], 403)
        self.assertEqual(self.put("skills-index", "x")[0], 404)
        self.assertEqual(self.put("../../etc/passwd", "x")[0], 404)
        self.assertEqual(self.put("PROJECT.md", "   ")[0], 400)
        self.assertEqual((self.ws / "AGENTS.md").read_text(), "charter")

    def test_saving_an_editable_file_keeps_a_backup(self):
        code, body = self.put("PROJECT.md", "new procedure")
        self.assertEqual((code, body["ok"]), (200, True))
        self.assertEqual((self.ws / "PROJECT.md").read_text(), "new procedure")
        self.assertTrue(list(self.ws.glob("PROJECT.md.bak-selfstatus-*")))

    def test_a_character_card_id_arrives_url_encoded_and_must_stay_a_card(self):
        path = "/api/instructions/characters%%2F%s%%2Fcard.json" % self.cid
        self.assertEqual(W.instructions_api("PUT", path, {"content": "not json"})[0], 400)
        self.assertEqual(W.instructions_api("PUT", path, {"content": '{"spec": "other", "data": {}}'})[0], 400)
        import characters
        card = characters.new_card("S2", "staff")
        self.assertEqual(W.instructions_api("PUT", path, {"content": json.dumps(card)})[0], 200)
        self.assertEqual(characters.load(self.cid, self.ws)["data"]["name"], "S2")

    def test_an_expert_memory_is_listed_when_it_exists(self):
        key = "characters/%s/memory.md" % self.cid
        self.assertNotIn(key, self.items())
        (self.ws / "characters" / self.cid / "memory.md").write_text("# Memory\n- [2026-01-01] x\n", encoding="utf-8")
        item = self.items()[key]
        self.assertEqual((item["layer"], item["editable"]), ("on_demand", True))

    def test_memory_is_saved_under_its_lock_and_cap(self):
        self.assertEqual(self.put("MEMORY.md", "# Memory\n- edited\n")[0], 200)
        self.assertIn("- edited", (self.ws / "memory" / "MEMORY.md").read_text())
        self.assertEqual(self.put("MEMORY.md", "x" * (W.memory_store.MAX_BYTES + 1))[0], 400)

    def test_without_a_readable_registry_everything_is_read_only(self):
        (self.root / "protected_paths.json").unlink()
        self.assertFalse(any(x["editable"] for x in W.agent_instructions()))
        self.assertEqual(self.put("PROJECT.md", "x")[0], 403)


if __name__ == "__main__":
    unittest.main()
