---
name: progress-report
description: Report where the team's work stands from records, not memory -- handoffs, dms, tickets -- in a few Korean lines with ids and numbers.
---

# Progress report (lead)

## When to use
The user asks how things stand, or a handoff/delegation result comes back and the user should hear it.

## Sources, in this order -- the records win over what you remember from earlier in the conversation
1. `dialog` `{"action": "handoffs"}`: every handoff you sent or received with its state now (sent, running, done,
   failed, cancelled). Report a handoff by this state, never by an earlier report.
   Then `read` the dms with the directors involved for the detail of a result (`#n …`).
2. `ticket` `list` with `"status": "open"` for the cards not closed (proposed / approved / in progress / awaiting
   merge) and what each waits for.
3. Your own memory only for what the records do not hold -- and say so.

## Rules
- Every claim names its source id: handoff `#n`, ticket `#n`, a test name, a count. No "all green" without the list.
- Before you put anything under "코치님 결정", check it is still open -- the dms and your memory may be older than
  what happened since (live 2026-10-05: a report asked to approve deleting a file deleted an hour before):
  - a file: `git status --short <path>` and `ls <path>` -- gone means it is done, not a decision;
  - a ticket: `ticket` `get` -- closed, merged or declined means done;
  - a handoff: the latest `#n` result in the dm -- a later result replaces an earlier one.
  Drop what is no longer open, or move it to 끝난 것.
- Unknown is a valid answer: "확인 못 함: …" beats a guess.
- Do not open code to verify a result; if a result looks wrong, hand a check to the owning director (`handoff-brief`).

## Output (Korean, 2–4 lines)
- **끝난 것:** `#n` 결과 한 줄씩 (숫자·이름 포함)
- **진행 중 / 막힌 것:** 누가, 무엇을 기다리는지
- **코치님 결정:** 아직 열려 있는 것만, 선택지와 함께
