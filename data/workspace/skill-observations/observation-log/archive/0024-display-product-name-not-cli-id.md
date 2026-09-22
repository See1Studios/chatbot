---
id: 24
title: User-facing provider chrome should show product names, not CLI ids
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace UI, no skill-families.md registry
area: static chat header — provider credit caption
date: 2026-09-18
session_context: After dropping Powered by, 실장님 asked to replace the agy caption with the full product name Antigravity
parked_until:
resolved: 2026-09-18
resolution: PROVIDER_CREDIT.agy is Antigravity; HTML fallback and portrait-tray tooltips use the same map. Internal provider id stays agy. app.js?v=44.
reference:
---

**Issue:** The header caption used the CLI binary id `agy` as the user-visible provider name. After the prefix was removed, that id was the entire caption.

**Suggested improvement:** Keep `agy` as the adapter/session id. Map user-facing chrome (caption, tray tooltip, title) through a product-name table (`Antigravity` / `Claude` / `Grok` / `Codex` / `OmniRoute`).

**Principle:** Binary ids belong in APIs and process args. Chrome that a person reads should use the product name.
