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
        import characters
        characters.save(characters.new_id(), characters.new_card("S", "staff"), self.data / "workspace")
        characters.save(characters.new_id(), characters.new_card("P", "pd"), self.data / "workspace")   # the PD is not an expert
        r = delegation.runner()
        self.saved = (delegation.DATA, delegation.SEEN_FILE, delegation._spawn, r.WORKTREE_BASE,
                      r.cleanup_worktree, r.commit_ticket_record, delegation.PLAN_ROOT)
        delegation.DATA = self.data
        delegation.PLAN_ROOT = self.data / "repo"             # the files a plan may name exist here
        for rel in TIER0 + TIER2 + ["static/chat.css", "static/app.js"]:
            (delegation.PLAN_ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
            (delegation.PLAN_ROOT / rel).write_text("x", encoding="utf-8")
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
         r.cleanup_worktree, r.commit_ticket_record, delegation.PLAN_ROOT) = self.saved

    def request(self, paths, title="Fix it"):
        return delegation.request(title, paths, "do the thing", [CAND], actor="chat-agent:x")

    def plan(self, tasks, title="Plan it", ticket_id=None):
        return delegation.plan(title, tasks, [CAND], actor="chat-agent:x", ticket_id=ticket_id)

    def task(self, paths, title="do it"):
        return {"role": "staff", "title": title, "instruction": "do the thing", "paths": paths}

    def state(self, tid):
        return delegation.runner().read_state(tid)


