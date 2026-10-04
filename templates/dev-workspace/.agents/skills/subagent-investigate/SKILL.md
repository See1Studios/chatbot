---
name: subagent-investigate
description: Direct an investigation -- subagents read and check, targeted tests confirm, you decide and report -- so your own context stays small and the turn ends on time.
---

# Investigate with subagents (dev)

## When to use
A handoff or request needs the code read, a cause found, or a behaviour checked.

## Steps
1. Write one precise question per subagent (file area, what to find, what to return in a few lines). Use your
   provider's subagent tool with a fast model; subagents read, search and run named tests -- they never edit files.
2. Confirm with targeted tests only: `./run-tests.sh test_x test_y`. Never the whole suite, never `python3 -m unittest`
   or pytest directly (refused for chat agents; the whole suite runs in the delegate gates).
3. Do not start or wait on long background commands; a turn ends at 8 minutes whatever is still running.
4. Decide: nothing to change (say why, with the evidence), or a change -> a `delegate` plan (see
   `roles/dev/PROCEDURE.md`: paths, reads, tests paired), which waits for the operator's go.

## Report (to the one who asked)
- What was checked (files, tests by name) and the finding, in 2–4 lines.
- The decision and, for a change, the plan ticket id.
