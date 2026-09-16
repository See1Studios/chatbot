---
id: 7
title: "Multiple SSE subscribers cannibalize single queue causing alternating missing text chunks"
status: applied
type: open-source
skill: [chatbot-self-improve]
proposes_skill: []
siblings_checked: none
area: Chat Host Transport — SSE multi-client streaming reliability
date: 2026-09-16
session_context: 실장님 reported heavily garbled/broken text in chatbot response during normal conversation
resolved: 2026-09-16
resolution: Introduced per-subscriber Queue and broadcast in _emit with finally cleanup in _sse
reference:
---

**Issue:** When a user opens multiple tabs, or has both the Hub FAB popup and full-page chat (:3011) open, or when an SSE connection reconnects before the previous socket is fully closed, streamed responses appear heavily broken with whole words and chunks dropped (e.g. `Google Imagen 3` -> `**Goo ... ge`)**`, `나노바나나` -> `''`). Inspection of dropped vs received text revealed an exact alternating 50/50 token partition. Root cause: `AgySession.events` was implemented as a single shared `queue.Queue[dict]`, and `_sse` called `sess.events.get()`. When two HTTP GET requests for `/api/sessions/:id/events` are active concurrently, the two consumer threads alternate popping events off the shared queue. Furthermore, terminal events like `result` were only delivered to one subscriber, leaving the other stranded with partial text.

**Suggested improvement:** Implement a pub/sub fan-out pattern for session events. Each `/api/sessions/:id/events` HTTP connection must register its own dedicated `queue.Queue(maxsize=1000)` into `session.subscribers`. In `_emit`, iterate through `subscribers` under the session lock and enqueue to all. In `_sse`, always deregister the subscriber queue in a `finally:` block.

**Principle:** Server-Sent Events (SSE) endpoints representing live room or assistant state must never consume from a single point-to-point work queue; each HTTP subscriber connection requires its own dedicated egress queue or ring buffer with broadcast dispatch to prevent multi-tab and reconnect race conditions from shredding stream deltas.
