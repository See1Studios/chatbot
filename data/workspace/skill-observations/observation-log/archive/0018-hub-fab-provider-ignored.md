---
id: 18
title: Hub FAB provider tray did not switch the live session
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot Hub FAB vs :3011 compact iframe, no skill-families.md registry
area: /volume1/web/index.html FAB JS + static/app.js compact boot
date: 2026-09-18
session_context: After verifying the gallery-404 fix on ⚡소생, continued self-improve; FAB tray set localStorage but iframe ensureSession/openSession overwrote it with the active session's provider
parked_until:
resolved: 2026-09-18
resolution: FAB openPopup now passes ?provider= on first iframe load and postMessages chatbot-select-provider on later picks. Compact boot honors the query after ensureSession and swaps via selectProvider. Static only — Hub + Ctrl+Shift+R, no host restart.
reference:
---

**Issue:** Hub FAB tray wrote `chatbot.provider` to localStorage then opened `http://host:3011/?compact=1` with the provider id ignored. The iframe's `openSession()` then copied the already-active session's provider back into localStorage and the dropdown, so picking Grok/Claude/OmniRoute on the Hub button never actually swapped the backend.

**Suggested improvement:** Put `?provider=` on the compact iframe URL; after `ensureSession()`, if that intent differs from the restored session, call `selectProvider`. If the iframe is already loaded, `postMessage({type:'chatbot-select-provider'})` with hostname check instead of a full reload.

**Principle:** A launcher that shares one live session with an embedded app cannot treat localStorage as a command — the embed's session restore will win. Pass the choice as an explicit intent (query or postMessage) and apply it after restore.
