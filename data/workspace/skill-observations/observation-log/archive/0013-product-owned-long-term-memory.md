---
id: 13
title: Chatbot had transcript search only, no durable facts
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: "none — chatbot product memory, not a shared skill family"
area: data/workspace/memory MEMORY.md tools/memory.py
date: 2026-09-18
session_context: User asked to attach memory to the chatbot while operating it and building its harness
parked_until:
resolved: 2026-09-18
resolution: Added product-owned memory/MEMORY.md plus tools/memory.py (show/add/search/forget). AGENTS.md §2 splits long-term facts from session-archive recall. Did not import ~/.grok/memory or Hermes USER.md. No server.py change, no live restart.
reference:
---

**Issue:** `recall_memory.py` only greps past `sessions/*/meta.json`. New sessions did not load standing facts about 실장님 or ops decisions, so the bot re-asked or forgot across rotates.

**Suggested improvement:** A small curated markdown file in the chatbot workspace, read at session start, written only on explicit "기억해", capped, isolated from other agents' memory stores.

**Principle:** Always-on product memory belongs in the product data tree and must work for every session backend. Transcript search is not memory.
