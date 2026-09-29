"""tickets.py: evidence, merging, attempt budget, author leases per file, owners, operator-only decisions.
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
from tests._platform import dev_only_bash  # noqa: E402
from tests._platform import posix_only  # noqa: E402

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

    def test_host_log_references_are_accepted_only_when_logged(self):
        data = self.data / "inst" / "data"   # its own instance: logs/ sits next to data/
        logs = data.parent / "logs"
        logs.mkdir(parents=True)
        (logs / "events.jsonl").write_text(
            json.dumps({"evt": "http.error", "rid": "a1b2c3d4e5f6", "err": {"fp": "0123456789"}}, separators=(",", ":")) + "\n"
            + "not json\n", encoding="utf-8")
        (logs / "events.jsonl.1").write_text(
            json.dumps({"evt": "turn.end", "rid": "ffffffffffff"}, separators=(",", ":")) + "\n", encoding="utf-8")
        for ref in ("log:fp:0123456789", "log:rid:a1b2c3d4e5f6", "log:rid:ffffffffffff"):
            tickets.verify_evidence(data, ref)
        for ref in ("log:fp:9999999999", "log:rid:000000000000", "log:fp:0123", "log:fp:ZZZZZZZZZZ",
                    "log:msg:hello", "log:fp:", "log:rid:a1b2c3d4e5f6x"):
            with self.assertRaises(tickets.TicketError, msg=ref):
                tickets.verify_evidence(data, ref)

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
        self.assertIn("token_sha256", (tickets.tickets_dir(self.data) / "leases.json").read_text(encoding="utf-8"))
        self.assertNotIn(c["token"], json.dumps(tickets.get(self.data, t["id"])))


class LeaseScopeTest(Base):
    """One author per file, not one for the whole host (LEASE_SCOPE_v1)."""

    def test_tickets_on_different_files_run_side_by_side(self):
        a = self.approved(target="a")
        b = self.approved(target="b")
        tickets.claim(self.data, a["id"], paths=["services/chatbot/static/app.js"], now=T0)
        c = tickets.claim(self.data, b["id"], paths=["services/chatbot/docs/DEVLOG.md"], now=T0 + 1)
        self.assertTrue(c["new_attempt"])
        self.assertEqual(sorted(x["ticket"] for x in tickets.leases(self.data, now=T0 + 2)), [a["id"], b["id"]])

    def test_a_shared_file_or_folder_blocks_and_says_what_and_until_when(self):
        a = self.approved(target="a")
        b = self.approved(target="b")
        tickets.claim(self.data, a["id"], paths=["services/chatbot/static/app.js"], now=T0)
        for paths in (["services/chatbot/static/app.js"], ["services/chatbot/static"], ["services/chatbot/static/"]):
            with self.assertRaises(tickets.TicketError) as cm:
                tickets.claim(self.data, b["id"], paths=paths, now=T0 + 5)
            self.assertIn("ticket %d on services/chatbot/static/app.js until" % a["id"], str(cm.exception))
        blocked = tickets.get(self.data, b["id"])
        self.assertEqual(blocked["blocked_by"]["ticket"], a["id"])
        self.assertEqual(blocked["attempts"], 0)
        # a name that merely starts the same is another file
        tickets.claim(self.data, b["id"], paths=["services/chatbot/static/app.js.map"], now=T0 + 6)

    def test_the_blocked_mark_goes_once_the_ticket_is_claimed(self):
        a = self.approved(target="a")
        b = self.approved(target="b")
        ca = tickets.claim(self.data, a["id"], paths=["x/y.py"], now=T0)
        with self.assertRaises(tickets.TicketError):
            tickets.claim(self.data, b["id"], paths=["x/y.py"], now=T0 + 1)
        tickets.release(self.data, a["id"], ca["token"], "abandoned", now=T0 + 2)
        tickets.claim(self.data, b["id"], paths=["x/y.py"], now=T0 + 3)
        self.assertNotIn("blocked_by", tickets.get(self.data, b["id"]))

    def test_a_claim_without_files_takes_every_file_and_waits_for_any(self):
        a = self.approved(target="a")
        b = self.approved(target="b")
        ca = tickets.claim(self.data, a["id"], now=T0)
        with self.assertRaises(tickets.TicketError):
            tickets.claim(self.data, b["id"], paths=["any/file.py"], now=T0 + 1)
        tickets.release(self.data, a["id"], ca["token"], "abandoned", now=T0 + 2)
        tickets.claim(self.data, b["id"], paths=["any/file.py"], now=T0 + 3)
        with self.assertRaises(tickets.TicketError):
            tickets.claim(self.data, a["id"], now=T0 + 4)

    def test_the_holder_cannot_widen_onto_another_tickets_files(self):
        a = self.approved(target="a")
        b = self.approved(target="b")
        tickets.claim(self.data, a["id"], paths=["x/a.py"], now=T0)
        cb = tickets.claim(self.data, b["id"], paths=["x/b.py"], now=T0)
        with self.assertRaises(tickets.TicketError):
            tickets.claim(self.data, b["id"], token=cb["token"], paths=["x/a.py"], now=T0 + 1)
        self.assertEqual(tickets.get(self.data, b["id"])["paths"], ["x/b.py"])

    def test_the_old_single_lease_file_is_moved_in(self):
        a = self.approved(target="a")
        a_raw = self.raw(a["id"])
        a_raw.update(status="in_progress", attempts=1, paths=["x/a.py"])
        (tickets.tickets_dir(self.data) / ("%04d.json" % a["id"])).write_text(json.dumps(a_raw), encoding="utf-8")
        (tickets.tickets_dir(self.data) / "author.lease").write_text(json.dumps(
            {"ticket": a["id"], "token_sha256": tickets._hash("tok"), "taken": "", "expires": T0 + 100}), encoding="utf-8")
        b = self.approved(target="b")
        tickets.claim(self.data, b["id"], paths=["x/b.py"], now=T0)
        self.assertFalse((tickets.tickets_dir(self.data) / "author.lease").exists())
        self.assertTrue(tickets.holds(self.data, a["id"], "tok", now=T0))
        with self.assertRaises(tickets.TicketError):
            tickets.claim(self.data, self.approved(target="c")["id"], paths=["x/a.py"], now=T0)

    def test_a_merge_waits_only_for_its_own_files(self):
        a = self.approved(target="a")
        ca = tickets.claim(self.data, a["id"], paths=["x/a.py"], now=T0)
        tickets.await_merge(self.data, a["id"], ca["token"], now=T0)
        b = self.approved(target="b")
        cb = tickets.claim(self.data, b["id"], paths=["x/a.py"], now=T0 + 1)
        with self.assertRaises(tickets.TicketError):
            tickets.merge_go(self.data, a["id"], now=T0 + 2, operator=tickets.OPERATOR_CONFIRMED)
        self.assertEqual(tickets.get(self.data, a["id"])["status"], "awaiting_merge")
        tickets.release(self.data, b["id"], cb["token"], "abandoned", now=T0 + 3)
        tickets.claim(self.data, self.approved(target="c")["id"], paths=["y/c.py"], now=T0 + 3)
        m = tickets.merge_go(self.data, a["id"], now=T0 + 4, operator=tickets.OPERATOR_CONFIRMED)
        self.assertTrue(tickets.holds(self.data, a["id"], m["token"], now=T0 + 4))

    def test_leases_list_shows_no_token_hash(self):
        a = self.approved(target="a")
        tickets.claim(self.data, a["id"], paths=["x/a.py"], now=T0, actor="claude-code")
        [row] = tickets.leases(self.data, now=T0)
        self.assertEqual((row["ticket"], row["paths"], row["actor"]), (a["id"], ["x/a.py"], "claude-code"))
        self.assertNotIn("token_sha256", row)

    def test_paths_written_from_a_parent_folder_are_cut_to_the_repo(self):
        root = self.data / "repo"
        (root / ".git").mkdir(parents=True)
        (root / "chatbot").mkdir()                        # a real folder of that name stays as written
        data = root / "data"
        (data / "sessions" / "s1").mkdir(parents=True)
        tail = "/".join(root.parts[-2:])
        self.assertEqual(tickets._norm_paths([tail + "/static/app.js", "repo/x.py", "chatbot/y.py", "z.py"], data),
                         ["static/app.js", "x.py", "chatbot/y.py", "z.py"])


class ContentWorkTest(unittest.TestCase):
    """CONTENT_WORK_v1 (plan dlg/E, #392): user data is not code -- no guard run and no commit before done."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        subprocess.check_call(["git", "init", "-q"], cwd=str(self.root))
        self.data = self.root / "data"
        (self.data / "sessions" / "s1").mkdir(parents=True)          # the evidence a proposal needs
        (self.data / "sessions" / "s1" / "events.jsonl").write_text('{"event":"system"}\n{"event":"error"}\n',
                                                                    encoding="utf-8")

    def test_only_paths_under_the_data_folder_are_content(self):
        self.assertTrue(tickets.is_content(self.data, ["data/workspace/characters/c/gallery/p.png"]))
        self.assertFalse(tickets.is_content(self.data, ["data/workspace/x.md", "session.py"]))
        self.assertFalse(tickets.is_content(self.data, ["data/../session.py"]))
        self.assertFalse(tickets.is_content(self.data, []))
        self.assertFalse(tickets.is_content(self.root, ["x.md"]))        # the data folder is the repo: no line

    def test_content_closes_without_guards_or_a_commit(self):
        (self.data / "pic.png").write_text("new", encoding="utf-8")       # untracked: would block code work
        t, _ = tickets.propose(self.data, "a picture", "gallery", [EVENT], now=T0)
        tickets.approve(self.data, t["id"], now=T0, operator=tickets.OPERATOR_CONFIRMED)
        c = tickets.claim(self.data, t["id"], now=T0, paths=["data/pic.png"])
        with mock.patch.object(tickets, "_guard_failure", side_effect=AssertionError("no guards for content")):
            r = tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        self.assertEqual(r["ticket"]["status"], "done")


class WidenTest(Base):
    """TICKET_WIDEN_v1 (#385): the author adds files to its ticket instead of giving it up and opening another."""

    def test_the_author_adds_files_without_a_new_attempt(self):
        t = self.approved()
        c = tickets.claim(self.data, t["id"], paths=["a.py"], now=T0)
        r = tickets.widen(self.data, t["id"], c["token"], ["b.py", "a.py"], now=T0 + 5)
        self.assertEqual(r["added"], ["b.py"])
        got = tickets.get(self.data, t["id"])
        self.assertEqual((got["paths"], got["attempts"], got["status"]), (["a.py", "b.py"], 1, "in_progress"))
        self.assertIn("paths widened: + b.py", json.dumps(self.raw(t["id"]), ensure_ascii=False))
        self.assertEqual(tickets.leases(self.data, now=T0 + 6)[0]["paths"], ["a.py", "b.py"])

    def test_only_the_live_author_may_widen(self):
        t = self.approved()
        c = tickets.claim(self.data, t["id"], paths=["a.py"], now=T0)
        for token, now in (("wrong", T0 + 1), (c["token"], T0 + tickets.LEASE_TTL_SEC + 1)):
            with self.assertRaises(tickets.TicketError):
                tickets.widen(self.data, t["id"], token, ["b.py"], now=now)

    def test_a_file_another_ticket_holds_is_refused(self):
        a, b = self.approved(target="a"), self.approved(target="b")
        tickets.claim(self.data, a["id"], paths=["b.py"], now=T0)
        c = tickets.claim(self.data, b["id"], paths=["a.py"], now=T0 + 1)
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.widen(self.data, b["id"], c["token"], ["b.py"], now=T0 + 2)
        self.assertIn("author lock is held for ticket %d" % a["id"], str(cm.exception))
        self.assertEqual(tickets.get(self.data, b["id"])["paths"], ["a.py"])


class UnavailableTest(Base):
    """No brain answered (quota, limit, timeout): the attempt is given back, a few times (DELEGATION_HARDENING_v1)."""

    def test_paused_gives_the_attempt_back(self):
        t = self.approved()
        for _ in range(5):                                                   # only the operator resumes it: no cap
            c = tickets.claim(self.data, t["id"], now=T0)
            r = tickets.release(self.data, t["id"], c["token"], "paused", now=T0)
        self.assertEqual((r["ticket"]["attempts"], r["ticket"]["status"]), (0, "approved"))

    def test_unavailable_gives_the_attempt_back_up_to_the_cap(self):
        t = self.approved()
        for n in range(tickets.UNAVAILABLE_REFUNDS):
            c = tickets.claim(self.data, t["id"], now=T0)
            r = tickets.release(self.data, t["id"], c["token"], "unavailable", now=T0)
            self.assertEqual((r["ticket"]["attempts"], r["ticket"]["unavailable"]), (0, n + 1))
        c = tickets.claim(self.data, t["id"], now=T0)
        r = tickets.release(self.data, t["id"], c["token"], "unavailable", now=T0)
        self.assertEqual(r["ticket"]["attempts"], 1)                     # past the cap it counts
        self.assertEqual(r["ticket"]["status"], "approved")


class OwnerTest(Base):
    """A ticket an agent opened to do itself is that agent's until the operator hands it over."""

    def test_only_the_owner_may_claim(self):
        t, _ = tickets.propose(self.data, "Docs", "docs", [EVENT], now=T0, actor="claude-code")
        tickets.set_owner(self.data, t["id"], "claude-code", now=T0)
        tickets.approve(self.data, t["id"], now=T0, operator=tickets.OPERATOR_CONFIRMED)
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.claim(self.data, t["id"], paths=["docs/a.md"], now=T0, actor="chat-agent:agy")
        self.assertIn("claude-code's", str(cm.exception))
        with self.assertRaises(tickets.TicketError):
            tickets.claim(self.data, t["id"], now=T0)       # nobody named: not the owner either
        self.assertEqual(tickets.get(self.data, t["id"])["attempts"], 0)
        tickets.claim(self.data, t["id"], paths=["docs/a.md"], now=T0, actor="claude-code")

    def test_the_operator_hands_it_over(self):
        t, _ = tickets.propose(self.data, "Docs", "docs", [EVENT], now=T0, actor="claude-code")
        tickets.set_owner(self.data, t["id"], "claude-code", now=T0)
        tickets.approve(self.data, t["id"], now=T0, operator=tickets.OPERATOR_CONFIRMED)
        with self.assertRaises(tickets.TicketError):
            tickets.disown(self.data, t["id"], now=T0)       # an agent cannot
        tickets.disown(self.data, t["id"], now=T0, operator=tickets.OPERATOR_UI)
        self.assertNotIn("owner", tickets.get(self.data, t["id"]))
        tickets.claim(self.data, t["id"], now=T0, actor="chat-agent:agy")

    def test_only_the_proposer_can_own_and_nobody_can_take_it(self):
        t, _ = tickets.propose(self.data, "Docs", "docs", [EVENT], now=T0, actor="chat-agent:agy")
        with self.assertRaises(tickets.TicketError):
            tickets.set_owner(self.data, t["id"], "claude-code", now=T0)
        tickets.set_owner(self.data, t["id"], "chat-agent:agy", now=T0)
        with self.assertRaises(tickets.TicketError):
            tickets.set_owner(self.data, t["id"], "grok", now=T0)


class ReleaseTest(Base):
    def claimed(self, **kw):
        t = self.approved(**kw)
        return t, tickets.claim(self.data, t["id"], now=T0)

    def test_done_closes_the_ticket_and_frees_the_lock(self):
        t, c = self.claimed()
        r = tickets.release(self.data, t["id"], c["token"], "done", "tests pass", now=T0)
        self.assertEqual((r["ticket"]["status"], r["ticket"]["closed_reason"]), ("done", "done"))
        self.assertEqual(tickets.leases(self.data, now=T0), [])
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

    @posix_only   # the operator's terminal is found through /dev/tty (the dev tickets CLI, #411)
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
                                        "re", "secrets", "shutil", "subprocess", "sys", "tempfile", "time", "typing",
                                        "platform_compat"})   # a core module (PP5)
        # shutil/tempfile: the release gate judges a throwaway worktree at HEAD (pew/Q)
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

    @dev_only_bash
    def test_the_guard_run_does_not_inherit_the_live_install_settings(self):
        # #371/#387: the server's CHATBOT_DATA / CHATBOT_ROOT reached the guard tests, which then failed on the copy
        self.git_init()
        runner = self.data / "run-tests.sh"
        runner.write_text('env | grep -q "^CHATBOT_\\|^PE_HOME=" && { echo "failed: leaked"; exit 1; }; exit 0\n',
                          encoding="utf-8")
        subprocess.check_call(["git", "add", "run-tests.sh"], cwd=str(self.data))
        subprocess.check_call(["git", "commit", "-qm", "runner"], cwd=str(self.data))
        with mock.patch.dict(os.environ, {"CHATBOT_DATA": "/live/data", "CHATBOT_ROOT": "/live", "PE_HOME": "/x"}):
            self.assertEqual(tickets._guard_failure(self.data), "")

    @dev_only_bash
    def test_done_is_refused_while_the_guard_tests_fail(self):
        # pew/O: the repo's run-tests.sh --fast is the backstop for a commit that skipped its hooks
        self.git_init()
        runner = self.data / "run-tests.sh"
        runner.write_text('echo "failed: test_x"; exit 1\n', encoding="utf-8")
        subprocess.check_call(["git", "add", "run-tests.sh"], cwd=str(self.data))   # the gate judges HEAD (pew/Q)
        subprocess.check_call(["git", "commit", "-qm", "runner"], cwd=str(self.data))
        t, c = self.claimed()
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        self.assertIn("guard tests fail (failed: test_x)", str(cm.exception))
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "in_progress")   # lease kept
        r = tickets.release(self.data, t["id"], c["token"], "gate_failed", now=T0)    # other outcomes still work
        self.assertEqual(r["ticket"]["status"], "approved")
        c = tickets.claim(self.data, t["id"], now=T0)
        runner.write_text("exit 0\n", encoding="utf-8")
        with self.assertRaises(tickets.TicketError):
            tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        subprocess.check_call(["git", "commit", "-qam", "fix runner"], cwd=str(self.data))
        r = tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        self.assertEqual(r["ticket"]["status"], "done")

    def test_a_repo_without_the_runner_is_not_copied(self):
        # a data folder inside another git repo (a home dir that is a repo) must not get a worktree of that repo
        self.git_init()
        t, c = self.claimed()
        real = subprocess.run
        seen = []

        def spy(cmd, *a, **kw):
            seen.append(cmd)
            return real(cmd, *a, **kw)
        with mock.patch.object(tickets.subprocess, "run", side_effect=spy):
            r = tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        self.assertEqual(r["ticket"]["status"], "done")
        self.assertFalse([cmd for cmd in seen if "worktree" in cmd], seen)

    def test_new_claim_is_refused_when_paths_already_have_leftover(self):
        self.git_init()
        (self.data / "host.py").write_text("leftover\n", encoding="utf-8")
        t = self.approved()
        with self.assertRaises(tickets.TicketError) as cm:
            tickets.claim(self.data, t["id"], now=T0, paths=["host.py"])
        self.assertIn("leftover", str(cm.exception))
        self.assertEqual(tickets.get(self.data, t["id"])["status"], "approved")


