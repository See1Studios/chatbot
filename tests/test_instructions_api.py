"""workspace_status.instructions_api: the status tab shows every instruction the agent reads, and edits only
what the protected-path registry leaves unprotected (STATUS_INSTRUCTIONS_v1).
Run: engine/run-tests.sh test_instructions_api
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
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
        self.cid, self.default = characters.new_id(), characters.new_id()
        characters.save(self.cid, characters.new_card("S"), self.ws)          # an expert: its card is read on demand
        characters.save(self.default, characters.new_card("P"), self.ws)      # the chatbot itself: read every turn
        characters.save_team({"default": self.default, "members": {self.cid: ["staff"], self.default: []}}, self.ws)
        (self.ws / "memory" / "MEMORY.md").write_text("# Memory\n- a fact\n", encoding="utf-8")
        (self.root / "protected_paths.json").write_text(json.dumps(
            {"protect": ["data/workspace/AGENTS.md", "data/workspace/SELF-MODIFY.md"]}), encoding="utf-8")
        self.saved = (W.REPO, W.WORKSPACE)
        W.REPO, W.WORKSPACE = self.root, self.ws

    def tearDown(self):
        W.REPO, W.WORKSPACE = self.saved

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
            "characters/%s/card.json" % self.cid: ("on_demand", True),
            "characters/%s/card.json" % self.default: ("always", True)})
        self.assertIn("data/workspace/AGENTS.md", items["AGENTS.md"]["reason"])
        self.assertEqual(items["PROJECT.md"]["content"], "procedure")      # whole, not a preview
        self.assertEqual(items["AGENTS.md"]["scope"], "system")
        self.assertEqual(items["characters/%s/card.json" % self.cid]["scope"], "character")
        for gen in ("skills-index", "status-badge"):
            self.assertEqual((items[gen]["kind"], items[gen]["editable"], items[gen]["scope"]), ("generated", False, "system"))
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
        backups = self.root / "data" / "backups" / "instructions"
        self.assertEqual([p.read_text() for p in backups.glob("PROJECT.md.*")], ["procedure"])   # outside the workspace
        self.assertEqual([p.name for p in self.ws.iterdir() if ".bak" in p.name], [])

    def test_only_the_newest_backups_are_kept(self):
        import workspace_status as W2
        backups = self.root / "data" / "backups" / "instructions"
        backups.mkdir(parents=True)
        for n in range(W2.BACKUP_KEEP + 3):
            (backups / ("PROJECT.md.2026010100%04d" % n)).write_text("old")
        self.put("PROJECT.md", "again")
        self.assertEqual(len(list(backups.glob("PROJECT.md.*"))), W2.BACKUP_KEEP)

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

    def test_git_auto_commit_on_instruction_and_card_save(self):
        import subprocess
        subprocess.check_call(["git", "init", "-q"], cwd=str(self.root))
        subprocess.check_call(["git", "config", "user.name", "test-user"], cwd=str(self.root))
        subprocess.check_call(["git", "config", "user.email", "test@test.local"], cwd=str(self.root))
        subprocess.check_call(["git", "add", "."], cwd=str(self.root))
        subprocess.check_call(["git", "commit", "-qm", "initial"], cwd=str(self.root))

        code, body = self.put("PROJECT.md", "updated procedure for test")
        self.assertEqual((code, body["ok"]), (200, True))
        W.wait_commits()   # GIT_AUTOCOMMIT_v2: the commit runs on its own thread
        msg = subprocess.check_output(["git", "log", "-1", "--pretty=%B"], cwd=str(self.root), text=True).strip()
        self.assertEqual(msg, "chore(team): update PROJECT.md")

        import characters
        card = characters.new_card("S_Updated", "staff")
        card_path = "/api/instructions/characters%2F" + self.cid + "%2Fcard.json"
        code, body = W.instructions_api("PUT", card_path, {"content": json.dumps(card)})
        self.assertEqual((code, body["ok"]), (200, True))
        W.wait_commits()   # GIT_AUTOCOMMIT_v2: the commit runs on its own thread
        msg = subprocess.check_output(["git", "log", "-1", "--pretty=%B"], cwd=str(self.root), text=True).strip()
        self.assertEqual(msg, "chore(team): update card " + self.cid)

    def test_git_auto_commit_failure_is_safely_isolated(self):
        import subprocess
        subprocess.check_call(["git", "init", "-q"], cwd=str(self.root))
        subprocess.check_call(["git", "config", "user.name", "test-user"], cwd=str(self.root))
        subprocess.check_call(["git", "config", "user.email", "test@test.local"], cwd=str(self.root))

        lock_file = self.root / ".git" / "index.lock"
        lock_file.write_text("lock")
        try:
            code, body = self.put("PROJECT.md", "lock test procedure")
            self.assertEqual((code, body["ok"]), (200, True))
            self.assertEqual((self.ws / "PROJECT.md").read_text(encoding="utf-8"), "lock test procedure")
        finally:
            if lock_file.exists():
                lock_file.unlink()


if __name__ == "__main__":
    unittest.main()
