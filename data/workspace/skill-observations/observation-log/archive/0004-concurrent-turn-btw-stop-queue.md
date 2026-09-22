---
id: 4
title: Concurrent Turn Inquiries (/btw), Auto-Detection, Message Queueing & Explicit Stop
status: actioned
type: open-source
skill: [chatbot-self-improve]
proposes_skill: []
siblings_checked: none
area: Chat Host Process Architecture & UX Flow
date: 2026-09-16
session_context: Sphere Chatbot active-turn message handling & side-query mechanism (migrated from legacy log.md, Observation 4)
resolved: 2026-09-16
resolution: Added side-channel ephemeral /btw execution, auto-inquiry detection, a dual-mode send button, an explicit stop endpoint, and sequential FIFO message queueing; hardened chatbot-ctl.sh kill_orphan_agy to PPID=1 only.
reference:
---

**Issue:** In `stream-json` interactive CLI mode, typing while a turn is `busy` dropped/corrupted input because stdin cannot accept concurrent prompts mid-turn. Users needed a hard stop, a lightweight side-query channel, and automatic routing of natural questions without manual `/btw` syntax.

**Suggested improvement:** For any single-stdin long-running agent process wrapped by a web UI, decouple three concerns explicitly: (1) an interrupt/stop path that kills the subprocess, (2) an ephemeral out-of-band query path that spawns a separate lightweight call instead of touching the busy stdin, (3) a FIFO queue for legitimate follow-up instructions. Auto-detect which bucket a mid-turn message belongs to (question vs. instruction) so the user doesn't need special syntax.

**Principle:** Long-running conversational agents must decouple task orchestration into distinct channels: explicit interruption for aborts, ephemeral out-of-band queries for mid-turn status/inquiries, and FIFO queues for follow-up commands.