class AwaitingMergeTest(Base):
    """AWAITING_MERGE_v1: reviewed work waits for the operator without holding the lease or the budget."""

    def waiting(self):
        t = self.approved()
        c = tickets.claim(self.data, t["id"], now=T0)
        tickets.await_merge(self.data, t["id"], c["token"], "branch worktree/ticket-1", now=T0 + 10, actor="claude-code")
        return t["id"]

    def test_waiting_frees_the_lease_and_spends_nothing(self):
        tid = self.waiting()
        t = self.raw(tid)
        self.assertEqual((t["status"], t["attempts"], t["merge_pending"]), ("awaiting_merge", 1, True))
        self.assertIn("awaiting merge: branch worktree/ticket-1", t["notes"][-1]["text"])
        self.assertEqual(t["notes"][-1]["by"], "agent:claude-code")
        other = self.approved(target="server.py: other")
        tickets.claim(self.data, other["id"], now=T0 + 20)   # the lease is free for other work

    def test_only_the_lease_holder_can_hand_in_for_merge(self):
        t = self.approved()
        tickets.claim(self.data, t["id"], now=T0)
        with self.assertRaises(tickets.TicketError):
            tickets.await_merge(self.data, t["id"], "wrong", now=T0)

    def test_an_agent_cannot_reclaim_or_let_it_land_itself(self):
        tid = self.waiting()
        with self.assertRaises(tickets.TicketError):
            tickets.claim(self.data, tid, now=T0 + 20)
        with self.assertRaises(tickets.TicketError):
            tickets.merge_go(self.data, tid, now=T0 + 20)

    def test_merge_go_hands_a_lease_back_without_an_attempt_then_done(self):
        tid = self.waiting()
        m = tickets.merge_go(self.data, tid, now=T0 + 20, operator=tickets.OPERATOR_UI)
        t = self.raw(tid)
        self.assertEqual((t["status"], t["attempts"], t["merge_approved_by"]), ("in_progress", 1, "operator (ui)"))
        tickets.release(self.data, tid, m["token"], "done", now=T0 + 30)
        t = self.raw(tid)
        self.assertEqual(t["status"], "done")
        self.assertNotIn("merge_pending", t)

    def test_merge_go_does_not_wait_for_a_busy_lease(self):
        tid = self.waiting()
        other = self.approved(target="server.py: other")
        tickets.claim(self.data, other["id"], now=T0 + 20)
        with self.assertRaises(tickets.TicketError):
            tickets.merge_go(self.data, tid, now=T0 + 30, operator=tickets.OPERATOR_CONFIRMED)
        self.assertEqual(self.raw(tid)["status"], "awaiting_merge")

    def test_a_lapsed_merge_lease_goes_back_to_waiting(self):
        tid = self.waiting()
        tickets.merge_go(self.data, tid, now=T0 + 20, operator=tickets.OPERATOR_UI)
        later = self.approved(target="server.py: other")
        tickets.claim(self.data, later["id"], now=T0 + 20 + tickets.LEASE_TTL_SEC + 1)
        self.assertEqual(self.raw(tid)["status"], "awaiting_merge")
        tickets.drop_lease(self.data, operator=tickets.OPERATOR_TTY)
        m = tickets.merge_go(self.data, tid, now=T0 + 5000, operator=tickets.OPERATOR_UI)
        tickets.drop_lease(self.data, operator=tickets.OPERATOR_TTY)
        self.assertEqual(self.raw(tid)["status"], "awaiting_merge")
        self.assertTrue(m["token"])

    def test_a_failed_merge_makes_it_an_ordinary_approved_ticket(self):
        tid = self.waiting()
        m = tickets.merge_go(self.data, tid, now=T0 + 20, operator=tickets.OPERATOR_UI)
        tickets.release(self.data, tid, m["token"], "failed", "main moved", now=T0 + 30)
        t = self.raw(tid)
        self.assertEqual((t["status"], t["attempts"]), ("approved", 1))
        self.assertNotIn("merge_pending", t)

    def test_decline_drops_a_waiting_change(self):
        tid = self.waiting()
        tickets.decline(self.data, tid, operator=tickets.OPERATOR_UI)
        t = self.raw(tid)
        self.assertEqual(t["status"], "declined")
        self.assertNotIn("merge_pending", t)

    def test_rework_sends_it_back_as_a_new_attempt_for_the_operator_only(self):
        tid = self.waiting()
        with self.assertRaises(tickets.TicketError):
            tickets.rework(self.data, tid, "shorter", now=T0 + 20)                 # an agent cannot
        with self.assertRaises(tickets.TicketError):
            tickets.rework(self.data, tid, " ", now=T0 + 20, operator=tickets.OPERATOR_UI)
        r = tickets.rework(self.data, tid, "shorter", now=T0 + 20, operator=tickets.OPERATOR_UI)
        t = self.raw(tid)
        self.assertEqual((t["status"], t["attempts"]), ("in_progress", 2))
        self.assertNotIn("merge_pending", t)
        self.assertIn("sent back (attempt 2/3): shorter", t["notes"][-1]["text"])
        tickets.await_merge(self.data, tid, r["token"], now=T0 + 30)
        self.assertEqual(self.raw(tid)["status"], "awaiting_merge")

    def test_rework_respects_the_budget(self):
        tid = self.waiting()
        for i in range(2):
            r = tickets.rework(self.data, tid, "again", now=T0 + 20 + i, operator=tickets.OPERATOR_UI)
            tickets.await_merge(self.data, tid, r["token"], now=T0 + 20 + i)
        with self.assertRaises(tickets.TicketError):
            tickets.rework(self.data, tid, "again", now=T0 + 40, operator=tickets.OPERATOR_UI)

    def test_a_proposal_for_the_same_target_joins_the_waiting_ticket(self):
        tid = self.waiting()
        t, merged = self.propose(evidence=[CAND], now=T0 + 40)
        self.assertEqual((t["id"], merged), (tid, True))


