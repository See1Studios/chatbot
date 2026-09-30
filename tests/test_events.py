"""The event mailbox (events.py, plan evt/B): events addressed to characters, read per session from a cursor that
survives restarts; work phase changes published once each; the turn hook delivers them as the old notes did;
private visits and account switches published with no text (evt/C).
Run: python3 -m unittest tests.test_events  (from services/chatbot)
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import delegation  # noqa: E402
import events as E  # noqa: E402


class Mailbox(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.dir / "ev")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_each_session_reads_what_was_addressed_to_its_character_on_its_channel(self):
        a = E.publish("x", ["kit"], subject="1")
        E.publish("x", ["ari"], subject="2")
        E.publish("y", E.ALL, subject="3")
        E.publish("p", ["kit"], channel="private", subject="4")
        self.assertEqual([e["subject"] for e in E.pending("s1", "kit")], ["1", "3"])
        self.assertEqual([e["subject"] for e in E.pending("s2", "kit", "private")], ["4"])
        self.assertIsNone(E.cursor("s1"))
        E.mark("s1", a["id"])
        self.assertEqual([e["subject"] for e in E.pending("s1", "kit")], ["3"])
        self.assertEqual(E.cursor("s1"), a["id"], "kept on disk: a restarted server reads on from here")
        with self.assertRaises(ValueError):
            E.publish("x", ["kit"], channel="elsewhere")

    def test_ids_rise_and_no_text_field_is_invented(self):
        ids = [E.publish("x", ["kit"])["id"] for _ in range(5)]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(set(E.latest("x")), {"id", "ts", "type", "channel", "subject", "to", "payload"})

    def test_old_events_go_private_ones_sooner(self):
        E.publish("w", ["kit"])
        E.publish("p", ["kit"], channel="private")
        lines = [json.loads(l) for l in (self.dir / "ev" / "events.jsonl").read_text().splitlines()]
        for e in lines:
            e["ts"] -= 8 * 86400                    # 8 days old: past the private limit, inside the work one
        (self.dir / "ev" / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines))
        E.publish("w2", ["kit"])
        self.assertEqual([e["type"] for e in E._read_all()], ["w", "w2"])
        with mock.patch.object(E, "MAX_BYTES", 600):
            for _ in range(10):
                E.publish("big", ["kit"], note="x" * 50)
        self.assertLessEqual((self.dir / "ev" / "events.jsonl").stat().st_size, 600)


class PublishPoints(unittest.TestCase):
    """evt/C: a private visit starting and ending, and an account switch, each published once, with no text."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.dir / "ev")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_private_visit_reaches_only_that_character_s_private_channel(self):
        import threshold
        priv, work = SimpleNamespace(sid="p1", character="kit"), SimpleNamespace(sid="w1", character="kit")
        threshold._publish("session.private.start", priv, work)
        e = E.latest("session.private.start")
        self.assertEqual((e["to"], e["channel"], e["subject"], e["payload"]), (["kit"], "private", "p1", {}))
        self.assertEqual(E.pending("w-ari", "ari", "private"), [])
        self.assertEqual(E.pending("w-kit", "kit", "work"), [], "never on the work side (private-security T3)")
        src = (ROOT / "threshold.py").read_text(encoding="utf-8")
        self.assertIn('_publish("session.private.start", priv, work)', src)
        self.assertIn('_publish("session.private.end", priv, work)', src)

    def test_an_account_switch_names_the_provider_never_the_account(self):
        from providers import accounts
        with mock.patch.object(accounts, "STATE_FILE", self.dir / "state.json"):
            accounts.observe("agy", {"ok": True, "email": "old@x"})
            accounts.observe("agy", {"ok": True, "email": "old@x"})
            self.assertIsNone(E.latest("account.switch"), "the same account is no switch")
            accounts.observe("agy", {"ok": True, "email": "new@x"})
        e = E.latest("account.switch")
        self.assertEqual((e["subject"], e["to"]), ("agy", [E.ALL]))
        self.assertNotIn("@", json.dumps(e))


