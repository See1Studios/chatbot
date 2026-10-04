"""WORK_TALK_v1: a delegated run's talk -- the expert's line, the PD's answer -- goes into the two characters' dm,
never announced (no coworker reacts to each line), and the work card keeps only the verdict and a way into the talk.
Run: python3 -m unittest tests.test_work_talk  (from services/chatbot)
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests.test_delegation as td   # its Base: a temp data folder, two characters (staff S, default pd P)

delegation = td.delegation
setUpModule, tearDownModule = td.setUpModule, td.tearDownModule


class WorkTalk(td.Base):
    def setUp(self):
        super().setUp()
        box = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"CHATBOT_DIALOGS_DIR": str(box / "dialogs"),
                                           "CHATBOT_EVENTS_DIR": str(box / "events")})
        env.start()
        self.addCleanup(env.stop)
        import characters
        ws = self.data / "workspace"
        self.pd = characters.default_character(ws)
        self.staff = characters.by_role("staff", ws)

    def run_state(self, tid, phase, lines):
        delegation.runner().write_state(tid, phase=phase, pid=os.getpid(), transcript=lines, task=1,
                                        plan={"tasks": [{"role": "staff", "title": "t", "paths": ["a.py"]}]})

    def talk(self):
        import dialog_log
        return [(m["who"], m["text"]) for m in dialog_log.history(dialog_log.dm_id(self.staff, self.pd))]

    def test_the_lines_go_into_the_dm_once_and_unannounced(self):
        import events
        self.run_state(5, "review", [{"task": 1, "round": 1, "role": "writer", "name": "S", "text": "done!"}])
        self.assertEqual(delegation.mirror_work_talk(), 1)
        self.run_state(5, "review", [{"task": 1, "round": 1, "role": "writer", "name": "S", "text": "done!"},
                                     {"task": 1, "round": 1, "role": "reviewer", "name": "P", "text": "nice",
                                      "verdict": "PASS", "fix": ""}])
        self.assertEqual(delegation.mirror_work_talk(), 1)
        self.assertEqual(delegation.mirror_work_talk(), 0)                       # each line once
        self.assertEqual(self.talk(), [(self.staff, "done!"), (self.pd, "nice")])
        self.assertEqual(events.recent("msg.new"), [])                          # nobody is prompted to react

    def test_a_run_over_when_first_seen_is_not_replayed(self):
        old = [{"task": 1, "role": "writer", "text": "long ago"}, "an old plain line"]
        self.run_state(6, "gate_failed", old)
        self.assertEqual(delegation.mirror_work_talk(), 0)
        self.run_state(6, "review", old + [{"task": 1, "role": "writer", "text": "again"}])
        self.assertEqual(delegation.mirror_work_talk(), 1)
        self.assertEqual(self.talk(), [(self.staff, "again")])

    def test_the_card_has_the_verdict_and_whom_to_talk_to_not_the_talk(self):
        self.run_state(7, "review", [{"task": 1, "role": "writer", "text": "here"},
                                     {"task": 1, "role": "reviewer", "text": "no", "verdict": "FAIL", "fix": "tests"}])
        card = [r for r in delegation.runs() if r["ticket"] == 7][0]
        self.assertNotIn("transcript", card)
        self.assertEqual(card["review"], {"verdict": "FAIL", "fix": "tests", "advisory": None})
        self.assertEqual(card["talk_with"], self.staff)


if __name__ == "__main__":
    unittest.main()
