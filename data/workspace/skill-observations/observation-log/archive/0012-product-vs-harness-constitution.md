---
id: 12
title: Product constitution baked agy identity and copied host law
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: "none — chatbot workspace constitution, not a shared skill-family rule"
area: data/workspace AGENTS.md PROJECT.md SELF-MODIFY.md
date: 2026-09-18
session_context: Host AGENTS.md compression; user asked to fix chatbot guidelines while operating the bot and building its own harness
parked_until:
resolved: 2026-09-18
resolution: Rewrote workspace AGENTS.md as product-only (pointer to ~/AGENTS.md), compressed PROJECT.md, made SELF-MODIFY provider-agnostic with docs/ as pointer, added harness-independence to PERSONA.md and chatbot-self-improve. Kept observation-log/ as this workspace SSOT.
reference:
---

**Issue:** Chatbot workspace rules restated the host constitution with `/var/services/homes/me` file:// links, treated `agy` stdin/`AgySession` as identity, and spent PROJECT.md on folded-repo archaeology. That fights the live Multi-Provider work (`AgentAdapter` already has agy/claude/grok) and inflates every session that auto-loads these files.

**Suggested improvement:** Split product law (persona, self-modify, pre-approval, session host) from harness contracts (adapter + ctl). Do not copy `~/AGENTS.md`. Keep the bot running on the default `agy` adapter while other adapters are built.

**Principle:** A product that is swapping its brain cannot put the current brain's process model in the constitution. The constitution names the surface that must stay up; adapters own CLI-specific contracts.
