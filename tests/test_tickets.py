"""tickets.py: evidence, merging, attempt budget, the single author lease, operator-only decisions.
Run: python3 -m unittest tests.test_tickets  (from services/chatbot)
"""
import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import tickets  # noqa: E402

T0 = 1_800_000_000.0
EVENT = "event:s1#2"
CAND = "candidate:1789908287.39"


class Base(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        (self.data / "sessions" / "s1").mkdir(parents=True)
        (self.data / "sessions" / "s1" / "events.jsonl").write_text('{"event":"system"}\n{"event":"error"}\n', encoding="utf-8")
        obs = self.data / "workspace" / "skill-observations"
        obs.mkdir(parents=True)
        (obs / "candidates.jsonl").write_text(json.dumps({"epoch": 1789908287.39, "signal": "correction"}) + "\n", encoding="utf-8")

    def propose(self, target="session.py: steer", title="Steer loses the queue", evidence=None, now=T0):
        return tickets.propose(self.data, title, target, evidence or [EVENT], now=now)

    def approved(self, **kw):
        t, _ = self.propose(**kw)
        return tickets.approve(self.data, t["id"], now=T0, operator=tickets.OPERATOR_CONFIRMED)

    def raw(self, tid):
        return json.loads((tickets.tickets_dir(self.data) / ("%04d.json" % tid)).read_text(encoding="utf-8"))


class EvidenceTest(Base):
    def test_real_events_and_candidates_are_accepted(self):
        for ref in ("event:s1#1", "event:s1#2", CAND, "candidate:1789908287.390"):
            tickets.verify_evidence(self.data, ref)

    def test_invented_or_malformed_evidence_is_refused(self):
        for ref in ("event:s1#3", "event:nope#1", "event:s1#0", "event:s1", "event:../s1#1", "event:s1/../s1#1",
                    "candidate:1.5", "candidate:", "metric:latency=3", "it felt slow", "", "event:#1"):
            with self.assertRaises(tickets.TicketError, msg=ref):
                tickets.verify_evidence(self.data, ref)

    def test_a_ticket_without_evidence_is_an_opinion(self):
        for ev in (None, [], "", 5):
            with self.assertRaises(tickets.TicketError):
                tickets.propose(self.data, "t", "x", ev, now=T0)
        with self.assertRaises(tickets.TicketError):
            tickets.propose(self.data, "t", "x", ["event:s1#99"], now=T0)
        self.assertEqual(tickets.list_tickets(self.data), [])


class ProposeTest(Base):
    def test_creates_a_proposed_ticket_with_the_evidence(self):
        t, merged = self.propose(evidence=[EVENT, CAND, EVENT])
        self.assertFalse(merged)
        self.assertEqual((t["id"], t["status"], t["attempts"], t["evidence"]), (1, "proposed", 0, [EVENT, CAND]))
        self.assertEqual(self.raw(1)["target"], "session.py: steer")

    def test_same_target_is_merged_not_duplicated(self):
        first, _ = self.propose(evidence=[EVENT])
        again, merged = self.propose(target="  SESSION.py:   Steer ", title="other words", evidence=[EVENT, CAND])
        self.assertTrue(merged)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(again["evidence"], [EVENT, CAND])
        self.assertEqual(len(tickets.list_tickets(self.data)), 1)

    def test_a_closed_ticket_does_not_absorb_a_new_proposal(self):
        t, _ = self.propose()
        tickets.decline(self.data, t["id"], operator=tickets.OPERATOR_CONFIRMED)
        new, merged = self.propose()
        self.assertFalse(merged)
        self.assertEqual(new["id"], 2)

    def test_different_targets_get_different_tickets(self):
        self.propose(target="a")
        self.propose(target="b")
        self.assertEqual([r["id"] for r in tickets.list_tickets(self.data)], [1, 2])

    def test_a_backlog_of_unreviewed_proposals_stops_new_ones(self):
        for i in range(tickets.MAX_PROPOSED):
            self.propose(target="t%d" % i)
        with self.assertRaises(tickets.TicketError) as cm:
            self.propose(target="one more")
        self.assertIn("waiting for the operator", str(cm.exception))
        self.propose(target="t0")  # merging into an existing one is still fine

    def test_missing_values_are_empty_not_the_word_none(self):
        for title, target in ((None, "x"), ("t", None), (None, None), ("", "x")):
            with self.assertRaises(tickets.TicketError, msg=(title, target)):
                tickets.propose(self.data, title, target, [EVENT], now=T0)
        t = self.approved()
        with self.assertRaises(tickets.TicketError):
            tickets.add_note(self.data, t["id"], None)
        c = tickets.claim(self.data, t["id"], now=T0)
        r = tickets.release(self.data, t["id"], c["token"], "abandoned", None, now=T0)  # no text is fine
        self.assertNotIn("None", json.dumps(r["ticket"]["notes"]))
        self.assertEqual(tickets.list_tickets(self.data)[0]["title"], "Steer loses the queue")

    def test_a_single_reference_given_as_a_plain_string_is_accepted(self):
        t, _ = self.propose(evidence="event:s1#1")
        self.assertEqual(t["evidence"], ["event:s1#1"])

    def test_bounds(self):
        t, _ = self.propose(title="x" * 500, target="y" * 500)
        self.assertLessEqual(len(t["title"]), 120)
        self.assertLessEqual(len(t["target"]), 80)


class OperatorDecisionsTest(Base):
    def test_only_a_proposed_ticket_can_be_approved(self):
        t, _ = self.propose()
        self.assertEqual(tickets.approve(self.data, t["id"], now=T0, operator=tickets.OPERATOR_CONFIRMED)["status"], "approved")
        with self.assertRaises(tickets.TicketError):
            tickets.approve(self.data, t["id"], operator=tickets.OPERATOR_CONFIRMED)

    def test_decline_and_unknown_ids(self):
        t, _ = self.propose()
        self.assertEqual(tickets.decline(self.data, t["id"], operator=tickets.OPERATOR_CONFIRMED)["status"], "declined")
        for bad in (99, "x", None):
            with self.assertRaises(tickets.TicketError):
                tickets.get(self.data, bad)

    def test_reopen_gives_a_wontfix_ticket_a_fresh_budget(self):
        t = self.approved()
        for _ in range(tickets.MAX_ATTEMPTS):
            c = tickets.claim(self.data, t["id"], now=T0)
            tickets.release(self.data, t["id"], c["token"], "failed", now=T0)
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "wontfix")
        r = tickets.reopen(self.data, t["id"], operator=tickets.OPERATOR_CONFIRMED)
        self.assertEqual((r["status"], r["attempts"], r["gate_failures"]), ("approved", 0, 0))
        with self.assertRaises(tickets.TicketError):
            tickets.reopen(self.data, t["id"], operator=tickets.OPERATOR_CONFIRMED)


