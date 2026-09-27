# Self-Evolution Loop Review — 2026-09-22

- Status: assessment. Not a work order; nothing here is approved for
  implementation. Related: [audit-2026-09-22-work-orders.md](./audit-2026-09-22-work-orders.md),
  [direction-2026-09-22.md](./direction-2026-09-22.md).
- Subject: the observe → review → ticket → fix → ship loop designed in
  [recursive-self-evolution.md](./recursive-self-evolution.md) (plan v3,
  Phase 0 and Phase 1 marked complete 2026-09-20).
- Method: plan text compared against the code that implements it
  (evolution.py, observations.py, tickets.py, mcp_core.py,
  instructions.py, chatbot-ctl.sh) and against the data the loop produced
  (21 tickets, 41 observations, 209 DEVLOG blocks over 7 days). Every claim
  below cites a file, a line, or a count that was read, not inferred.

---

## Verdict

**The loop works as a safe bug-fixing loop. It does not yet work as a
self-evolution loop.** About half of its gates are enforced by code; the other
half rely on the agent's own report of having verified. One shipped ticket
already shows that report being wrong.

---

## What is enforced by code (works)

| Mechanism | Where | Evidence |
|---|---|---|
| Protected-path registry, data-driven, fail-closed | protected_paths.json, evolution.is_protected; callers mcp_server.py:425, server.py:889 | tests/test_core_standalone.py, tests/test_no_trace.py pass |
| Ticket protocol: evidence must exist (event:/candidate:), approval CLI-only, author lease, 3-attempt budget | tickets.py (verify_evidence, approve, claim, MAX_ATTEMPTS) | raises TicketError, not prose |
| done requires the ticket's paths to be clean in git | tickets.py:503 _ship_blockers | added by ticket 15 after observation 0039 |
| Observation input limited to user words + host outcome; tool/web output never used | evolution.turn_signals (:382) | plan §4.4 implemented; blocks prompt-injection persistence |
| The loop closed on its own protocol once | observation 0039 → ticket 15 → ship-gate in release | real self-correction of process, not only code |
| Throughput | 21 tickets done, 36/41 observations actioned in 7 days | the loop is actually used |

---

## What is not enforced (gaps, with evidence)

### G1. Verification is self-reported

release(done) checks git cleanliness only; it never runs a test. Ticket 15's
own done-note lists a subset ("test_tickets/mcp_core/bundle_budget pass")
chosen by the agent.

Consequence already observed: ticket 14 (/private, 2026-09-22) hardcoded
"실장님" at server.py:766 and :775. That breaks the project's own guard
tests/test_identity_wiring.py. The ticket was closed done and the change
was committed (ba13cc4). **The loop shipped a violation of its own rule and
recorded it as verified.**

### G2. The attempt budget has never been exercised

All 21 tickets: attempts=1. Zero gate_failed, failed, or abandoned
outcomes in any ticket note. A gate that is never run cannot fail; the 3-attempt
budget is a scale that has never weighed anything.

### G3. Post-hoc detection is noise

The only mitigation for H4 (CLI providers writing protected files natively) is
the warn-only hash manifest checked by doctor. Baseline is 2026-09-21 01:09
and was never refreshed; python3 evolution.py manifest-check now warns on
77 modified + 11 new files. An alarm that always rings is no alarm.

### G4. It repairs; it does not evolve

- Observations with proposes_skill filled: 0 / 41.
- Tickets with before/after metrics (required by plan §4.4): 3 / 21.
- Signals (observation_signals.json): 9 Korean correction regexes on the
  user's message + turn outcome kinds. No latency, token, failure-rate, or
  provider-error signal exists. The loop only receives what the operator says
  is broken.

### G5. The review edge depends on a human typing /review
Plan §8-4 chose manual review only. last-review-date.txt reads
2026-09-16; the DEVLOG's "first real /review on 2026-09-20" did not reach
mark_reviewed (or its write was lost). Candidates accumulate in
candidates.jsonl; the badge that reports them is, by charter, "not an
instruction". If nobody opens the review, observe → ticket is severed.

### G6. Three ledgers, no links

DEVLOG (prose, 209 blocks), tickets (21), observations (41).

- Tickets citing an observation id: 0 / 21.
- Observations with reference: filled: 1 / 41.

"Which observation became which ticket and improved which metric by how much"
cannot be answered by a machine.

### G7. Protection covers the least-used write path

The registry gates MCP write_file and PUT /api/rules. agy, grok, and codex
run with permission-skipping flags and native Write/Edit
(adapters.py:192, 971-972, 1239); claude has Bash/Write/Edit in
ALLOWED_TOOLS. The primary path by which the agent edits itself is
unguarded. The plan acknowledges this (§3 "한계"); G3 means the stated
mitigation is currently dead as well.

---

## Stage scorecard

| Stage | State | Basis |
|---|---|---|
| Observe | partial | automatic candidate collection; signals are correction phrases only |
| Review | weak | manual; last recorded review 2026-09-16 |
| Ticket / approval | strong | evidence check, CLI approval, lease, budget — all raise on violation |
| Fix | risky | edits the live tree; native CLI writes unguarded (G7) |
| Verify | absent | nothing checks that tests ran (G1, G2) |
| Ship | strong | git-clean gate on done |
| Measure | absent | before/after metrics in 3/21 tickets (G4) |

---

## Recommendations (by effect)

### R1. Put a test gate inside release(done)

- core_modules.json gains a tests_for list per module.
- release maps the ticket's paths to tests and runs
  python3 -m unittest <mapped> before flipping to done; on failure the
  outcome becomes gate_failed and attempts counts.
- Closes G1 and G2 in one change; the 3-attempt budget becomes meaningful for
  the first time.

### R2. Re-baseline the manifest at done

- Files changed under an approved ticket are legitimate; release(done) runs
  manifest-update restricted to the ticket's paths.
- After that, a doctor warning means exactly "a protected file changed
  without a ticket", which is the signal H4 needs. Closes G3.

### R3. Add host-measured signals to candidate collection

- From events.jsonl: turn latency p95, tokens per turn, auto_stop
  frequency, provider error rate. Threshold crossings become candidates with
  the numbers attached.
- Only then can propose require before/after metrics on improvement tickets
  (plan §4.4). Moves the loop from "repair" toward "evolve" (G4).

### R4. Link the ledgers

- propose accepts observation:<id> as an evidence type.
- resolve on an observation requires a ticket number when status is
  actioned.
- Smallest change that makes G6 answerable.

### R5. Conditional review prompt

- When unreviewed candidates exceed N or the last review is older than 7 days,
  the first turn of a session gets one line offering a review. Starting still
  requires the operator's yes, so plan §4.2 is not violated. Addresses G5
  without automating review itself.

### Not recommended now

- Opening Phase 2 (staging / isolation for core self-modification) before R1
  and R2. Decision 3 in the plan defers Phase 2; that remains correct. H4
  isolation belongs there, but a staging gate without a test gate would
  promote unverified code faster, not safer.

---

## Data appendix

`
tickets            : 21, all status=done except #2 declined; attempts=1 for all
ticket outcomes    : gate_failed=0 failed=0 abandoned=0
tickets → obs link : 0/21
observations       : 41 (36 actioned, 4 open, 1 superseded)
obs reference:     : 1/41 filled;  proposes_skill: 0/41
last-review-date   : 2026-09-16
manifest-check     : WARN modified=77 new=11 (baseline 2026-09-21 01:09)
identity guard     : FAIL server.py:766, :775 (introduced by ticket 14)
DEVLOG blocks      : 209 over 2026-09-16..22
signals            : 9 correction regexes + outcome kinds; no metrics
