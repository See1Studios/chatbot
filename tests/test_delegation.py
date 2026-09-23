"""delegation.py: who may start, land or drop delegated work, and what the work cards read.
The runner itself is tested in tests/test_worktree_runner.py; here its launch is recorded, not run.
Run: python3 -m unittest tests.test_delegation  (from services/chatbot)
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import delegation  # noqa: E402
import tickets  # noqa: E402

CAND = "candidate:1789908287.39"
TIER0 = ["data/workspace/notes/x.md"]
TIER2 = ["session.py"]


class Base(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        obs = self.data / "workspace" / "skill-observations"
        obs.mkdir(parents=True)
        (obs / "candidates.jsonl").write_text(json.dumps({"epoch": 1789908287.39}) + "\n", encoding="utf-8")
        r = delegation.runner()
        self.saved = (delegation.DATA, delegation.SEEN_FILE, delegation._spawn, r.WORKTREE_BASE,
                      r.cleanup_worktree, r.commit_ticket_record)
        delegation.DATA = self.data
        delegation.SEEN_FILE = self.data / "delegation_seen.json"
        r.WORKTREE_BASE = self.data / "wt"
        self.spawned = []
        self.cleaned = []

        def fake_spawn(tid, args):
            self.spawned.append((tid, args))
            r.write_state(tid, pid=999999)
            return 4242
        delegation._spawn = fake_spawn
        r.cleanup_worktree = lambda repo, branch, wt: self.cleaned.append(branch)
        r.commit_ticket_record = lambda *a, **k: None

    def tearDown(self):
        r = delegation.runner()
        (delegation.DATA, delegation.SEEN_FILE, delegation._spawn, r.WORKTREE_BASE,
         r.cleanup_worktree, r.commit_ticket_record) = self.saved

    def request(self, paths, title="Fix it"):
        return delegation.request(title, paths, "do the thing", [CAND], actor="chat-agent:x")

    def state(self, tid):
        return delegation.runner().read_state(tid)


class RequestTest(Base):
    def test_tier_0_starts_at_once_on_the_operator_s_request(self):
        res = self.request(TIER0)
        self.assertEqual((res["tier"], res["started"]), (0, True))
        t = tickets.get(self.data, res["ticket"])
        self.assertEqual(t["status"], "in_progress")
        self.assertIn("via chat-agent:x delegate (Tier 0", t["approved_by"])
        self.assertEqual(t["worked_by"], delegation.worker_role())
        tid, args = self.spawned[-1]
        self.assertEqual(args[:2], ["run", "--ticket"])
        self.assertNotIn("--stop-before-merge", args)
        self.assertEqual(args[args.index("--prompt") + 1], "do the thing")
        self.assertEqual(self.state(tid)["instruction"], "do the thing")

    def test_tier_2_is_proposed_and_waits_for_the_operator(self):
        res = self.request(TIER2)
        self.assertEqual((res["tier"], res["started"]), (2, False))
        self.assertEqual(tickets.get(self.data, res["ticket"])["status"], "proposed")
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.state(res["ticket"])["phase"], "awaiting_go")

    def test_tier_3_and_bad_requests_are_refused(self):
        for paths in (["tickets.py"], ["tests/smoke.py"], [], ["/etc/passwd"], ["../x"]):
            with self.assertRaises(delegation.DelegationError, msg=paths):
                self.request(paths)
        with self.assertRaises(delegation.DelegationError):
            delegation.request("", TIER0, "x", [CAND], actor="chat-agent:x")
        self.assertEqual(tickets.list_tickets(self.data), [])

    def test_evidence_is_still_required(self):
        with self.assertRaises(tickets.TicketError):
            delegation.request("Fix it", TIER0, "x", [], actor="chat-agent:x")


class OperatorTest(Base):
    def test_go_approves_as_the_operator_and_launches_waiting_for_the_merge(self):
        tid = self.request(TIER2)["ticket"]
        delegation.go(tid)
        t = tickets.get(self.data, tid)
        self.assertEqual((t["status"], t["approved_by"]), ("in_progress", "operator (ui)"))
        self.assertIn("--stop-before-merge", self.spawned[-1][1])

    def test_go_on_a_ticket_without_files_is_refused(self):
        t, _ = tickets.propose(self.data, "vague", "make it better", [CAND])
        with self.assertRaises(delegation.DelegationError):
            delegation.go(t["id"])

    def awaiting(self):
        tid = self.request(TIER2)["ticket"]
        tickets.approve(self.data, tid, operator=tickets.OPERATOR_UI)
        c = tickets.claim(self.data, tid, paths=TIER2)
        tickets.await_merge(self.data, tid, c["token"])
        delegation.runner().write_state(tid, phase="awaiting_merge")
        return tid

    def test_merge_relays_the_operator_s_word_and_launches_the_landing(self):
        tid = self.awaiting()
        delegation.merge(tid)
        self.assertEqual(tickets.get(self.data, tid)["merge_approved_by"], "operator (ui)")
        args = self.spawned[-1][1]
        self.assertEqual(args[:3], ["merge", "--ticket", str(tid)])
        self.assertEqual(self.state(tid)["phase"], "merging")

    def test_merge_needs_a_waiting_change(self):
        tid = self.request(TIER2)["ticket"]
        with self.assertRaises(delegation.DelegationError):
            delegation.merge(tid)

    def test_a_merge_that_cannot_start_goes_back_to_waiting(self):
        tid = self.awaiting()

        def broken(tid, args):
            raise OSError("no python")
        delegation._spawn = broken
        with self.assertRaises(delegation.DelegationError):
            delegation.merge(tid)
        self.assertEqual(tickets.get(self.data, tid)["status"], "awaiting_merge")

    def test_discard_declines_and_drops_the_branch(self):
        tid = self.awaiting()
        delegation.discard(tid)
        self.assertEqual(tickets.get(self.data, tid)["status"], "declined")
        self.assertEqual(self.cleaned, ["worktree/ticket-%d" % tid])
        self.assertEqual(self.state(tid)["phase"], "declined")

    def test_a_stalled_run_can_be_discarded(self):
        tid = self.request(TIER0)["ticket"]          # claimed; its runner "died"
        delegation.runner().write_state(tid, phase="writing", pid=999999)
        delegation.discard(tid)
        self.assertEqual(tickets.get(self.data, tid)["status"], "declined")
        self.assertIsNone(tickets._read_lease(self.data))

    def test_a_running_change_cannot_be_discarded(self):
        tid = self.request(TIER0)["ticket"]
        import os
        delegation.runner().write_state(tid, phase="writing", pid=os.getpid())   # alive
        with self.assertRaises(delegation.DelegationError):
            delegation.discard(tid)


class CardsTest(Base):
    def test_cards_show_phase_seen_and_a_stalled_run(self):
        tid = self.request(TIER0)["ticket"]
        delegation.runner().write_state(tid, phase="writing", pid=999999)   # no such process
        card = delegation.runs()[0]
        self.assertEqual((card["ticket"], card["phase"], card["active"]), (tid, "stalled", False))
        delegation.runner().write_state(tid, phase="done")
        self.assertFalse(delegation.runs()[0]["seen"])
        delegation.mark_seen(tid)
        self.assertTrue(delegation.runs()[0]["seen"])
        delegation.runner().write_state(tid, phase="done", head="abc")   # a newer update is unseen again
        self.assertFalse(delegation.runs()[0]["seen"])

    def test_api_routes(self):
        tid = self.request(TIER2)["ticket"]
        self.assertIsNone(delegation.delegation_api("GET", "/api/tickets", None))
        code, body = delegation.delegation_api("GET", "/api/delegations", None)
        self.assertEqual((code, body["runs"][0]["ticket"]), (200, tid))
        self.assertEqual(delegation.delegation_api("POST", "/api/delegations/%d/seen" % tid, {})[0], 200)
        self.assertEqual(delegation.delegation_api("POST", "/api/delegations/%d/merge" % tid, {})[0], 400)
        self.assertEqual(delegation.delegation_api("POST", "/api/delegations/9999/go", {})[0], 404)
        self.assertEqual(delegation.delegation_api("POST", "/api/delegations/%d/approve" % tid, {})[0], 404)
        code, body = delegation.delegation_api("POST", "/api/delegations/%d/go" % tid, {})
        self.assertEqual((code, body["ticket"]), (200, tid))


class ToolTest(Base):
    def test_the_tool_server_offers_delegate_and_refuses_operator_actions(self):
        import mcp_server
        self.assertIn("delegate", [t["name"] for t in mcp_server.tool_defs()])
        res = mcp_server.call_tool("delegate", {"action": "status"})
        self.assertTrue(res.get("success"), res)
        res = mcp_server.call_tool("delegate", {"action": "merge"})
        self.assertFalse(res.get("success"))


class LiveRequestRefTest(unittest.TestCase):
    def test_the_operator_s_latest_message_is_the_default_evidence(self):
        import mcp_server
        from unittest import mock
        data = Path(tempfile.mkdtemp())
        sess = data / "sessions" / "s-1"
        sess.mkdir(parents=True)
        (sess / "events.jsonl").write_text('{"event":"system"}\n{"event":"user_ack","text":"a"}\n'
                                           '{"event":"result"}\n{"event":"user_ack","text":"b"}\n{"event":"tool"}\n')

        class Resp:
            def __init__(self, body): self.body = body
            def read(self): return self.body
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch.object(mcp_server, "DATA", data), \
                mock.patch("urllib.request.urlopen", return_value=Resp(b'{"id": "s-1"}')):
            self.assertEqual(mcp_server._live_request_ref(), "event:s-1#4")
        with mock.patch.object(mcp_server, "DATA", data), \
                mock.patch("urllib.request.urlopen", return_value=Resp(b'{"id": "../x"}')):
            self.assertIsNone(mcp_server._live_request_ref())


if __name__ == "__main__":
    unittest.main()