class ClaimTest(Base):
    def test_only_an_approved_ticket_can_be_worked_on(self):
        t, _ = self.propose()
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.claim(self.data, t["id"], now=T0)
        self.assertIn("approved", str(cm.exception))
        self.assertEqual(tickets.get(self.data, t["id"])["attempts"], 0)

    def test_claim_counts_an_attempt_and_hands_out_a_token(self):
        t = self.approved()
        c = tickets.claim(self.data, t["id"], now=T0)
        self.assertTrue(c["new_attempt"])
        self.assertEqual((c["ticket"]["status"], c["ticket"]["attempts"], c["attempts_left"]), ("in_progress", 1, 2))
        self.assertEqual(len(c["token"]), 32)
        self.assertEqual(c["expires_in_sec"], tickets.LEASE_TTL_SEC)

    def test_the_holder_extends_without_spending_an_attempt(self):
        t = self.approved()
        c = tickets.claim(self.data, t["id"], now=T0)
        again = tickets.claim(self.data, t["id"], token=c["token"], now=T0 + 600)
        self.assertFalse(again["new_attempt"])
        self.assertEqual(again["ticket"]["attempts"], 1)
        self.assertEqual(again["expires_in_sec"], tickets.LEASE_TTL_SEC)

    def test_a_second_author_is_refused_at_once_and_leaves_a_note(self):
        a = self.approved(target="a")
        b = self.approved(target="b")
        tickets.claim(self.data, a["id"], now=T0)
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.claim(self.data, b["id"], now=T0 + 5)
        self.assertIn("not waiting", str(cm.exception))
        note = tickets.get(self.data, b["id"])["notes"][-1]
        self.assertIn("author lock is held for ticket %d" % a["id"], note["text"])
        self.assertEqual(tickets.get(self.data, b["id"])["attempts"], 0)
        with self.assertRaises(tickets.TicketError):  # same ticket, no token: also a stranger
            tickets.claim(self.data, a["id"], now=T0 + 6)
        with self.assertRaises(tickets.TicketError):  # a wrong token is a stranger too
            tickets.claim(self.data, a["id"], token="0" * 32, now=T0 + 6)

    def test_an_expired_lease_lets_the_next_author_in_and_frees_the_old_ticket(self):
        a = self.approved(target="a")
        b = self.approved(target="b")
        tickets.claim(self.data, a["id"], now=T0)
        later = T0 + tickets.LEASE_TTL_SEC + 1
        c = tickets.claim(self.data, b["id"], now=later)
        self.assertTrue(c["new_attempt"])
        old = tickets.get(self.data, a["id"])
        self.assertEqual(old["status"], "approved")
        self.assertIn("author lease expired", old["notes"][-1]["text"])

    def test_the_same_ticket_can_be_retaken_after_its_lease_expired(self):
        t = self.approved()
        tickets.claim(self.data, t["id"], now=T0)
        c = tickets.claim(self.data, t["id"], now=T0 + tickets.LEASE_TTL_SEC + 1)
        self.assertEqual(c["ticket"]["attempts"], 2)

    def test_the_attempt_budget_closes_the_ticket_for_a_human(self):
        t = self.approved()
        for n in range(tickets.MAX_ATTEMPTS):
            c = tickets.claim(self.data, t["id"], now=T0)
            self.assertEqual(c["ticket"]["attempts"], n + 1)
            tickets.release(self.data, t["id"], c["token"], "abandoned", now=T0)
        closed = tickets.get(self.data, t["id"])
        self.assertEqual((closed["status"], closed["closed_reason"]), ("wontfix", "needs-human"))
        with self.assertRaises(tickets.TicketError):
            tickets.claim(self.data, t["id"], now=T0)

    def test_an_author_who_vanishes_without_releasing_still_spends_the_budget(self):
        # crashes never call release: only the claim-time check can end this ticket
        t = self.approved()
        now = T0
        for n in range(tickets.MAX_ATTEMPTS):
            self.assertEqual(tickets.claim(self.data, t["id"], now=now)["ticket"]["attempts"], n + 1)
            now += tickets.LEASE_TTL_SEC + 1
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.claim(self.data, t["id"], now=now)
        self.assertIn("needs-human", str(cm.exception))
        closed = tickets.get(self.data, t["id"])
        self.assertEqual((closed["status"], closed["closed_reason"], closed["attempts"]), ("wontfix", "needs-human", 3))

    def test_exactly_one_of_many_simultaneous_claims_wins(self):
        t = self.approved()
        results = []

        def go():
            try:
                results.append(tickets.claim(self.data, t["id"]))
            except tickets.TicketError as e:
                results.append(e)
        threads = [threading.Thread(target=go) for _ in range(8)]
        [x.start() for x in threads]
        [x.join() for x in threads]
        wins = [r for r in results if isinstance(r, dict)]
        self.assertEqual(len(wins), 1)
        self.assertEqual(tickets.get(self.data, t["id"])["attempts"], 1)

    def test_the_token_is_never_stored_in_the_clear(self):
        t = self.approved()
        c = tickets.claim(self.data, t["id"], now=T0)
        for path in tickets.tickets_dir(self.data).iterdir():
            if path.is_file():
                self.assertNotIn(c["token"], path.read_text(encoding="utf-8"), path.name)
        self.assertIn("token_sha256", (tickets.tickets_dir(self.data) / "author.lease").read_text(encoding="utf-8"))
        self.assertNotIn(c["token"], json.dumps(tickets.get(self.data, t["id"])))


