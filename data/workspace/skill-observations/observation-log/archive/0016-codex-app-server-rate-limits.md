---
id: 16
title: Codex account quota is available through its local app-server protocol
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace adapter, no skill-families.md registry
area: AgentAdapter rate_limit_report / status-tab usage
date: 2026-09-18
session_context: 실장님 asked whether Codex usage could be added to the chatbot status tab
parked_until:
resolved: 2026-09-18
resolution: Codex CLI 0.154.0 app-server `account/rateLimits/read` returned a live authenticated quota bucket. CodexAdapter now launches that read-only child for the cached status check, terminates it, and maps usedPercent/windows/resetsAt to the shared remaining_pct rows without reading auth credentials.
reference:
---

**Issue:** The adapter only checked `codex --help`, found no one-shot usage
subcommand, and labelled account usage unsupported.

**Principle:** A provider's local app-server protocol can expose account
capabilities absent from its top-level CLI; inspect that supported protocol
before declaring a status surface unavailable.
