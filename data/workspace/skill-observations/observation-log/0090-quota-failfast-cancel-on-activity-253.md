---
id: 90
title: "QUOTA_FAILFAST cancels on turn activity (#253)"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "session"
date: 2026-09-27
parked_until:
resolved: 2026-09-27
resolution: "Ticket #253 done (4f34e29). Front matter added later (pew/N3): the file was written by hand without it."
reference:
actor: "antigravity"
resolved_by: "antigravity"
---

# Observation 0090 — QUOTA_FAILFAST cancel on activity (#253)

- Date: 2026-09-27
- Ticket: #253
- Context: agy backend retry emitted step_type error_message -> chatbot armed 8s failfast timer, but agy recovered and streamed answer; chatbot cut off answer at 8s mark.
- Fix: _touch_turn_activity calls _cancel_error_message_failfast() on delta/tool, re-arms silent hang; _arm_error_message_failfast skips if current_text exists; _error_message_failfast returns if text or recent activity exists.
- Verify: unittest test_conversation_sync 25 OK, smoke.py 7 OK, guard OK.
- Deploy: python module -> ⚡소생