class ReleaseTest(Base):
    def claimed(self, **kw):
        t = self.approved(**kw)
        return t, tickets.claim(self.data, t["id"], now=T0)

    def test_done_closes_the_ticket_and_frees_the_lock(self):
        t, c = self.claimed()
        r = tickets.release(self.data, t["id"], c["token"], "done", "tests pass", now=T0)
        self.assertEqual((r["ticket"]["status"], r["ticket"]["closed_reason"]), ("done", "done"))
        self.assertFalse((tickets.tickets_dir(self.data) / "author.lease").exists())
        other = self.approved(target="other")
        tickets.claim(self.data, other["id"], now=T0)  # the lock is free again

    def test_the_wrong_expired_or_missing_token_cannot_release(self):
        t, c = self.claimed()
        for token in (None, "", "0" * 32):
            with self.assertRaises(tickets.TicketError):
                tickets.release(self.data, t["id"], token, "done", now=T0)
        with self.assertRaises(tickets.TicketError):
            tickets.release(self.data, t["id"], c["token"], "done", now=T0 + tickets.LEASE_TTL_SEC + 1)
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "in_progress")

    def test_an_unknown_outcome_is_refused(self):
        t, c = self.claimed()
        with self.assertRaises(tickets.TicketError):
            tickets.release(self.data, t["id"], c["token"], "success", now=T0)

    def test_two_gate_failures_in_a_row_advise_a_new_approach(self):
        t = self.approved()
        c1 = tickets.claim(self.data, t["id"], now=T0)
        r1 = tickets.release(self.data, t["id"], c1["token"], "gate_failed", now=T0)
        self.assertIn("2 attempt(s) left", r1["advice"])
        c2 = tickets.claim(self.data, t["id"], now=T0)
        r2 = tickets.release(self.data, t["id"], c2["token"], "gate_failed", now=T0)
        self.assertIn("change the approach", r2["advice"])
        self.assertEqual(r2["ticket"]["gate_failures"], 2)
        self.assertEqual(r2["ticket"]["status"], "approved")

    def test_the_last_attempt_failing_ends_in_needs_human(self):
        t = self.approved()
        for _ in range(tickets.MAX_ATTEMPTS):
            c = tickets.claim(self.data, t["id"], now=T0)
            r = tickets.release(self.data, t["id"], c["token"], "failed", now=T0)
        self.assertIn("tell the operator", r["advice"])
        self.assertEqual(r["ticket"]["status"], "wontfix")

    def test_notes_by_the_author_keep_the_lease_alive(self):
        t, c = self.claimed()
        tickets.add_note(self.data, t["id"], "still working", token=c["token"], now=T0 + 1500)
        self.assertEqual(tickets.claim(self.data, t["id"], token=c["token"], now=T0 + 3000)["new_attempt"], False)

    def test_anyone_can_leave_a_note_but_not_keep_a_lease_alive(self):
        t, c = self.claimed()
        tickets.add_note(self.data, t["id"], "a comment", token=None, now=T0 + 1500)
        with self.assertRaises(tickets.TicketError):  # the stranger's note did not extend it: it ran out on schedule
            tickets.release(self.data, t["id"], c["token"], "done", now=T0 + tickets.LEASE_TTL_SEC + 1)
        with self.assertRaises(tickets.TicketError):
            tickets.add_note(self.data, t["id"], "  ")


