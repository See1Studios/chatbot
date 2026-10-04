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
        self.sid, self.busy, self.history, self.sent = sid, False, [], []
        self.adapter = type("A", (), {"subagents": subagents, "subagent_hint": " (spawn one)"})()

    def _send_direct(self, text, notice=False):
        self.sent.append((text, notice))
        self.busy = True


class Office:
    def __init__(self, desks):
        self.desks = desks

    def get_active(self, cid):
        return self.desks.get(cid)

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

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hand(self, cid, sid, **args):
        return T.call({"action": "handoff", **args}, envelope, {"id": sid, "character": cid, "mode": "work",
                                                               "private": False})

    def test_a_handoff_by_role_is_recorded_and_left_in_the_two_directors_dm(self):
        out = self.hand(self.lead, "s-lead", to="dev", text="the stream jitters on mobile", done_when="no jump on reload")
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
        self.assertIn("[Handoff #1 from Lead", prompt)
        self.assertIn("fix the jitter", prompt)
        self.assertIn("subagents (spawn one)", prompt)
        self.assertIn("`delegate` plan", prompt)
        self.assertEqual(H.run_once(self.office), [])                           # still working
        dev.history.append({"role": "assistant", "text": "fixed; one test left for you", "ts": 1001.0})
        dev.busy = False
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "done"}])
        self.assertEqual(D.history(D.dm_id(self.dev, self.lead))[-1]["text"], "fixed; one test left for you")
        report, _ = lead.sent[0]
        self.assertIn("Dev finished handoff #1 (done)", report)
        self.assertIn("Do not use tools", report)
        self.assertEqual(H.all_handoffs()[1]["state"], "done")

    def test_a_turn_that_ends_without_an_answer_fails_back(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        self.office.desks[self.dev].busy = False
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "failed"}])

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
