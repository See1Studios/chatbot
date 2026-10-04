---
name: handoff-brief
description: Hand work to the director who owns it with a brief they can act on alone -- symptom, what is known, done-when -- instead of analysing it yourself.
---

# Handoff brief (lead, and any director)

## When to use
Work comes up that another role owns (`owns:` in its role pack): code, tests and fixes go to `dev`; plans and specs to
`plan`; outside facts to `scout`; images to `art`.

## The call
`dialog` `{"action": "handoff", "to": "<role>", "text": "<brief>", "done_when": "<check>"}` -- one piece of work per
handoff. The receiver starts at its own desk; the result comes back to you as a dm.

## The brief
- **Symptom or goal** in the user's terms: what they see or want, where, since when.
- **What is already known**: earlier handoff or ticket ids, results, what was ruled out -- so nothing is redone.
- **done_when**: a check the receiver can run or state ("test_x passes", "count reported", "plan ticket opened").
- Leave the how to the owner: no file guesses, no code analysis of your own.

## After
Tell the user in one line who has it (`#n`, role). When the result dm arrives, report with `progress-report`.