class OperatorToolsTest(Base):
    def test_drop_lease_frees_a_crashed_session_s_ticket(self):
        t = self.approved()
        tickets.claim(self.data, t["id"], now=T0)
        lease = tickets.drop_lease(self.data, now=T0, operator=tickets.OPERATOR_CONFIRMED)
        self.assertEqual(lease["ticket"], t["id"])
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "approved")
        self.assertIsNone(tickets.drop_lease(self.data, operator=tickets.OPERATOR_CONFIRMED))

    def test_reading_needs_no_terminal(self):
        t, _ = self.propose()
        with mock.patch.dict(os.environ, {"AGY_CHAT_DATA": str(self.data)}):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(tickets.main(["list"]), 0)
                self.assertEqual(tickets.main(["show", str(t["id"])]), 0)
            self.assertIn("Steer loses the queue", out.getvalue())
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(tickets.main(["bogus"]), 2)


class OperatorOnlyTest(Base):
    """Approving, declining, reopening and dropping the lease are for a person at a terminal."""

    def cli(self, *args, stdin=None):
        env = dict(os.environ, AGY_CHAT_DATA=str(self.data))
        return subprocess.run([sys.executable, str(CODE / "tickets.py")] + list(args), env=env, stdin=stdin,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30)

    def test_the_api_refuses_a_caller_that_does_not_say_who_is_asking(self):
        t, _ = self.propose()
        for fn in (tickets.approve, tickets.decline, tickets.reopen, tickets.drop_lease):
            args = (self.data,) if fn is tickets.drop_lease else (self.data, t["id"])
            for kw in ({}, {"operator": None}, {"operator": ""}, {"operator": "operator"}, {"operator": "agent"}):
                with self.assertRaises(tickets.TicketError, msg="%s %s" % (fn.__name__, kw)) as cm:
                    fn(*args, **kw)
                self.assertIn("for the operator", str(cm.exception))
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "proposed")
        self.assertEqual(tickets.get(self.data, t["id"])["notes"], [])

    def test_the_record_says_how_the_operator_asked(self):
        a, _ = self.propose(target="a")
        b, _ = self.propose(target="b")
        tickets.approve(self.data, a["id"], operator=tickets.OPERATOR_TTY)
        tickets.approve(self.data, b["id"], operator=tickets.OPERATOR_CONFIRMED)
        self.assertEqual(tickets.get(self.data, a["id"])["notes"][-1]["by"], "operator (tty)")
        self.assertEqual(tickets.get(self.data, b["id"])["notes"][-1]["by"], "operator (api)")

    def test_a_shell_without_a_terminal_cannot_use_the_command_line(self):
        t, _ = self.propose()
        for cmd in ("approve", "decline", "reopen"):
            r = self.cli(cmd, str(t["id"]), stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 1, cmd)
            self.assertIn("ask the operator", r.stderr)
        r = self.cli("drop-lease", stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1)
        piped = subprocess.run([sys.executable, str(CODE / "tickets.py"), "approve", str(t["id"])],
                               input="%d\n" % t["id"], env=dict(os.environ, AGY_CHAT_DATA=str(self.data)),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
        self.assertEqual(piped.returncode, 1)  # typing the right number into a pipe is not enough
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "proposed")

    def with_terminal(self, typed, *args):
        import pty
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen([sys.executable, str(CODE / "tickets.py")] + list(args), stdin=slave, stdout=slave,
                                    stderr=slave, env=dict(os.environ, AGY_CHAT_DATA=str(self.data)), close_fds=True)
            os.close(slave)
            os.write(master, typed.encode("utf-8"))
            proc.wait(timeout=30)
            out = b""
            try:
                import select
                while select.select([master], [], [], 0.2)[0]:
                    chunk = os.read(master, 4096)
                    if not chunk:
                        break
                    out += chunk
            except OSError:
                pass
            return proc.returncode, out.decode("utf-8", "replace")
        finally:
            os.close(master)

    def test_a_person_at_a_terminal_can_decide_after_retyping_the_number(self):
        try:
            import pty  # noqa: F401
        except ImportError:
            self.skipTest("no pty on this platform")
        t, _ = self.propose()
        rc, out = self.with_terminal("%d\n" % t["id"], "approve", str(t["id"]))
        self.assertEqual(rc, 0, out)
        self.assertIn("is now approved", out)
        note = tickets.get(self.data, t["id"])["notes"][-1]
        self.assertEqual((note["by"], note["text"]), ("operator (tty)", "approved"))

    def test_a_wrong_or_empty_confirmation_changes_nothing(self):
        try:
            import pty  # noqa: F401
        except ImportError:
            self.skipTest("no pty on this platform")
        t, _ = self.propose()
        for typed in ("\n", "9\n", "yes\n"):
            rc, out = self.with_terminal(typed, "approve", str(t["id"]))
            self.assertEqual(rc, 1, out)
            self.assertIn("not confirmed", out)
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "proposed")