class Logged(unittest.TestCase):
    """The mailbox and the engine log are one record seen twice: every publish, delivery and prune is in the log,
    as metadata -- never a payload's words, and a private event not even its subject."""

    def setUp(self):
        import obslog
        self.dir = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.dir / "ev")})
        self.env.start()
        self.saved = dict(obslog._state)
        obslog.configure("test", self.dir / "log.jsonl")

    def tearDown(self):
        import obslog
        obslog._state.clear()
        obslog._state.update(self.saved)
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def lines(self):
        return [json.loads(l) for l in (self.dir / "log.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_publish_and_delivery_are_logged_without_words(self):
        E.publish("work.phase", ["kit"], subject="7", title="secret plan words", phase="done")
        E.publish("session.private.start", ["kit"], channel="private", subject="p-sid-1")
        E.pending("s1", "kit")
        log = self.lines()
        pub = [l for l in log if l["evt"] == "events.publish"]
        self.assertEqual([(l["type"], l["to"]) for l in pub], [("work.phase", 1), ("session.private.start", 1)])
        self.assertEqual(pub[0]["subject"], "7")
        self.assertNotIn("subject", pub[1], "a private event keeps its subject out of the log")
        deliver = [l for l in log if l["evt"] == "events.deliver"]
        self.assertEqual((deliver[0]["sid"], deliver[0]["n"], deliver[0]["types"]), ("s1", 1, ["work.phase"]))
        text = (self.dir / "log.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("secret plan words", text)
        self.assertNotIn("p-sid-1", text)

    def test_the_boot_restart_event_is_published_after_the_log_is_configured(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertLess(src.index('obslog.start_process("chat"'), src.index("    _record_boot()"),
                        "else the host.restart event misses its log line")


class WorkEvents(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.dir / "ev")})
        self.env.start()
        ws = self.dir / "workspace"
        self.lead, self.kit, self.ari = sorted(C.new_id() for _ in range(3))
        for cid, name in ((self.lead, "Boss"), (self.kit, "Kit"), (self.ari, "Ari")):
            C.save(cid, C.new_card(name), ws)
        C.save_team({"default": self.lead, "members": {self.lead: ["lead"], self.kit: ["dev"], self.ari: ["art"]}}, ws)
        self.runs = []
        self.saved = (delegation.DATA, delegation.runs)
        delegation.DATA = self.dir
        delegation.runs = lambda limit=delegation.MAX_RUNS: [dict(r) for r in self.runs]

    def tearDown(self):
        delegation.DATA, delegation.runs = self.saved
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_(self, tid, phase, role="dev"):
        self.runs = [r for r in self.runs if r["ticket"] != tid] + [
            {"ticket": tid, "title": "fix it", "phase": phase, "task": 1, "tasks_total": 1, "tasks": [{"role": role}]}]

    def test_phase_changes_are_published_once_to_the_worker_and_the_default(self):
        self.run_(1, "done")                        # ended before the mailbox saw it: not announced
        self.run_(2, "writing")
        self.assertEqual(delegation.publish_work_changes(), 1)
        e = E.latest("work.phase")
        self.assertEqual((e["subject"], e["to"], e["payload"]["phase"]), ("2", sorted([self.kit, self.lead]), "writing"))
        self.assertEqual(delegation.publish_work_changes(), 0, "no change, no event")
        self.run_(2, "review")
        self.assertEqual(delegation.publish_work_changes(), 1)

    def test_the_turn_hook_delivers_summary_first_then_changes_for_that_character_only(self):
        import server
        self.run_(3, "writing")
        delegation.publish_work_changes()
        kit, ari = SimpleNamespace(sid="s-kit", character=self.kit), SimpleNamespace(sid="s-ari", character=self.ari)
        lead = SimpleNamespace(sid="s-lead", character=self.lead)
        self.assertIn('#3 "fix it": you are working on it', server._turn_notices(kit), "a first read: the summary")
        self.assertEqual(server._turn_notices(kit), "", "nothing new")
        self.assertIn("Kit is working on it", server._turn_notices(lead))
        server._turn_notices(ari)
        self.run_(3, "awaiting_merge")
        delegation.publish_work_changes()
        kit_again = SimpleNamespace(sid="s-kit", character=self.kit)      # the same session after a restart
        self.assertIn("waiting for the user's approval", server._turn_notices(kit_again))
        self.assertEqual(server._turn_notices(ari), "", "not Ari's work")
        self.assertIn("[Work you delegated]", server._turn_notices(lead))

    def test_a_private_session_gets_no_work_note_and_private_events_reach_only_who_was_there(self):
        import server
        self.run_(4, "writing")
        delegation.publish_work_changes()
        private = SimpleNamespace(sid="p-kit", character=self.kit, is_private=True)
        self.assertNotIn("#4", server._turn_notices(private))
        E.publish("session.private.start", [self.kit], channel="private", subject=self.kit)
        self.assertEqual(len(E.pending("p-ari", self.ari, "private")), 0)
        self.assertEqual(len(E.pending("p-kit2", self.kit, "private")), 1)


if __name__ == "__main__":
    unittest.main()
