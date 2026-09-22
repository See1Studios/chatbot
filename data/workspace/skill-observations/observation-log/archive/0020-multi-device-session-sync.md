---
id: 20
title: Multi-device session view drifted — SSE-only live path, inverted catch-up
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot session host + compact UI, no skill-families.md registry
area: server.py SSE/_emit/to_public + static/app.js resync
date: 2026-09-18
session_context: 실장님 had tablet+phone on the same session; tablet streamed the turn, phone stayed frozen, tablet then said connection lost, phone refresh showed the finished reply, and the non-typing device sometimes rendered the answer above the question
parked_until:
resolved: 2026-09-18
resolution: SSE no longer expires mid-turn; stuck subscriber queues are dropped; GET session now includes current_text/last_progress; client polls every 2.5s and on visibility, keys bubbles by role+ts, inserts missed items in timestamp order before the live draft. Needs ⚡소생 + Ctrl+Shift+R on every device.
reference:
---

**Issue:** Live progress existed only on the EventSource that happened to stay open. A backgrounded phone did not resync until refresh. Catch-up appended missed history after a live-rendered assistant bubble, so the original question appeared under the answer. The 900s SSE cutoff also killed the typing tablet mid-job.

**Suggested improvement:** Treat GET /api/sessions/:id as the source of truth for other devices (history + in-flight draft + last tool line), poll it while visible, and insert by timestamp instead of appending. Keep SSE as the fast path, not the only path.

**Principle:** A multi-viewer session cannot use a single push socket as the only replica; late or backgrounded clients must be able to catch up from durable+live snapshot state without scrambling message order.
