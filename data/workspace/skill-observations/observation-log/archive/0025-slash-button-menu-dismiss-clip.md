---
id: 25
title: Slash picker opened then immediately dismissed or clipped on mobile
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace UI, no skill-families.md registry
area: static chat composer — slash trigger button and menu
date: 2026-09-18
session_context: After the Antigravity caption change, 실장님 reported the / button looked broken
parked_until:
resolved: 2026-09-18
resolution: Slash menu is position:fixed above the composer, 450ms outside-dismiss guard, button stopPropagation, empty input seeds /. app.js?v=45. Static only.
reference:
---

**Issue:** Tapping the composer `/` button opened the command menu then immediately closed it, or the menu was clipped by `.wrap { overflow:hidden }` once the mobile keyboard resized the viewport. The button also did not insert `/`, so the next keystroke hid the menu.

**Suggested improvement:** Treat picker popovers as viewport-fixed layers, ignore the opening pointer for outside-dismiss, and seed the trigger character so the input filter stays in slash mode.

**Principle:** A control that both opens a popover and focuses an input must not let the same gesture, or the resulting layout shift, count as an outside dismiss.
