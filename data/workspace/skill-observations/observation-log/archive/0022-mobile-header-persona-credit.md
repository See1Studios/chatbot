---
id: 22
title: Mobile header title bound to provider name starved right-side chrome
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace UI, no skill-families.md registry
area: static chat header — brand title vs provider credit
date: 2026-09-18
session_context: 실장님 asked to tidy the mobile portrait/name so long provider titles stop hiding the right-side widgets, and to keep the name as 냥피디 with a small Powered by [provider] caption
parked_until:
resolved: 2026-09-18
resolution: Header h1 is always 냥피디. Provider is a stacked Powered by caption. Mobile brand shrinks, bar is flex 0 0 auto, caption ellipsizes first.
reference:
---

**Issue:** `updateBrandAvatar()` wrote the provider display name (`냥피디 (agy)`, `OmniRoute`, …) into the header `h1`. On a nowrap mobile header both `.brand` and `.bar` were `flex-shrink: 0`, so a long title overflowed and clipped the tab/⋯/new-session controls.

**Suggested improvement:** Keep product identity in the heading. Put the engine credit in a caption that can ellipsize. On a nowrap toolbar, the identity cluster may shrink; the action cluster must not.

**Principle:** A chrome heading that changes with a backend or provider name will starve sibling controls on a nowrap mobile header. Bind the heading to the stable product identity and demote variable credits to a caption that is allowed to truncate.
