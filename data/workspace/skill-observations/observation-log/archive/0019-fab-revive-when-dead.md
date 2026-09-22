---
id: 19
title: Hub FAB should revive the host when the chat process is down
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot Hub FAB vs :3011 compact iframe, no skill-families.md registry
area: /volume1/web/index.html FAB JS + hub revive API
date: 2026-09-18
session_context: 실장님 noted CPR (⋯ 호스트 소생) only works while the chat UI is loaded from :3011, so a dead host cannot be revived from the control they actually use
parked_until:
resolved: 2026-09-18
resolution: Hub FAB now polls chatbot.php status every 8s independently of :3011. When offline the FAB becomes the revive control (grayscale + ⚡), click posts the existing hub revive API, overlay shows progress, and the iframe reloads on recovery. Static hub only — Ctrl+Shift+R, no host restart.
reference:
---

**Issue:** The in-chat defibrillate control lives inside the surface served by :3011. When that process is down, the FAB still tried to open a dead iframe, and the only working revive button was a small service-card control most sessions never click.

**Suggested improvement:** Keep recovery on the Hub page (PHP + port ping), not inside the dying host. When 3011 is down, the always-visible FAB should be the revive button.

**Principle:** Recovery controls must live outside the failing system — an emergency action that requires the dead UI to load is not an emergency action.
