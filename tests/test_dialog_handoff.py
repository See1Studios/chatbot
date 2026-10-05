"""HANDOFF_v1 (docs/plans/director-handoff.md dir/D-G): a director hands work that is not its role's to the director
that owns it; the receiver works it in its own work session, and the result comes back to the sender.
Run: python3 -m unittest tests.test_dialog_handoff  (from services/chatbot)
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CHATBOT_EVENTS_DIR", tempfile.mkdtemp())   # never the live mailbox
os.environ.setdefault("CHATBOT_DIALOGS_DIR", tempfile.mkdtemp())  # nor the live dialogs
os.environ.setdefault("CHATBOT_EDITION", "dev")
import characters as C  # noqa: E402
import dialog_handoff as H  # noqa: E402
import dialog_log as D  # noqa: E402
import dialog_tool as T  # noqa: E402
import event_react  # noqa: E402
import room_chat as RC  # noqa: E402

LEAD = "---\ntitle: Lead\nowns: priorities\nrepo: none\n---\n\nLead.\n"
DEV = "---\ntitle: Dev\nowns: engine code, tests\n---\n\nDev.\n"


def envelope(ok, message, data):
    return {"success": ok, "message": message, "data": data}


class Now:
    """threading.Thread that runs its target at start(): the pass's turns start before the test looks."""
    def __init__(self, target, args=(), **kw):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class Desk:
    def __init__(self, sid, subagents=True):
        self.sid, self.busy, self.history, self.sent, self.drawn = sid, False, [], [], []
        self.adapter = type("A", (), {"subagents": subagents, "subagent_hint": " (spawn one)"})()

    def _emit(self, ev):
        self.drawn.append(ev)

    def _send_direct(self, text, notice=False, event_type=""):
        self.sent.append((text, notice))
        self.event_type = event_type
        self.busy = True


class Office:
    def __init__(self, desks):
        self.desks = desks

    def get_active(self, cid):
        return self.desks.get(cid)

    def _newest(self, mode, character):
        return self.desks.get(character)

    def peek(self, sid):
        return next((d for d in self.desks.values() if d.sid == sid), None)


