---
id: 3
title: Persona Avatar & Static Asset Path Resolution Across Ports (:3011 vs :80)
status: actioned
type: open-source
skill: [chatbot-self-improve]
proposes_skill: []
siblings_checked: none
area: Static Hosting & Asset Resolution
date: 2026-09-16
session_context: Full-window chatbot header avatar image repair (migrated from legacy log.md, Observation 3)
resolved: 2026-09-16
resolution: Symlinked shared persona asset dir into the :3011 static root, added a dedicated server-side persona route with correct MIME guessing, and an onerror fallback to the :80 nginx path.
reference:
---

**Issue:** The header avatar 404'd on `:3011` because the shared persona asset tree wasn't present in that port's document root, while `:80` (nginx) resolved it fine.

**Suggested improvement:** When a service is reachable on multiple ports/origins (dev port + reverse-proxied canonical port), symlink shared static asset trees into every origin's local static root, and add a port-agnostic `onerror` fallback to the canonical origin instead of assuming one document root.

**Principle:** Microservice web frontends on non-standard ports must symlink shared static asset trees into their local static roots and provide port-agnostic `onerror` fallbacks to canonical web endpoints.
