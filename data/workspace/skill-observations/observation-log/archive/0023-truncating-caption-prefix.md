---
id: 23
title: Truncating chrome captions must not start with a static prefix
status: actioned
type: open-source
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace UI, no skill-families.md registry
area: static chat header — provider credit caption
date: 2026-09-18
session_context: After shipping a stacked Powered by [provider] caption, 실장님 reported mobile only shows Powered...
parked_until:
resolved: 2026-09-18
resolution: Dropped the Powered by prefix. Caption is the provider name only (agy/Claude/Grok/Codex/OmniRoute). app.js?v=43.
reference:
---

**Issue:** A nowrap ellipsis caption that started with `Powered by ` clipped to `Powered...` on a narrow mobile header. The variable payload (the provider name) sat at the end, so truncation hid the only useful word.

**Suggested improvement:** If a chrome caption is allowed to ellipsize, put the identifying token first — or drop the lead-in phrase entirely and show only that token.

**Principle:** Ellipsis eats the end of a nowrap string. A static prefix in a truncating label will survive while the variable it was meant to introduce disappears.
