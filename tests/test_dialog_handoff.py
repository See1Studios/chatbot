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

    def stop(self, notify=True):
        self.stopped, self.busy = True, False

    def _send_direct(self, text, notice=False, event_type=""):
        self.sent.append((text, notice))
        self.event_type = event_type
        self.busy = True
        self.turn_started_at = float("inf")   # the fake turn starts at once, whatever clock the test runs on


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
                        mock.patch.object(H.threading, "Thread", Now),
                        mock.patch.object(H, "_BOOT", 0.0)]   # the fake clock's turns all began after this host started
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
        self.assertTrue(asked and asked[0].startswith("/api/office/notify?"))  # receiver draws it now
        self.assertIn("only=" + self.dev, asked[0])
        self.assertTrue(out["success"], out)
        self.assertEqual(out["data"], {"handoff": 1, "to_role": "dev"})
        h = H.all_handoffs()[1]
        self.assertEqual((h["from"], h["to"], h["state"], h["hops"]), (self.lead, self.dev, "sent", 1))
        msgs = D.history(D.dm_id(self.lead, self.dev))
        self.assertEqual(msgs[-1]["who"], self.lead)
        self.assertIn("no jump on reload", msgs[-1]["text"])

    def test_a_handoff_task_is_drawn_only_in_the_receiver_window(self):
        from urllib.parse import parse_qs, urlparse
        import route_sessions as RS
        asked = []
        out = T.call({"action": "handoff", "to": "dev", "text": "fix mobile jitter",
                      "done_when": "smooth"}, envelope,
                     {"id": "s-lead", "character": self.lead, "mode": "work", "private": False}, asked.append)
        self.assertTrue(out["success"])
        self.assertEqual(len(asked), 1)
        url = asked[0]
        self.assertIn("only=" + self.dev, url)
        qs = parse_qs(urlparse(url).query)
        req = type("Req", (), {"q": lambda self, k, d="": qs.get(k, [d])[0],
                               "send": lambda *a: None, "json": lambda *a: None})()
        lead_desk, dev_desk = self.office.desks[self.lead], self.office.desks[self.dev]
        with mock.patch.object(RS.REG, "_newest", side_effect=lambda mode, character: self.office.desks.get(character)), \
                mock.patch("event_react.react_once"):
            RS.office_notify(req)
        # Sender already shows the turn as its own assistant bubble; office event goes to receiver only
        lead_office = [e for e in lead_desk.drawn if e.get("event") == "office"]
        dev_office = [e for e in dev_desk.drawn if e.get("event") == "office"]
        self.assertEqual(lead_office, [], "sender window does not get duplicate office task line")
        self.assertEqual(len(dev_office), 1, "receiver window gets the office task line")
        self.assertIn("fix mobile jitter", dev_office[0]["msg"]["text"])

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
        self.assertIn("never the whole home folder", prompt)                    # live #31: a home-wide find
        self.assertIn("stop any subagent still running", prompt)
        self.assertEqual(H.run_once(self.office), [])                           # still working
        dev.busy, dev._loop_stopping = False, True                              # between a notice's stop and resume
        self.assertEqual(H.run_once(self.office), [])
        dev._loop_stopping = False
        dev.history.append({"role": "assistant", "text": "fixed; one test left for you", "ts": 1001.0})
        dev.busy = False
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "done"}])
        self.assertEqual(D.history(D.dm_id(self.dev, self.lead))[-1]["text"], "#1 fixed; one test left for you")
        office = [e for e in lead.drawn if e.get("event") == "office"]         # the sender's window draws it now
        self.assertIn("fixed; one test left", office[-1]["msg"]["text"])
        self.assertEqual([e for e in dev.drawn if e.get("event") == "office"], [])   # not again in the receiver's
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
        self.assertIn("went over its budget", H.ledger(self.lead)[0]["outcome"])   # the ledger keeps it too

    def test_a_turn_cut_by_a_restart_is_sent_again_once_then_fails_saying_so(self):
        # HANDOFF_RESTART_v1 (drill 2026-10-05): the restart stopped the agent; the handoff failed with no reason
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        dev = self.office.desks[self.dev]
        dev.busy = False
        with mock.patch.object(H, "_BOOT", 1500.0):                            # the host came back after it began
            self.assertEqual(H.run_once(self.office, now=1600.0), [{"id": 1, "state": "sent"}, {"id": 1, "state": "running"}])
            self.assertEqual(len(dev.sent), 2)                                 # the task again, not a resume
            self.assertIn("[Handoff #1 from Lead", dev.sent[1][0])
        dev.busy = False
        with mock.patch.object(H, "_BOOT", 1700.0):                            # and again
            self.assertEqual(H.run_once(self.office, now=1800.0), [{"id": 1, "state": "failed"}])
        self.assertIn("the host restarted", H.all_handoffs()[1]["reason"])

    def test_every_failure_says_why(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        self.office.desks[self.dev].busy = False
        H.run_once(self.office)
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "failed"}])
        self.assertEqual(H.all_handoffs()[1]["reason"], "the turn ended without an answer")

    def test_an_answer_after_the_budget_is_partial_and_the_lead_says_what_is_left(self):
        # HANDOFF_PARTIAL_v1 (drill 2026-10-06): one of ten files read, then "done"
        self.hand(self.lead, "s-lead", to="dev", text="read ten files")
        H.run_once(self.office, now=1000.0)
        dev, lead = self.office.desks[self.dev], self.office.desks[self.lead]
        dev._budget_hit_at = 1005.0                                             # the budget notice, in this turn
        dev.history.append({"role": "assistant", "text": "read one; nine left", "ts": 1010.0})
        dev.busy = False
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "partial"}])
        self.assertIn("tool-call budget", H.all_handoffs()[1]["reason"])
        self.assertIn("(partial)", lead.sent[0][0])
        self.assertIn("what is left", lead.sent[0][0])
        self.assertEqual(H.ledger(self.lead)[0]["state"], "partial")

    def test_a_budget_hit_in_an_earlier_turn_does_not_make_this_one_partial(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        dev = self.office.desks[self.dev]
        dev._budget_hit_at = 900.0
        H.run_once(self.office, now=1000.0)
        dev.history.append({"role": "assistant", "text": "all done", "ts": 1010.0})
        dev.busy = False
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "done"}])

    def scout(self):
        (self.ws / "roles" / "scout").mkdir(parents=True)
        (self.ws / "roles" / "scout" / "ROLE.md").write_text("---\ntitle: Scout\nowns: outside facts\n---\n\nScout.\n",
                                                             encoding="utf-8")

    def test_a_role_nobody_holds_goes_to_the_default_character(self):
        # DEFAULT_ROLE_v1: like an unclaimed skill, the work of a role nobody holds is the default's
        self.scout()
        out = self.hand(self.dev, "s-dev", to="scout", text="find the price")
        self.assertTrue(out["success"], out["message"])
        h = H.all_handoffs()[1]
        self.assertEqual((h["to"], h["role"]), (self.lead, "scout"))
        self.assertIn("Nobody holds the scout role", h["task"])
        self.assertIn("find the price", h["task"])

    def test_the_default_handing_off_a_role_nobody_holds_is_told_it_is_its_own(self):
        self.scout()
        out = self.hand(self.lead, "s-lead", to="scout", text="find the price")
        self.assertFalse(out["success"])
        self.assertIn("its work is yours", out["message"])
        self.assertEqual(H.all_handoffs(), {})

    def test_a_role_that_does_not_exist_is_still_refused(self):
        out = self.hand(self.dev, "s-dev", to="astronaut", text="x")
        self.assertFalse(out["success"])
        self.assertIn("the role or coworker who owns the work", out["message"])

    def test_a_waiting_handoff_cancelled_never_starts(self):
        # HANDOFF_CANCEL_v1
        self.hand(self.lead, "s-lead", to="dev", text="x")
        dev = self.office.desks[self.dev]
        dev.busy = True                                                         # talking with the operator
        H.cancel(1, self.lead, "the user called it off")
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "cancelled"}])
        self.assertFalse(getattr(dev, "stopped", False), "the operator's own turn is not stopped")
        dev.busy = False
        self.assertEqual(H.run_once(self.office, now=1000.0), [])
        self.assertEqual(dev.sent, [])
        self.assertEqual(H.all_handoffs()[1]["reason"], "the user called it off")
        self.assertIn("#1 (cancelled: the user called it off)", D.history(D.dm_id(self.dev, self.lead))[-1]["text"])

    def test_a_running_handoff_cancelled_stops_its_turn_and_its_end_is_not_a_result(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        dev, lead = self.office.desks[self.dev], self.office.desks[self.lead]
        H.cancel(1, "operator")
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "cancelled"}])
        self.assertTrue(dev.stopped)
        self.assertEqual(H.all_handoffs()[1]["reason"], "the operator cancelled it")
        dev.history.append({"role": "assistant", "text": "half of it", "ts": 1001.0})
        self.assertEqual(H.run_once(self.office), [])
        self.assertEqual(H.all_handoffs()[1]["state"], "cancelled")
        self.assertEqual(lead.sent, [], "no tell-the-user turn: whoever cancelled it knows")

    def test_cancelling_a_handoff_cancels_the_work_it_handed_on(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        self.hand(self.dev, "s-dev", to=self.art, text="draw")                  # dev hands part on while running #1
        art = self.office.desks[self.art]
        H.run_once(self.office, now=2000.0)
        self.assertEqual(H.all_handoffs()[2]["state"], "running")
        H.cancel(1, self.lead)
        self.assertEqual(H.run_once(self.office), [{"id": 1, "state": "cancelled"}, {"id": 2, "state": "cancelled"}])
        self.assertTrue(art.stopped)
        self.assertEqual(H.all_handoffs()[2]["reason"], "its parent #1 was cancelled")

    def test_a_cancelled_child_lets_its_waiting_parent_go_on(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        self.hand(self.dev, "s-dev", to=self.art, text="draw")
        dev = self.office.desks[self.dev]
        dev.history.append({"role": "assistant", "text": "handed the drawing on", "ts": 1001.0})
        dev.busy = False
        H.run_once(self.office, now=2000.0)
        self.assertEqual(H.all_handoffs()[1]["state"], "waiting")
        H.cancel(2, self.dev, "not needed after all")
        H.run_once(self.office, now=3000.0)
        self.assertEqual(H.all_handoffs()[2]["state"], "cancelled")
        self.assertIn(H.all_handoffs()[1]["state"], ("resume", "running"))

    def test_only_its_two_directors_or_the_operator_cancel_an_open_handoff(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        with self.assertRaises(H.HandoffError):
            H.cancel(1, self.art)
        with self.assertRaises(H.HandoffError):
            H.cancel(9, self.lead)
        H.cancel(1, self.dev)
        H.run_once(self.office)
        with self.assertRaises(H.HandoffError):
            H.cancel(1, "operator")                                             # already closed

    def test_the_tool_cancels_by_number_whatever_the_model_calls_it(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        out = T.call({"action": "cancel", "id": "#1", "reason": "user said stop"}, envelope,
                     {"id": "s-lead", "character": self.lead, "mode": "work", "private": False})
        self.assertTrue(out["success"], out["message"])
        self.assertEqual(H.all_handoffs()[1]["cancel_reason"], "user said stop")
        out = T.call({"action": "cancel", "handoff": 1}, envelope,
                     {"id": "s-art", "character": self.art, "mode": "work", "private": False})
        self.assertFalse(out["success"])

    def test_a_handoff_named_with_the_words_models_use_still_goes(self):
        # drill 2026-10-05: {"action": "handoff", "role": "art", "brief": "..."} -- no `to`, no `text`
        out = T.call({"action": "handoff", "role": "dev", "brief": "fix it"}, envelope,
                     {"id": "s-lead", "character": self.lead, "mode": "work", "private": False})
        self.assertTrue(out["success"], out["message"])
        self.assertEqual(H.all_handoffs()[1]["task"], "fix it")

    def test_a_turn_that_never_starts_is_sent_again_once_then_fails_saying_so(self):
        # HANDOFF_UNSTARTED_v1 (drill 2026-10-06): a resent turn stuck before its agent ran stayed running 10 minutes
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        dev = self.office.desks[self.dev]
        dev.turn_started_at = 0.0                                               # it never began
        self.assertEqual(H.run_once(self.office, now=1000.0 + H.START_GRACE_SEC - 1), [], "still in its grace")
        got = H.run_once(self.office, now=1000.0 + H.START_GRACE_SEC + 1)
        self.assertEqual(got, [{"id": 1, "state": "sent"}, {"id": 1, "state": "running"}])
        self.assertTrue(dev.stopped, "what held the session is stopped first")
        self.assertEqual(len(dev.sent), 2)
        dev.turn_started_at = 0.0
        later = 1000.0 + 3 * H.START_GRACE_SEC
        self.assertEqual(H.run_once(self.office, now=later), [{"id": 1, "state": "failed"}])
        self.assertIn("never started", H.all_handoffs()[1]["reason"])
        self.assertIn("never started", D.history(D.dm_id(self.dev, self.lead))[-1]["text"])

    def test_a_long_turn_that_did_start_is_left_alone(self):
        self.hand(self.lead, "s-lead", to="dev", text="x")
        H.run_once(self.office, now=1000.0)
        dev = self.office.desks[self.dev]
        dev.turn_started_at = 1001.0                                            # began, still working
        self.assertEqual(H.run_once(self.office, now=1000.0 + 10 * H.START_GRACE_SEC), [])
        self.assertFalse(getattr(dev, "stopped", False))

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

    def test_a_handoff_turn_gets_the_unread_dm_lines_after_the_task_not_the_restart_line(self):
        # live #20 (2026-10-05): the whole before-turn note put the restart line first and the turn answered that
        D.append(D.dm_id(self.lead, self.dev), self.lead, "the build broke again", announce=False)
        self.hand(self.lead, "s-lead", to="dev", text="look at the build")
        H.run_once(self.office, now=1000.0)
        prompt = self.office.desks[self.dev].sent[0][0]
        self.assertLess(prompt.index("look at the build"), prompt.index("Also new in your dialogs"))
        self.assertIn("the build broke again", prompt)
        src = (ROOT / "session_turn.py").read_text(encoding="utf-8")
        self.assertIn('"" if notice else _s().boot_notice(self)', src)          # host turns skip the restart line

    def test_one_host_turn_at_a_time_per_session(self):
        # HOST_TURN_ONE_v1, live #24: a restart reaction and a handoff reached the same new session in one pass
        desk = self.office.desks[self.lead]
        self.assertTrue(H.claim(desk))
        self.assertFalse(H.claim(desk))                                          # the second waits
        desk._host_turn_at -= H.HOST_TURN_GAP + 1
        self.assertTrue(H.claim(desk))
        self.hand(self.dev, "s-dev", to="lead", text="report")
        self.office.desks[self.lead]._host_turn_at = __import__("time").time()   # a reaction just started there
        self.assertEqual(H.run_once(self.office), [])                            # the handoff waits its turn
        src = Path(event_react.__file__).read_text(encoding="utf-8")
        self.assertIn("dialog_handoff.claim(sess, now)", src)

    def test_a_handoff_handed_on_waits_then_its_director_finishes_it(self):
        # HANDOFF_CHAIN_v1, live #27/#28: #27 closed on "I handed it to art"; art's result reached only a tell-the-user
        dev, lead, art = self.office.desks[self.dev], self.office.desks[self.lead], self.office.desks[self.art]
        self.hand(self.lead, "s-lead", to="dev", text="plan the style guide")
        H.run_once(self.office, now=1000.0)                                      # dev works #1
        self.hand(self.dev, "s-dev", to=self.art, text="list the styles")       # ... and hands part of it on (#2)
        dev.history.append({"role": "assistant", "text": "handed to art as #2", "ts": 1001.0})
        dev.busy = False
        H.run_once(self.office, now=1002.0)
        self.assertEqual(H.all_handoffs()[1]["state"], "waiting")               # not done on "I handed it on"
        self.assertEqual(lead.sent, [])                                          # and nothing told upward yet
        self.assertEqual(H.all_handoffs()[2]["state"], "running")               # art got #2 in the same pass
        art.history.append({"role": "assistant", "text": "studio_anime, subculture_punk", "ts": 1003.0})
        art.busy = False
        H.run_once(self.office, now=1004.0)
        self.assertEqual(H.all_handoffs()[2]["state"], "done")
        self.assertEqual(len(dev.sent), 2)                                       # one more turn for dev, and it is ...
        self.assertEqual(H.all_handoffs()[1]["state"], "running")               # ... #1 resumed at dev's desk
        resume = dev.sent[-1][0]
        self.assertNotIn("Do not use tools", resume)                             # a work turn, not a tell-the-user
        self.assertIn("#1 from Lead, continued", resume)
        self.assertIn("#2 (done): studio_anime, subculture_punk", resume)
        dev.history.append({"role": "assistant", "text": "decide: default style, chibi or not", "ts": 1006.0})
        dev.busy = False
        H.run_once(self.office, now=1007.0)
        self.assertEqual(H.all_handoffs()[1]["state"], "done")
        self.assertIn("decide: default style", H.all_handoffs()[1]["result"])
        self.assertIn("Dev finished handoff #1", lead.sent[-1][0])               # now the lead hears it

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