class Handoff(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.lead, self.dev, self.art = sorted(C.new_id() for _ in range(3))
        for cid, name in ((self.lead, "Boss"), (self.dev, "Kit"), (self.art, "Ari")):
            C.save(cid, C.new_card(name), self.ws)
        for role, text in (("lead", LEAD), ("dev", DEV)):
            (self.ws / "roles" / role).mkdir(parents=True)
            (self.ws / "roles" / role / "ROLE.md").write_text(text, encoding="utf-8")
        C.save_team({"default": self.lead, "members": {self.lead: ["lead"], self.dev: ["dev"]}}, self.ws)
        self.patches = [mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.tmp / "events"),
                                                     "CHATBOT_HANDOFFS_FILE": str(self.tmp / "handoffs.jsonl")}),
                        mock.patch.object(RC, "_dir", lambda: self.tmp / "rooms"),
                        mock.patch.object(D, "_dir", lambda: self.tmp / "dialogs"),
                        mock.patch.object(C, "_default_ws", return_value=self.ws),
                        mock.patch.object(H.threading, "Thread", Now)]
        for p in self.patches:
            p.start()
        self.office = Office({self.lead: Desk("s-lead"), self.dev: Desk("s-dev"), self.art: Desk("s-art")})
        H._UNANSWERED.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hand(self, cid, sid, **args):
        return T.call({"action": "handoff", **args}, envelope, {"id": sid, "character": cid, "mode": "work",
                                                               "private": False})

    def test_a_handoff_by_role_is_recorded_and_left_in_the_two_directors_dm(self):
        asked = []
        out = T.call({"action": "handoff", "to": "dev", "text": "the stream jitters on mobile",
                      "done_when": "no jump on reload"}, envelope,
                     {"id": "s-lead", "character": self.lead, "mode": "work", "private": False}, asked.append)
        self.assertTrue(asked and asked[0].startswith("/api/office/notify?"))  # both windows draw the task now
        self.assertTrue(out["success"], out)
        self.assertEqual(out["data"], {"handoff": 1, "to_role": "dev"})
        h = H.all_handoffs()[1]
        self.assertEqual((h["from"], h["to"], h["state"], h["hops"]), (self.lead, self.dev, "sent", 1))
        msgs = D.history(D.dm_id(self.lead, self.dev))
        self.assertEqual(msgs[-1]["who"], self.lead)
        self.assertIn("no jump on reload", msgs[-1]["text"])

    def test_no_one_named_lists_who_owns_what(self):
        out = self.hand(self.lead, "s-lead", to="", text="x")
        self.assertFalse(out["success"])
        self.assertIn("dev (engine code, tests)", out["message"])
        self.assertFalse(self.hand(self.lead, "s-lead", to="lead", text="x")["success"])      # not to yourself

    def test_the_receiver_starts_when_free_and_the_result_comes_back(self):
        self.hand(self.lead, "s-lead", to="dev", text="fix the jitter", done_when="tests pass")
        dev, lead = self.office.desks[self.dev], self.office.desks[self.lead]
        dev.busy = True                                                         # talking with the operator
        self.assertEqual(H.run_once(self.office), [])
        dev.busy = False
        self.assertEqual(H.run_once(self.office, now=1000.0), [{"id": 1, "state": "running"}])
        prompt, notice = dev.sent[0]
        self.assertTrue(notice)                                                # a host turn, not the user's words
        self.assertEqual(dev.event_type, "handoff")                            # with a whole turn's budget
        self.assertIn("Read narrowly", prompt)
        self.assertIn("[Handoff #1 from Lead", prompt)
        self.assertIn("fix the jitter", prompt)
        self.assertIn("subagents (spawn one)", prompt)
        self.assertIn("`delegate` plan", prompt)
        self.assertEqual(H.run_once(self.office), [])                           # still working
        dev.busy, dev._loop_stopping = False, True                              # between a notice's stop and resume
        self.assertEqual(H.run_once(self.office), [])
        dev._loop_stopping = False
        dev.history.append({"role": "assistant", "text": "fixed; one test left for you", "ts": 1001.0})
        dev.busy = False
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "done"}])
        self.assertEqual(D.history(D.dm_id(self.dev, self.lead))[-1]["text"], "#1 fixed; one test left for you")
        for desk in (dev, lead):                                                # both windows draw the answer now
            office = [e for e in desk.drawn if e.get("event") == "office"]
            self.assertIn("fixed; one test left", office[-1]["msg"]["text"])
        report, _ = lead.sent[0]
        self.assertIn("Dev finished handoff #1 (done)", report)
        self.assertIn("Do not use tools", report)
        self.assertEqual(H.all_handoffs()[1]["state"], "done")

    def test_a_turn_that_ends_without_an_answer_fails_back_with_its_reason(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        dev = self.office.desks[self.dev]
        dev.busy, dev._loop_hint = False, "The last turn went over its budget (20 tool calls)"   # live 2026-10-05
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "failed"}])
        self.assertIn("went over its budget", D.history(D.dm_id(self.dev, self.lead))[-1]["text"])

    def test_an_answer_still_on_its_way_gets_a_second_look(self):
        # live #6 (2026-10-05): the turn had ended, its answer was not in the record yet, and it was failed
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        dev = self.office.desks[self.dev]
        dev.busy = False
        self.assertEqual(H.run_once(self.office), [])                           # no answer yet: look again
        dev.history.append({"role": "assistant", "text": "done it", "ts": 1001.0})
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "done"}])

    def test_a_turn_that_ran_out_of_time_is_not_done(self):
        # handoff #5 (2026-10-05): "I gave it to a subagent, I will report" and then the 8-minute timeout
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        dev = self.office.desks[self.dev]
        dev.history.append({"role": "assistant", "text": "handed to a subagent, will report", "ts": 1489.0})
        dev.busy, dev._turn_timed_out = False, True
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "failed"}])
        self.assertIn("ran out of time", D.history(D.dm_id(self.dev, self.lead))[-1]["text"])

    def test_a_handoff_turn_is_not_cut_to_the_notice_budget(self):
        src = (ROOT / "session_turn.py").read_text(encoding="utf-8")
        self.assertIn('if notice and event_type != "handoff":', src)

    def test_one_open_handoff_per_director_and_at_most_two_hops(self):
        self.assertTrue(self.hand(self.lead, "s-lead", to="dev", text="a")["success"])
        busy = self.hand(self.lead, "s-lead", to="dev", text="b")
        self.assertIn("still on handoff #1", busy["message"])
        H.run_once(self.office, now=1000.0)                                     # dev works #1 in s-dev
        second = self.hand(self.dev, "s-dev", to=self.art, text="draw it")      # hop 2, from inside #1
        self.assertTrue(second["success"], second)
        self.assertEqual(H.all_handoffs()[2]["hops"], 2)
        H.run_once(self.office, now=1001.0)                                     # art works #2 in s-art
        third = self.hand(self.art, "s-art", to=self.lead, text="decide")
        self.assertIn("already handed on 2 times", third["message"])

    def test_a_director_reads_the_ledger_with_the_state_now(self):
        # live 2026-10-05: the lead kept reporting a cancelled handoff (#3) as waiting, from memory
        self.hand(self.lead, "s-lead", to="dev", text="build the tool")
        H.run_once(self.office, now=1000.0)
        self.office.desks[self.dev].busy, self.office.desks[self.dev]._loop_hint = False, "over budget"
        H.run_once(self.office)                                                 # failed
        H.mark(1, "cancelled", reason="operator: not needed")
        self.hand(self.lead, "s-lead", to="dev", text="count the plans")
        out = T.call({"action": "handoffs"}, envelope, {"id": "s-lead", "character": self.lead, "mode": "work",
                                                        "private": False})
        rows = out["data"]["handoffs"]
        self.assertEqual([(r["id"], r["state"], r["direction"]) for r in rows], [(2, "sent", "sent"), (1, "cancelled", "sent")])
        self.assertIn("not needed", rows[1]["outcome"])
        dev_rows = H.ledger(self.dev)
        self.assertEqual([r["direction"] for r in dev_rows], ["received", "received"])

    def test_a_handoff_turn_gets_the_unread_dm_lines(self):
        src = (ROOT / "session_turn.py").read_text(encoding="utf-8")
        self.assertIn('told = not notice or event_type == "handoff"', src)

    def test_the_reactor_runs_handoffs_whatever_auto_says(self):
        src = Path(event_react.__file__).read_text(encoding="utf-8")
        self.assertIn("dialog_handoff.run_once(reg)", src)

    def test_adapters_say_how_their_subagents_start(self):
        from providers.adapter_base import AgentAdapter
        from providers.adapter_agy import AgyAdapter
        from providers.adapter_claude import ClaudeAdapter
        from providers.adapter_codex import CodexAdapter
        from providers.adapter_grok import GrokAdapter
        self.assertFalse(AgentAdapter.subagents)
        for a in (AgyAdapter, ClaudeAdapter, CodexAdapter, GrokAdapter):
            self.assertTrue(a.subagents and a.subagent_hint.startswith(" ("), a)

    def test_the_role_templates_say_what_each_director_owns(self):
        tpl = ROOT / "templates" / "dev-workspace"
        for role in ("lead", "dev", "plan", "scout"):
            self.assertTrue(C.role_pack(role, tpl)["owns"], role)


if __name__ == "__main__":
    unittest.main()