class PlanTest(Base):
    def test_a_plan_waits_for_the_operator_whatever_its_tier(self):
        for paths in (TIER0, TIER2):
            res = self.plan([self.task(paths)], title="Plan %s" % paths[0])
            self.assertEqual(tickets.get(self.data, res["ticket"])["status"], "proposed")
            st = self.state(res["ticket"])
            self.assertEqual((st["phase"], st["plan"]["tasks"][0]["paths"]), ("awaiting_go", paths))
        self.assertEqual(self.spawned, [])

    def test_the_older_start_is_a_one_task_plan(self):
        res = self.request(TIER0)
        self.assertEqual(self.state(res["ticket"])["phase"], "awaiting_go")
        self.assertEqual(self.spawned, [])

    def test_bad_plans_are_refused(self):
        bad = ([], [self.task(TIER0)] * 9, [self.task(["tickets.py"])], [self.task(["tests/smoke.py"])],
               [dict(self.task(TIER0), role="ad")], [dict(self.task(TIER0), instruction="")],
               [self.task([])], [self.task(["../x"])], "not a list")
        for tasks in bad:
            with self.assertRaises(delegation.DelegationError, msg=tasks):
                self.plan(tasks)
        self.assertEqual(tickets.list_tickets(self.data), [])

    def test_evidence_is_still_required(self):
        with self.assertRaises(tickets.TicketError):
            delegation.plan("Fix it", [self.task(TIER0)], [], actor="chat-agent:x")

    def test_a_waiting_plan_can_be_replaced_but_not_a_running_one(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        self.plan([self.task(TIER0, "a"), self.task(TIER2, "b")], ticket_id=tid)
        self.assertEqual([t["title"] for t in self.state(tid)["plan"]["tasks"]], ["a", "b"])
        delegation.go(tid)
        with self.assertRaises(delegation.DelegationError):
            self.plan([self.task(TIER0)], ticket_id=tid)


class QueueTest(Base):
    """[실행] on files another ticket holds waits in the queue and starts once they are free (LEASE_SCOPE_v1)."""

    def hold(self, paths):
        t, _ = tickets.propose(self.data, "other work", "other", [CAND])
        tickets.approve(self.data, t["id"], operator=tickets.OPERATOR_UI)
        return t["id"], tickets.claim(self.data, t["id"], paths=paths, actor="claude-code")["token"]

    def test_go_on_held_files_queues_and_starts_when_they_are_free(self):
        other, token = self.hold(TIER0)
        tid = self.plan([self.task(TIER0)])["ticket"]
        res = delegation.go(tid)
        self.assertTrue(res["queued"])
        self.assertEqual(res["blocked_by"]["ticket"], other)
        card = [r for r in delegation.runs() if r["ticket"] == tid][0]
        self.assertEqual((card["phase"], card["blocked_by"]["paths"]), ("queued", TIER0))
        self.assertEqual(self.spawned, [])
        self.assertEqual(delegation.advance_queue(), [])           # still held
        tickets.release(self.data, other, token, "abandoned")
        self.assertEqual(delegation.advance_queue(), [tid])
        self.assertEqual(self.state(tid)["phase"], "starting")
        self.assertEqual(tickets.get(self.data, tid)["status"], "in_progress")

    def test_go_on_other_files_starts_at_once(self):
        self.hold(TIER2)
        tid = self.plan([self.task(TIER0)])["ticket"]
        self.assertNotIn("queued", delegation.go(tid))
        self.assertEqual(self.state(tid)["phase"], "starting")

    def test_a_queued_run_can_be_taken_out_of_the_queue(self):
        self.hold(TIER0)
        tid = self.plan([self.task(TIER0)])["ticket"]
        delegation.go(tid)
        code, body = delegation.delegation_api("POST", "/api/delegations/%d/unqueue" % tid, {})
        self.assertEqual((code, body["phase"]), (200, "awaiting_go"))
        self.assertEqual(delegation.advance_queue(), [])
        with self.assertRaises(delegation.DelegationError):
            delegation.unqueue(tid)

    def test_a_queued_run_that_can_no_longer_start_is_marked_failed(self):
        other, token = self.hold(TIER0)
        tid = self.plan([self.task(TIER0)])["ticket"]
        delegation.go(tid)
        tickets.decline(self.data, tid, operator=tickets.OPERATOR_UI)
        tickets.release(self.data, other, token, "abandoned")
        self.assertEqual(delegation.advance_queue(), [])
        self.assertEqual(self.state(tid)["phase"], "failed")
        self.assertIn("could not start from the queue", self.state(tid)["reason"])


class PlanPathsTest(Base):
    """A plan names files that exist; new files are declared (DELEGATION_CLARITY_v1)."""

    def test_a_guessed_file_is_refused_with_the_nearest_real_ones(self):
        with self.assertRaises(delegation.DelegationError) as cm:
            self.plan([self.task(["static/style.css"])])
        msg = str(cm.exception)
        self.assertIn("task 1: static/style.css does not exist", msg)
        self.assertIn("static/chat.css", msg)
        self.assertIn("creates", msg)

    def test_new_files_go_in_creates_and_join_the_scope(self):
        t = dict(self.task(["static/app.js"]), creates=["static/app-new.js"])
        tid = self.plan([t])["ticket"]
        self.assertEqual(self.state(tid)["plan"]["tasks"][0]["paths"], ["static/app.js", "static/app-new.js"])
        for bad, why in ((["static/app.js"], "already exists"), (["nope/x.js"], "folder nope does not exist")):
            with self.assertRaises(delegation.DelegationError) as cm:
                self.plan([dict(self.task(["static/app.js"]), creates=bad)])
            self.assertIn(why, str(cm.exception))

    def test_only_new_files_is_a_plan_too(self):
        tid = self.plan([{"role": "staff", "title": "t", "instruction": "i", "creates": ["static/app-new.js"]}])["ticket"]
        self.assertEqual(self.state(tid)["paths"], ["static/app-new.js"])


class AllowPathsTest(Base):
    """[경로 허용] (NEED_PATH_v1): the files a paused worker asked for join its task and the plan runs again."""

    def paused(self, asked):
        tid = self.plan([self.task(TIER0)])["ticket"]
        delegation.go(tid)
        tickets.drop_lease(self.data, operator=tickets.OPERATOR_UI, ticket_id=tid)   # the runner released it
        delegation.runner().write_state(tid, phase="paused", need_paths=asked, need_task=1, kept=True)
        self.spawned.clear()
        return tid

    def test_allowing_adds_the_files_and_runs_again(self):
        (delegation.PLAN_ROOT / "data/workspace/notes/y.md").write_text("y")
        tid = self.paused([{"path": "data/workspace/notes/y.md", "why": "the list is there"}])
        res = delegation.allow(tid)
        self.assertEqual(res["allowed"], ["data/workspace/notes/y.md"])
        st = self.state(tid)
        self.assertIn("data/workspace/notes/y.md", st["plan"]["tasks"][0]["paths"])
        self.assertEqual(st["need_paths"], [])
        args = self.spawned[-1][1]
        self.assertIn("data/workspace/notes/y.md", args[args.index("--paths") + 1])

    def test_tier_3_missing_folders_and_other_phases_are_refused(self):
        for asked in ([{"path": "tickets.py"}], [{"path": "nope/dir/x.md"}]):
            tid = self.paused(asked)
            with self.assertRaises(delegation.DelegationError):
                delegation.allow(tid)
        tid = self.plan([self.task(TIER0)])["ticket"]
        with self.assertRaises(delegation.DelegationError):
            delegation.allow(tid)


class OperatorTest(Base):
    def test_go_approves_as_the_operator_and_runs_the_plan_to_final_confirmation(self):
        tid = self.plan([self.task(TIER0), self.task(TIER2)])["ticket"]
        delegation.go(tid)
        t = tickets.get(self.data, tid)
        self.assertEqual((t["status"], t["approved_by"]), ("in_progress", "operator (ui)"))
        args = self.spawned[-1][1]
        for flag in ("--plan-from-state", "--stop-before-merge"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--paths") + 1], ",".join(sorted(TIER0 + TIER2)))
        self.assertEqual(self.state(tid)["phase"], "starting")

    def test_go_on_a_ticket_from_elsewhere_makes_a_one_task_plan(self):
        t, _ = tickets.propose(self.data, "fix notes", TIER0[0], [CAND])
        delegation.go(t["id"])
        self.assertEqual(self.state(t["id"])["plan"]["tasks"][0]["paths"], TIER0)

    def test_go_on_a_ticket_without_files_is_refused(self):
        t, _ = tickets.propose(self.data, "vague", "make it better", [CAND])
        with self.assertRaises(delegation.DelegationError):
            delegation.go(t["id"])

    def awaiting(self):
        tid = self.plan([self.task(TIER2)])["ticket"]
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

    def test_the_run_is_marked_merging_before_the_runner_starts(self):
        tid = self.awaiting()
        seen = []
        delegation._spawn = lambda t, args: seen.append(self.state(t)["phase"]) or 1
        delegation.merge(tid)
        self.assertEqual(seen, ["merging"])

    def test_a_merge_whose_process_died_can_be_retried(self):
        tid = self.awaiting()
        delegation.merge(tid)
        delegation.runner().write_state(tid, pid=999999)          # the merge process is gone
        card = [r for r in delegation.runs() if r["ticket"] == tid][0]
        self.assertEqual((card["phase"], card["stalled_in"]), ("stalled", "merging"))
        delegation.merge(tid)                                      # [승인 다시]
        self.assertEqual(self.spawned[-1][1][:3], ["merge", "--ticket", str(tid)])
        self.assertEqual(tickets.get(self.data, tid)["status"], "in_progress")

    def test_merge_needs_a_waiting_change(self):
        tid = self.plan([self.task(TIER2)])["ticket"]
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

    def test_rework_sends_it_back_with_the_comment(self):
        tid = self.awaiting()
        delegation.rework(tid, "shorter please")
        args = self.spawned[-1][1]
        self.assertIn("--resume", args)
        self.assertEqual(args[args.index("--prompt") + 1], "shorter please")
        self.assertEqual(tickets.get(self.data, tid)["attempts"], 2)

    def test_a_rework_that_cannot_start_keeps_waiting(self):
        tid = self.awaiting()

        def broken(tid, args):
            raise OSError("no python")
        delegation._spawn = broken
        with self.assertRaises(delegation.DelegationError):
            delegation.rework(tid, "shorter")
        self.assertEqual(tickets.get(self.data, tid)["status"], "awaiting_merge")
        self.assertEqual(self.state(tid)["phase"], "awaiting_merge")

    def test_discard_declines_and_drops_the_branch(self):
        tid = self.awaiting()
        delegation.discard(tid)
        self.assertEqual(tickets.get(self.data, tid)["status"], "declined")
        self.assertEqual(self.cleaned, ["worktree/ticket-%d" % tid])
        self.assertEqual(self.state(tid)["phase"], "declined")

    def test_a_stalled_run_can_be_discarded(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        delegation.go(tid)                                  # claimed; its runner "died"
        delegation.runner().write_state(tid, phase="writing", pid=999999)
        delegation.discard(tid)
        self.assertEqual(tickets.get(self.data, tid)["status"], "declined")
        self.assertIsNone(tickets._read_lease(self.data))

    def test_a_running_plan_cannot_be_discarded(self):
        import os
        tid = self.plan([self.task(TIER0)])["ticket"]
        delegation.go(tid)
        delegation.runner().write_state(tid, phase="writing", pid=os.getpid())   # alive
        with self.assertRaises(delegation.DelegationError):
            delegation.discard(tid)


class CardsTest(Base):
    def test_cards_show_phase_seen_and_a_stalled_run(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
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
        self.assertEqual(delegation.delegation_api("POST", "/api/delegations/%d/rework" % tid, {"comment": "x"})[0], 400)
        code, body = delegation.delegation_api("POST", "/api/delegations/%d/go" % tid, {})
        self.assertEqual((code, body["ticket"]), (200, tid))
        self.assertEqual(delegation.runs()[0]["tasks"][0]["role"], "staff")


class ToolTest(Base):
    def test_the_tool_server_offers_delegate_and_refuses_operator_actions(self):
        import mcp_server
        self.assertIn("delegate", [t["name"] for t in mcp_server.tool_defs()])
        res = mcp_server.call_tool("delegate", {"action": "status"})
        self.assertTrue(res.get("success"), res)
        res = mcp_server.call_tool("delegate", {"action": "merge"})
        self.assertFalse(res.get("success"))
        import re as _re
        r = delegation.tool_call("delegate", {"action": "status"}, "chat-agent:x", _re.compile("SECRET"),
                                 mcp_server.envelope, private=True)
        self.assertFalse(r["success"])
        self.assertIn("private session", r["message"])


class LiveRequestRefTest(unittest.TestCase):
    def test_the_operator_s_latest_message_is_the_default_evidence(self):
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
        with mock.patch.object(delegation, "DATA", data), \
                mock.patch("urllib.request.urlopen", return_value=Resp(b'{"id": "s-1"}')):
            self.assertEqual(delegation.latest_request_ref(), "event:s-1#4")
        with mock.patch.object(delegation, "DATA", data), \
                mock.patch("urllib.request.urlopen", return_value=Resp(b'{"id": "../x"}')):
            self.assertIsNone(delegation.latest_request_ref())


if __name__ == "__main__":
    unittest.main()
