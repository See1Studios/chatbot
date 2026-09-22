---
id: 14
title: Grok account usage lives on the TUI billing proxy, not grok usage CLI
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace adapter, no skill-families.md registry
area: AgentAdapter rate_limit_report / status-tab usage
date: 2026-09-18
session_context: 실장님 asked to show Grok usage in the chatbot status tab, after Claude /cost was already wired
parked_until:
resolved: 2026-09-18
resolution: GrokAdapter.rate_limit_report() now GETs GROK_CLI_CHAT_PROXY_BASE_URL/billing?format=credits with the grok login OIDC token and maps productUsage/creditUsagePercent into the existing remaining_pct rows. 401 retries once via grok models refresh.
reference:
---

**Issue:** `grok usage <session_id>` is a per-session cost dump. An earlier adapter comment treated "no session-less subcommand" as "this provider cannot show account usage," so the status tab returned 지원 안 함 even though the TUI `/usage` modal already shows weekly GrokBuild credit remaining.

**Suggested improvement:** When a CLI's usage slash command is TUI-only, inspect what HTTP the TUI actually calls (here `/v1/billing?format=credits`) and parse that into the host's existing row shape instead of returning None.

**Principle:** Absence of a one-shot CLI subcommand is not absence of a one-shot report. Look at the interactive surface's own fetch before declaring a provider unsupported.
