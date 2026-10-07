"""delegation.py: who may start, land or drop delegated work, and what the work cards read.
The runner itself is tested in tests/test_worktree_runner.py; here its launch is recorded, not run.
Run: engine/run-tests.sh test_delegation
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
# delegation is a dev-build feature (edition-boundary); pin the edition before host_config is first imported
os.environ.setdefault("CHATBOT_EDITION", "dev")
import delegation  # noqa: E402
import tickets  # noqa: E402
# Run in one process with other test modules, host_config may already have read the shipped edition before the line
# above: the tool server is pinned to dev only while this module runs (split/A).
_DEV = mock.patch.object(__import__("mcp_server"), "EDITION", "dev")
setUpModule, tearDownModule = _DEV.start, _DEV.stop

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
        s_id, p_id, ws = characters.new_id(), characters.new_id(), self.data / "workspace"
        characters.save(s_id, characters.new_card("S"), ws)
        characters.save(p_id, characters.new_card("P"), ws)
        # the default character delegates and is not an expert, whatever its roles are called (the engine knows none)
        characters.save_team({"default": p_id, "members": {s_id: ["staff"], p_id: ["pd"]}}, ws)
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

    def ended(self, outcome, runs=1):
        paths = TIER0 if outcome == "gate_failed" else TIER2   # one open ticket per target
        tid = self.plan([self.task(paths)])["ticket"]
        tickets.approve(self.data, tid, operator=tickets.OPERATOR_UI)
        for _ in range(runs):
            c = tickets.claim(self.data, tid, paths=paths)
            tickets.release(self.data, tid, c["token"], outcome)
        delegation.runner().write_state(tid, phase=outcome, reason="gate said no", transcript=["old"], task=1)
        return tid

    def test_a_gate_failed_plan_can_be_replaced_under_the_same_id(self):
        for outcome in ("gate_failed", "failed"):
            tid = self.ended(outcome)
            res = self.plan([self.task(TIER0, "fixed")], ticket_id=tid)
            self.assertEqual(res["ticket"], tid)
            st = self.state(tid)
            self.assertEqual((st["phase"], st["reason"], st["transcript"], st["task"]), ("awaiting_go", "", [], 0))
            self.assertEqual(st["plan"]["tasks"][0]["title"], "fixed")
            t = tickets.get(self.data, tid)
            self.assertEqual((t["status"], t["attempts"]), ("approved", 1))
            self.assertEqual(t["gate_failures"], 1 if outcome == "gate_failed" else 0)

    def test_a_spent_ticket_cannot_be_replanned(self):
        tid = self.ended("gate_failed", runs=tickets.MAX_ATTEMPTS)
        with self.assertRaises(delegation.DelegationError) as cm:
            self.plan([self.task(TIER0)], ticket_id=tid)
        self.assertIn("used all %d attempts; open a new ticket" % tickets.MAX_ATTEMPTS, str(cm.exception))

    def test_running_or_awaiting_merge_tickets_cannot_be_replanned(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        delegation.go(tid)
        for phase in ("running", "awaiting_merge"):
            delegation.runner().write_state(tid, phase=phase)
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

    def test_reads_stay_out_of_the_scope_and_the_tier(self):
        tid = self.plan([dict(self.task(TIER0), reads=TIER2 + TIER0)])["ticket"]
        st = self.state(tid)
        self.assertEqual((st["tier"], st["paths"]), (0, TIER0))
        self.assertEqual(st["plan"]["tasks"][0]["reads"], TIER2)
        with self.assertRaises(delegation.DelegationError) as cm:
            self.plan([dict(self.task(TIER0), reads=["static/style.css"])])
        self.assertIn("reads static/style.css does not exist", str(cm.exception))

    def test_only_new_files_is_a_plan_too(self):
        tid = self.plan([{"role": "staff", "title": "t", "instruction": "i", "creates": ["static/app-new.js"]}])["ticket"]
        self.assertEqual(self.state(tid)["paths"], ["static/app-new.js"])

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(delegation.PLAN_ROOT),
                       check=True, capture_output=True)

    def test_uncommitted_files_are_refused_before_run(self):
        self.git("init", "-q")
        self.git("add", "static/chat.css")
        self.git("commit", "-qm", "init")
        tid = self.plan([self.task(["static/chat.css"])])["ticket"]              # clean: a plan
        for rel in ("static/app.js", "static/chat.css"):                          # untracked, then modified
            if rel == "static/chat.css":
                (delegation.PLAN_ROOT / rel).write_text("changed", encoding="utf-8")
            for ticket_id in (None, tid):
                with self.assertRaises(delegation.DelegationError) as cm:
                    self.plan([self.task([rel])], ticket_id=ticket_id)
                self.assertIn("uncommitted: " + rel, str(cm.exception))
        self.git("checkout", "--", "static/chat.css")
        t = dict(self.task(["static/chat.css"]), creates=["static/app-new.js"])  # creates-only files are exempt
        self.assertTrue(self.plan([t])["ticket"])


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

    def test_the_page_sees_a_tier_3_request_as_operator_only(self):
        # #381: the card must not offer [경로 허용] for a file allow() will always refuse
        (delegation.PLAN_ROOT / "data/workspace/notes/y.md").write_text("y")
        tid = self.paused([{"path": "tickets.py", "why": "guard"}, {"path": "data/workspace/notes/y.md"}])
        run = next(r for r in delegation.runs() if r["ticket"] == tid)
        flags = {n["path"]: bool(n.get("operator_only")) for n in run["need_paths"]}
        self.assertEqual(flags, {"tickets.py": True, "data/workspace/notes/y.md": False})


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

    def test_go_goes_on_from_the_attic_when_a_failed_attempt_left_one(self):
        saved = delegation._has_attic
        try:
            for has, paths in ((False, TIER0), (True, TIER2)):
                delegation._has_attic = lambda tid, has=has: has
                tid = self.plan([self.task(paths)], title="attic %s" % has)["ticket"]
                delegation.go(tid)
                self.assertEqual("--from-attic" in self.spawned[-1][1], has)
        finally:
            delegation._has_attic = saved

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

    def test_approving_a_landed_run_whose_ticket_stayed_open_closes_the_ticket(self):
        # MERGED_CLOSE_v1 (#371, 2026-09-29): merged, but the lease ran out before the ticket closed; the card still
        # offered [승인] and the merge was refused ("no delegated change awaiting a merge")
        tid = self.awaiting()
        r = delegation.runner()
        r.write_state(tid, phase="merged-ticket-open", head="af2f5763d656")
        spawned = len(self.spawned)
        with mock.patch.object(r, "git", return_value=(0, "", "")) as git, \
                mock.patch.object(tickets, "_guard_failure", return_value=""):
            out = delegation.merge(tid)
        self.assertEqual(git.call_args[0][1:], ("merge-base", "--is-ancestor", "af2f5763d656", "HEAD"))
        self.assertEqual((out["status"], out["healed"]), ("done", True))
        self.assertEqual(tickets.get(self.data, tid)["status"], "done")
        self.assertEqual(self.state(tid)["phase"], "done")
        self.assertEqual(len(self.spawned), spawned, "nothing to land again")

    def test_a_landed_run_whose_runner_left_its_lease_behind_still_closes(self):
        # #387: the done gate refused right after the merge; the dead runner's lease held the files for an hour
        tid = self.awaiting()
        tickets.merge_go(self.data, tid, operator=tickets.OPERATOR_UI, actor="agy")      # the runner's lease
        self.assertEqual(tickets.get(self.data, tid)["status"], "in_progress")
        r = delegation.runner()
        r.write_state(tid, phase="merged-ticket-open", head="af2f5763d656", pid=0)
        with mock.patch.object(r, "git", return_value=(0, "", "")), \
                mock.patch.object(tickets, "_guard_failure", return_value=""):
            out = delegation.merge(tid)
        self.assertEqual(out["status"], "done")
        self.assertEqual([l for l in tickets.leases(self.data) if l["ticket"] == tid], [])

    def test_a_user_data_plan_runs_as_content_work(self):
        # CONTENT_WORK_v1 (#392): a gallery picture needs no worktree, gates, review or merge
        tid = self.plan([self.task(TIER0)])["ticket"]
        with mock.patch.object(tickets, "is_content", return_value=True):
            delegation.go(tid)
        self.assertIn("--content", self.spawned[-1][1])

    def test_a_landed_run_is_closed_only_when_its_commit_is_on_main(self):
        tid = self.awaiting()
        r = delegation.runner()
        r.write_state(tid, phase="merged-ticket-open", head="deadbeef")
        with mock.patch.object(r, "git", return_value=(1, "", "")):
            with self.assertRaises(delegation.DelegationError):
                delegation.merge(tid)
        self.assertEqual(tickets.get(self.data, tid)["status"], "awaiting_merge")

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

    def test_finalized_ticket_auto_rectifies_and_marks_seen(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        self.assertEqual(self.state(tid)["phase"], "awaiting_go")
        tickets.approve(self.data, tid, operator=tickets.OPERATOR_UI)
        c = tickets.claim(self.data, tid, paths=TIER0)
        tickets.release(self.data, tid, c["token"], "done")
        self.assertEqual(tickets.get(self.data, tid)["status"], "done")
        card = [r for r in delegation.runs() if r["ticket"] == tid][0]
        self.assertEqual(card["phase"], "done")
        self.assertTrue(card["seen"])
        self.assertEqual(self.state(tid)["phase"], "done")

    def test_declined_ticket_auto_rectifies_and_marks_seen(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        tickets.decline(self.data, tid, operator=tickets.OPERATOR_UI)
        self.assertEqual(tickets.get(self.data, tid)["status"], "declined")
        card = [r for r in delegation.runs() if r["ticket"] == tid][0]
        self.assertEqual(card["phase"], "declined")
        self.assertTrue(card["seen"])
        self.assertEqual(self.state(tid)["phase"], "declined")

    def test_go_on_finalized_ticket_heals_instead_of_failing(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        tickets.approve(self.data, tid, operator=tickets.OPERATOR_UI)
        c = tickets.claim(self.data, tid, paths=TIER0)
        tickets.release(self.data, tid, c["token"], "done")
        res = delegation.go(tid)
        self.assertTrue(res.get("healed"))
        self.assertEqual(res.get("status"), "done")
        self.assertEqual(self.state(tid)["phase"], "done")
        self.assertTrue([r for r in delegation.runs() if r["ticket"] == tid][0]["seen"])

    def test_discard_on_already_closed_ticket_succeeds(self):
        tid = self.plan([self.task(TIER0)])["ticket"]
        tickets.approve(self.data, tid, operator=tickets.OPERATOR_UI)
        c = tickets.claim(self.data, tid, paths=TIER0)
        tickets.release(self.data, tid, c["token"], "done")
        res = delegation.discard(tid)
        self.assertEqual(res["status"], "done")
        self.assertEqual(self.state(tid)["phase"], "declined")
        self.assertTrue([r for r in delegation.runs() if r["ticket"] == tid][0]["seen"])

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
    def setUp(self):
        super().setUp()
        # The tool server asks the running chat server who is mid-turn (mcp_server._live_scope); a real turn by a
        # character without the PD role on this host (the operator chatting while tests ran) made this fail.
        import mcp_server
        self._scope = mcp_server._live_scope
        mcp_server._live_scope = lambda grant: (False, False)

    def tearDown(self):
        import mcp_server
        mcp_server._live_scope = self._scope
        super().tearDown()

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
        with mock.patch.object(delegation, "DATA", data), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("asked the screen")):
            self.assertEqual(delegation.latest_request_ref("s-1"), "event:s-1#4")   # the caller's own session


if __name__ == "__main__":
    unittest.main()
