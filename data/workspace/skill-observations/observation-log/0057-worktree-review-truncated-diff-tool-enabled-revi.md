---
id: 57
title: "Worktree review: truncated diff + tool-enabled reviewer + timeout not handed to next brain"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "protocol"
date: 2026-09-24
parked_until:
resolved: 2026-09-24
resolution: "Ticket #141 done (da9db6d). agy stays tools-on; the prompt rule is its only guard."
reference:
actor: "chat-agent:claude"
resolved_by: "chat-agent:claude"
---

Ticket #140 attempt 1 failed at 2026-09-24 17:27:44 with 'reviewer agy exited with -1'. Measured: review prompt 19548 bytes, diff cut at DIFF_LIMIT=15000 ('... (diff truncated)'), only 5 'diff --git' blocks of the task's files visible. Reviewer agy gemini-3.8-flash-low was not tools-off: from the empty review-room it spawned `find / -name host_config.py` (3m30s) and `python3 -m unittest discover` inside ~/.worktrees/chatbot/ticket-140, then hit REVIEW_TIMEOUT=300. Exit -1 did not match UNAVAILABLE_RE, so no fallback to the next brain; the whole run failed and worktree + branch worktree/ticket-140 were removed, discarding 루루's finished task 1/3. Operator (실장님): '제미나이가 코드를 또 못읽는걸까' — 'again', recurring.
