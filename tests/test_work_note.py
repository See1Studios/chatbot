"""WORK_NOTE_v1 (delegation.work_note, server._turn_notices): a character the user talks to directly hears, in one
line before the user's message, the delegated work it is doing -- all of it on a session's first turn, then only when
a run's phase changes. The default character, which delegates, hears every run (it once guessed a timed-out run
was waiting for a merge); nothing in a private session.
Run: python3 -m unittest tests.test_work_note  (from services/chatbot)
"""
import shutil
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("CHATBOT_EVENTS_DIR", tempfile.mkdtemp())   # never the live event mailbox (evt/B)
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import delegation  # noqa: E402


class WorkNote(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        ws = self.data / "workspace"
        self.lead, self.kit, self.art = sorted(C.new_id() for _ in range(3))
        for cid, name in ((self.lead, "Boss"), (self.kit, "Kit"), (self.art, "Ari")):
            C.save(cid, C.new_card(name), ws)
        # the default also holds `dev`: the work of a role goes to another holder (by_role)
        C.save_team({"default": self.lead, "members": {self.lead: ["lead", "dev"], self.kit: ["dev"],
                                                       self.art: ["art"]}}, ws)
        self.runs = []
        self.saved = (delegation.DATA, delegation.runs)
        delegation.DATA = self.data
        delegation.runs = lambda limit=delegation.MAX_RUNS: [dict(r) for r in self.runs]

    def tearDown(self):
        delegation.DATA, delegation.runs = self.saved
        shutil.rmtree(self.data, ignore_errors=True)

    def run_(self, tid, phase, role="dev", task=1, total=1):
        self.runs = [r for r in self.runs if r["ticket"] != tid] + [
            {"ticket": tid, "title": "fix the widget", "phase": phase, "task": task, "tasks_total": total,
             "tasks": [{"role": role}] * total}]

    def test_the_worker_hears_its_work_once_then_only_changes(self):
        self.run_(7, "writing")
        note, told = delegation.work_note(self.kit, {})
        self.assertIn('#7 "fix the widget": you are working on it', note)
        self.assertEqual(delegation.work_note(self.kit, told)[0], "", "nothing changed: nothing said")
        self.run_(7, "review")
        note, told = delegation.work_note(self.kit, told)
        self.assertIn("Boss is checking the change", note)
        self.run_(7, "done")
        note, told = delegation.work_note(self.kit, told)
        self.assertIn("landed", note)
        self.assertEqual(told, {}, "an ended run is told once, then dropped")
        self.assertEqual(delegation.work_note(self.kit, told)[0], "")

    def test_a_new_session_does_not_hear_of_work_that_ended_before_it(self):
        self.run_(8, "done")
        self.assertEqual(delegation.work_note(self.kit, {})[0], "")

    def test_only_the_character_doing_the_current_task_hears_it(self):
        self.run_(9, "writing", role="art")
        self.assertEqual(delegation.work_note(self.kit, {})[0], "")
        self.assertIn("#9", delegation.work_note(self.art, {})[0])
        lead = delegation.work_note(self.lead, {})[0]
        self.assertIn('[Work you delegated] #9 "fix the widget": Ari is working on it', lead)
        self.assertIn("check `delegate` status", lead)

    def test_a_timed_out_run_is_told_as_stopped_and_kept(self):
        self.run_(12, "unavailable")
        note = delegation.work_note(self.lead, {})[0]
        self.assertIn("stopped: no brain answered in time; the work is kept", note)
        self.assertNotIn("waiting for the user's approval", note)

    def test_a_multi_task_plan_says_which_task(self):
        self.run_(10, "gates", task=2, total=3)
        self.assertIn("(task 2 of 3): the change is being tested", delegation.work_note(self.kit, {})[0])

    def test_the_server_hook_adds_it_in_work_sessions_only(self):
        import server
        self.run_(11, "writing")
        work = SimpleNamespace(character=self.kit, is_private=False)
        self.assertIn("#11", server._turn_notices(work))
        self.assertNotIn("#11", server._turn_notices(work), "told once")
        private = SimpleNamespace(character=self.kit, is_private=True)
        self.assertNotIn("#11", server._turn_notices(private))


if __name__ == "__main__":
    unittest.main()
