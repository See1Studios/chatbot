---
id: 26
title: Session management belongs in the chat, not the header
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace UI, no skill-families.md registry
area: static chat header vs in-log session actions
date: 2026-09-18
session_context: 실장님 asked to remove the header 새 세션 button and show session tools in the chat window when the situation calls for it
parked_until:
resolved: 2026-09-18
resolution: Removed header #newSession. Session actions now park at the end of #log — quiet chips after a real turn, the existing soft/hard prompt when the session is long. Sessions tab got 새 세션 / 맥락 이어가기. Compact/keyboard no longer hide the in-log card. Static only, app.js?v=46.
reference:
---

**Issue:** The header always showed a primary 새 세션 button, crowding the mobile/compact bar (see also 0022) while the actual "session is getting long" banner lived in chrome and was `display:none` in compact/keyboard-open — so the persistent header control was the only way to start a new chat in the popup.

**Suggested improvement:** Put session management in the conversation itself, shown when there is something to do (a turn has happened, or token pressure), and keep a 새 세션 control on the Sessions tab.

**Principle:** Always-on header chrome is the wrong place for actions that only make sense at a pause in the conversation. Relocate them to the surface the user is already looking at, and only show them in that situation.