class ListingTest(Base):
    def test_list_filters_by_status(self):
        a, _ = self.propose(target="a")
        self.propose(target="b")
        tickets.approve(self.data, a["id"], operator=tickets.OPERATOR_CONFIRMED)
        self.assertEqual([r["id"] for r in tickets.list_tickets(self.data, "approved")], [1])
        self.assertEqual([r["id"] for r in tickets.list_tickets(self.data, "proposed")], [2])


class ImportDisciplineTest(unittest.TestCase):
    def test_only_the_standard_library_and_the_core_module(self):
        tree = ast.parse((CODE / "tickets.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "contextlib", "evolution", "hashlib", "json", "os", "pathlib",
                                        "re", "secrets", "subprocess", "sys", "time", "typing"})
        self.assertNotIn("nas_mcp", (CODE / "tickets.py").read_text(encoding="utf-8"))


class ShipGateTest(Base):
    def claimed(self, **kw):
        t = self.approved(**kw)
        return t, tickets.claim(self.data, t["id"], now=T0)

    def git_init(self):
        subprocess.check_call(["git", "init", "-q"], cwd=str(self.data))
        subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=str(self.data))
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=str(self.data))
        (self.data / "host.py").write_text("ok\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "host.py"], cwd=str(self.data))
        subprocess.check_call(["git", "commit", "-qm", "init"], cwd=str(self.data))

    def test_done_without_git_still_closes_when_there_is_no_repo(self):
        t, c = self.claimed()
        r = tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        self.assertEqual(r["ticket"]["status"], "done")

    def test_done_is_refused_while_claimed_paths_are_dirty(self):
        self.git_init()
        t = self.approved()
        c = tickets.claim(self.data, t["id"], now=T0, paths=["host.py"])
        (self.data / "host.py").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        self.assertIn("uncommitted", str(cm.exception))
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "in_progress")
        subprocess.check_call(["git", "add", "host.py"], cwd=str(self.data))
        subprocess.check_call(["git", "commit", "-qm", "ship"], cwd=str(self.data))
        r = tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        self.assertEqual(r["ticket"]["status"], "done")

    def test_new_claim_is_refused_when_paths_already_have_leftover(self):
        self.git_init()
        (self.data / "host.py").write_text("leftover\n", encoding="utf-8")
        t = self.approved()
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.claim(self.data, t["id"], now=T0, paths=["host.py"])
        self.assertIn("leftover", str(cm.exception))
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "approved")


if __name__ == "__main__":
    unittest.main()
