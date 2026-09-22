---
id: 21
title: Other device drew the answer above the question
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot session host + compact UI, no skill-families.md registry
area: server.py _send_direct emit order + static/app.js placeMsgByTs/repairMsgOrder
date: 2026-09-18
session_context: After the multi-device poll patch, 실장님 sent from the phone; the tablet rendered the assistant bubble above the user question
parked_until:
resolved: 2026-09-18
resolution: Emit user_ack before starting the HTTP/one-shot worker. Client treats untagged assistant bubbles as in-flight, repositions a late user bubble before them, and repairMsgOrder swaps inverted pairs. app.js?v=41. Server emit order needs ⚡소생; client repair is Ctrl+Shift+R.
reference:
---

**Issue:** HTTP `_run_http_turn` started before `user_ack`, so a watching tablet received deltas first and appended the question later. Catch-up stamped ts on the misplaced user bubble without moving it.

**Suggested improvement:** Broadcast the question first; on the client, never append a user bubble after an in-flight assistant, and repair inverted pairs after every sync.

**Principle:** Fan-out event order is part of the UI contract — a replica that sees the reply before the prompt will draw it that way, and a watermark resync that only appends cannot fix inverted DOM.