if __name__ == "__main__":
    unittest.main()


class ActorTest(Base):
    """ACTOR_ATTRIBUTION_v1: who proposed, approved (and through what), worked on and closed a ticket."""

    def test_the_record_names_each_hand(self):
        t, _ = tickets.propose(self.data, "Swap blocks", "session.py: swap", [EVENT], now=T0, actor="claude-code")
        self.assertEqual(t["actor"], "claude-code")
        t = tickets.approve(self.data, t["id"], now=T0, operator=tickets.OPERATOR_CONFIRMED,
                            on_behalf="claude-code ticket-quick (operator's instruction)")
        self.assertEqual(t["approved_by"], "operator (api) via claude-code ticket-quick (operator's instruction)")
        c = tickets.claim(self.data, t["id"], now=T0, actor="claude-code")
        self.assertEqual(c["ticket"]["worked_by"], "claude-code")
        tickets.add_note(self.data, t["id"], "halfway", c["token"], now=T0)       # the holder, unnamed: still attributed
        r = tickets.release(self.data, t["id"], c["token"], "done", now=T0)
        done = tickets.get(self.data, t["id"])
        self.assertEqual(done["closed_by"], "claude-code")
        bys = {n["by"] for n in done["notes"]}
        self.assertIn("agent:claude-code", bys)
        self.assertNotIn("agent", bys)

    def test_without_an_actor_the_record_is_as_before(self):
        t = self.approved()
        c = tickets.claim(self.data, t["id"], now=T0)
        self.assertNotIn("worked_by", c["ticket"])
        self.assertIn("agent", {n["by"] for n in c["ticket"]["notes"]})
        self.assertEqual(t["approved_by"], "operator (api)")

    def test_a_note_from_someone_else_is_theirs(self):
        t = self.approved()
        c = tickets.claim(self.data, t["id"], now=T0, actor="grok")
        n = tickets.add_note(self.data, t["id"], "looked at it", None, now=T0, actor="chat-agent:agy")
        self.assertEqual(n["notes"][-1]["by"], "agent:chat-agent:agy")


class RoleIdTest(Base):
    """NAME_NEUTRAL_v1: who-fields take role ids only -- a persona name or title cannot get in."""

    def test_names_and_titles_are_refused(self):
        for bad in ("냥피디", "실장님", "Claude Code", "grok!", "a b"):
            with self.assertRaises(tickets.TicketError, msg=bad):
                tickets.propose(self.data, "t", "x-%s" % len(bad), [EVENT], now=T0, actor=bad)
        with self.assertRaises(tickets.TicketError):
            tickets.approve(self.data, self.propose()[0]["id"], now=T0, operator=tickets.OPERATOR_CONFIRMED,
                            on_behalf="실장님 지시")

    def test_role_ids_are_taken(self):
        for good in ("claude-code", "grok", "operator", "chat-agent:agy", "chat-agent"):
            t, _ = tickets.propose(self.data, "t " + good, "y-" + good, [EVENT], now=T0, actor=good)
            self.assertEqual(t["actor"], good)
