---
id: 2
title: Real-time Progressive Activity Status Bar & Server Tool Event Sanitization
status: actioned
type: open-source
skill: [chatbot-self-improve]
proposes_skill: []
siblings_checked: none
area: UX & Streaming Activity Feedback
date: 2026-09-16
session_context: Chatbot UX enhancement during multi-step tool invocations (migrated from legacy log.md, Observation 2)
resolved: 2026-09-16
resolution: Added server-side tool payload sanitization (_tool_summary, dedup via _last_tool_sig) and a client-side ambient progress lane synced across full window + hub FAB.
reference:
---

**Issue:** During multi-step tool execution, the UI appeared frozen/silent until text generation began ("왜 대답이 없니"), and raw SSE tool events emitted repetitive noise like `tool: tool`.

**Suggested improvement:** Sanitize/dedupe raw tool-event payloads server-side before they reach the client, and surface an always-visible ambient progress indicator with state transitions (요청 보냄 → 작업 중 → 작성 중) rather than leaving the UI silent between turns.

**Principle:** Long-running agentic chat interfaces must stream real-time, sanitized tool execution summaries into an ambient progress lane so users always have continuous visual confirmation of background actions.
