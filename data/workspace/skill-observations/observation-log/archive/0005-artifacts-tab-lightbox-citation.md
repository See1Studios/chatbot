---
id: 5
title: Dedicated Artifacts Tab, Multi-Format Modal Lightbox & Live In-Chat Citation
status: actioned
type: open-source
skill: [chatbot-self-improve]
proposes_skill: []
siblings_checked: none
area: Web UI & Artifact Asset Management
date: 2026-09-16
session_context: Chatbot generated media/file gallery & artifact management (migrated from legacy log.md, Observation 5)
resolved: 2026-09-16
resolution: Added server-side unified artifact discovery + GET /api/sessions/:id/artifacts, a three-tab segmented UI (대화/아티팩트/로그) with filters, a modal lightbox/file viewer, one-click in-chat citation, and SSE-driven badge sync.
reference:
---

**Issue:** Chat sessions generate images/code/docs but users had no central place to inspect, download, or cite them back into the conversation; duplicate streaming events also caused image clutter.

**Suggested improvement:** Any conversational agent that produces file-like deliverables should index them as first-class artifacts in a dedicated, filterable tab (not just inline chat bubbles), with a lightbox/viewer and a one-click "cite this back into the composer" action, kept in sync via the existing SSE stream rather than polling.

**Principle:** Deliverables produced by conversational agents must be indexed as first-class artifacts in a dedicated workspace tab, featuring instantaneous preview, one-click chat citation, and non-blocking background synchronization.
